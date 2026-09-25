import pytest

from rig_agent.config import Settings
from rig_agent.llm import MissingApiKeyError, make_model


def config(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults_use_the_given_endpoint_and_models():
    s = config()
    assert s.openai_base_url == "https://api.openai.com/v1"
    assert (s.planner_model, s.guard_model) == ("gpt-5.4-mini", "gpt-5.4-nano")
    assert s.openai_api_key is None and s.primary_provider == "openai"


def test_the_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PLANNER_MODEL", "other-model")
    s = config()
    assert s.openai_api_key == "sk-test" and s.planner_model == "other-model"


def test_the_key_is_read_from_a_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-file\n")
    assert Settings(_env_file=env).openai_api_key == "sk-from-file"


def test_an_empty_key_in_the_env_file_counts_as_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=\n")
    with pytest.raises(MissingApiKeyError, match=".env"):
        make_model("gpt-5.4-mini", Settings(_env_file=env))


def test_a_model_is_built_without_touching_the_network():
    model = make_model("gpt-5.4-mini", config(openai_api_key="sk-test"))
    assert model.model_name == "gpt-5.4-mini"
    assert "api.openai.com" in str(model.client.base_url)


def test_a_custom_base_url_is_used():
    model = make_model("m", config(openai_api_key="k", openai_base_url="http://localhost:1234/v1"))
    assert "localhost:1234" in str(model.client.base_url)


def test_missing_key_raises_a_clear_error():
    with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
        make_model("gpt-5.4-mini", config())


# ---- provider selection and failover (LLD 3.13) ----------------------------------------------

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel

from rig_agent.llm import build_model, make_anthropic_model
from rig_agent.schemas.guardrail import GuardResult


def test_anthropic_defaults_and_provider_order_setting():
    s = config()
    assert (s.anthropic_planner_model, s.anthropic_guard_model) == (
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
    )
    assert s.primary_provider == "openai"


def test_only_openai_key_gives_a_plain_openai_model():
    planner = build_model("planner", config(openai_api_key="k"))
    guard = build_model("guard", config(openai_api_key="k"))
    assert isinstance(planner, OpenAIChatModel) and planner.model_name == "gpt-5.4-mini"
    assert isinstance(guard, OpenAIChatModel) and guard.model_name == "gpt-5.4-nano"


def test_only_anthropic_key_gives_an_anthropic_model():
    planner = build_model("planner", config(anthropic_api_key="k"))
    guard = build_model("guard", config(anthropic_api_key="k"))
    assert isinstance(planner, AnthropicModel) and planner.model_name == "claude-sonnet-5"
    assert guard.model_name == "claude-haiku-4-5-20251001"


def test_both_keys_give_a_fallback_with_the_primary_first():
    model = build_model("planner", config(openai_api_key="a", anthropic_api_key="b"))
    assert isinstance(model, FallbackModel)
    assert isinstance(model.models[0], OpenAIChatModel)
    assert isinstance(model.models[1], AnthropicModel)


def test_the_primary_provider_can_be_switched():
    model = build_model(
        "planner", config(openai_api_key="a", anthropic_api_key="b", primary_provider="anthropic")
    )
    assert isinstance(model.models[0], AnthropicModel)
    assert isinstance(model.models[1], OpenAIChatModel)


def test_a_primary_without_a_key_is_skipped():
    model = build_model("planner", config(anthropic_api_key="b", primary_provider="openai"))
    assert isinstance(model, AnthropicModel)


def test_no_keys_at_all_is_a_clear_error():
    with pytest.raises(MissingApiKeyError, match="No API key"):
        build_model("planner", config())


def test_the_anthropic_factory_needs_its_key():
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        make_anthropic_model("claude-sonnet-5", config())


VERDICT = GuardResult(accepted=True, category="ok", reason="Fine.").model_dump(mode="json")


def answering(calls):
    def respond(messages, info):
        calls.append("answered")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, VERDICT)])

    return FunctionModel(respond)


def failing(error, calls):
    def respond(messages, info):
        calls.append("failed")
        raise error

    return FunctionModel(respond)


def test_an_api_error_on_the_primary_fails_over_to_the_second_provider():
    calls = []
    model = FallbackModel(failing(ModelHTTPError(503, "primary"), calls), answering(calls))
    result = Agent(model, output_type=GuardResult).run_sync("hi")
    assert result.output.accepted and calls == ["failed", "answered"]


def test_a_healthy_primary_is_used_alone():
    calls = []
    model = FallbackModel(answering(calls), failing(ModelHTTPError(503, "x"), calls))
    Agent(model, output_type=GuardResult).run_sync("hi")
    assert calls == ["answered"]


def test_a_failure_that_is_not_an_api_error_does_not_fail_over():
    calls = []
    model = FallbackModel(failing(ValueError("a bug"), calls), answering(calls))
    with pytest.raises(ValueError, match="a bug"):
        Agent(model, output_type=GuardResult).run_sync("hi")
    assert calls == ["failed"]


def test_when_every_provider_fails_the_error_reaches_the_caller():
    from pydantic_ai.exceptions import FallbackExceptionGroup

    calls = []
    model = FallbackModel(
        failing(ModelHTTPError(500, "a"), calls), failing(ModelHTTPError(529, "b"), calls)
    )
    with pytest.raises(FallbackExceptionGroup):
        Agent(model, output_type=GuardResult).run_sync("hi")
    assert calls == ["failed", "failed"]
