"""Builds the chat models the agents run on, with provider failover (LLD 3.13, 5.1)."""

from typing import Literal

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from rig_agent.config import Settings, settings

Role = Literal["planner", "guard"]


class MissingApiKeyError(RuntimeError):
    """No API key is configured, so no live model can be created."""


def make_model(model_name: str, config: Settings | None = None) -> OpenAIChatModel:
    """An OpenAI chat model using the configured base URL and key. Makes no network call."""
    config = config or settings
    if not config.openai_api_key:
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Add it to the .env file in the project root."
        )
    provider = OpenAIProvider(base_url=config.openai_base_url, api_key=config.openai_api_key)
    return OpenAIChatModel(model_name, provider=provider)


def make_anthropic_model(model_name: str, config: Settings | None = None) -> AnthropicModel:
    """An Anthropic chat model using the configured key. Makes no network call."""
    config = config or settings
    if not config.anthropic_api_key:
        raise MissingApiKeyError(
            "ANTHROPIC_API_KEY is not set. Add it to the .env file in the project root."
        )
    return AnthropicModel(model_name, provider=AnthropicProvider(api_key=config.anthropic_api_key))


def build_model(role: Role, config: Settings | None = None) -> Model:
    """The model for a role. With both keys set, the second provider is a failover.

    Each provider's own client already retries twice with exponential backoff; the failover
    only happens after that, on an API error (LLD 3.13).
    """
    config = config or settings
    names = {
        "openai": {"planner": config.planner_model, "guard": config.guard_model},
        "anthropic": {
            "planner": config.anthropic_planner_model,
            "guard": config.anthropic_guard_model,
        },
    }
    keys = {"openai": config.openai_api_key, "anthropic": config.anthropic_api_key}
    order = [
        config.primary_provider,
        "anthropic" if config.primary_provider == "openai" else "openai",
    ]

    models: list[Model] = []
    for provider in order:
        if not keys[provider]:
            continue
        if provider == "openai":
            models.append(make_model(names["openai"][role], config))
        else:
            models.append(make_anthropic_model(names["anthropic"][role], config))
    if not models:
        raise MissingApiKeyError(
            "No API key is set. Add OPENAI_API_KEY (and optionally ANTHROPIC_API_KEY) to the "
            ".env file in the project root."
        )
    return models[0] if len(models) == 1 else FallbackModel(*models)
