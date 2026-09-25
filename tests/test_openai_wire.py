"""The planner and guard talk to OpenAI through the real client; only the network is faked.

An httpx MockTransport records each request and answers in the Chat Completions format, so these
tests cover what is sent (model, instructions, tools) and that a real reply shape is parsed.
"""

import json

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from rig_agent.agent.planner import build_planner, plan
from rig_agent.guardrails.input_guard import build_guard_agent, check_input

SPEC = {
    "character_summary": "a chibi knight",
    "style": "chibi knight",
    "preset": "chibi",
    "view": "front",
    "rest_pose": "A_pose",
}


def completion(tool_name, arguments, call_id="call_1"):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5.4-mini",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


def fake_openai(model_name, replies):
    """A real OpenAIChatModel whose HTTP layer records requests and plays back `replies`."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url, json.loads(request.content)))
        return httpx.Response(200, json=replies[min(len(seen) - 1, len(replies) - 1)])

    client = AsyncOpenAI(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    model = OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))
    return model, seen


def test_the_planner_request_carries_the_model_prompt_and_all_tools():
    model, seen = fake_openai("gpt-5.4-mini", [completion("final_result", SPEC)])
    result = plan("a chibi knight", agent=build_planner(model))
    assert result.spec.preset == "chibi"

    url, body = seen[0]
    assert str(url) == "https://api.openai.com/v1/chat/completions"
    assert body["model"] == "gpt-5.4-mini"
    tool_names = [t["function"]["name"] for t in body["tools"]]
    assert tool_names == [
        "list_vocabulary", "get_preset", "get_view_rules", "describe_proportions",
        "dry_run_validate", "list_existing_bones", "final_result",
    ]  # fmt: skip
    system = json.dumps(body["messages"][0])
    assert "2D technical animator" in system and "Guardrails" in system
    assert "<character_description>" in json.dumps(body["messages"][-1])


def test_the_output_tool_schema_is_the_rigspec():
    model, seen = fake_openai("gpt-5.4-mini", [completion("final_result", SPEC)])
    plan("a chibi knight", agent=build_planner(model))
    final = next(t for t in seen[0][1]["tools"] if t["function"]["name"] == "final_result")
    schema = final["function"]["parameters"]
    assert {"character_summary", "style", "view", "rest_pose"} <= set(schema["required"])
    assert "extra_bones" in schema["properties"]


def test_a_tool_call_round_trip_over_http():
    replies = [
        completion("get_preset", {"name": "chibi"}, "call_a"),
        completion("final_result", SPEC, "call_b"),
    ]
    model, seen = fake_openai("gpt-5.4-mini", replies)
    result = plan("a chibi knight", agent=build_planner(model))
    assert (result.requests, result.tool_calls) == (2, 1)
    assert (result.input_tokens, result.output_tokens) == (240, 60)

    second = seen[1][1]["messages"]
    tool_message = next(m for m in second if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "call_a"
    assert json.loads(tool_message["content"])["base"]["heads_tall"] == 3.0


def test_the_guard_request_uses_the_small_model_and_parses_the_verdict():
    verdict = {
        "accepted": False,
        "category": "non_humanoid",
        "reason": "A horse.",
        "suggestion": "Try a person.",
    }
    model, seen = fake_openai("gpt-5.4-nano", [completion("final_result", verdict)])
    result = check_input("rig a horse", build_guard_agent(model))
    assert result.category == "non_humanoid" and not result.accepted
    body = seen[0][1]
    assert body["model"] == "gpt-5.4-nano"
    assert [t["function"]["name"] for t in body["tools"]] == ["final_result"]
    assert "input guardrail" in json.dumps(body["messages"][0])
