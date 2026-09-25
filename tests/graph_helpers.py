"""Scripted fakes for the graph and CLI tests: a guard result, a planner that plays back specs, a clock."""

from rig_agent.agent.planner import PlanResult
from rig_agent.config import Settings
from rig_agent.graph.nodes import GraphDeps
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.state import UnityResult

ACCEPT = GuardResult(accepted=True, category="ok", reason="A humanoid request.")

GOOD = {
    "character_summary": "a chibi knight",
    "style": "chibi knight",
    "preset": "chibi",
    "view": "front",
    "rest_pose": "A_pose",
    "optional_bones": ["hands"],
}


def horn(**kw):
    """A spec that builds but fails validation: a mirrored horn pointing straight up."""
    data = {
        "name": "extra_horn",
        "parent": "head",
        "direction_deg": 90,
        "length_ratio": 0.1,
        "mirror": True,
    }
    data.update(kw)
    return dict(GOOD, extra_bones=[data])


BAD_1 = horn()  # 1 error
BAD_2 = dict(
    GOOD, extra_bones=[horn()["extra_bones"][0], horn()["extra_bones"][0] | {"name": "extra_horn2"}]
)  # 2 errors
UNBUILDABLE = dict(
    GOOD,
    extra_bones=[
        {"name": "extra_x", "parent": "no_such_bone", "direction_deg": 0, "length_ratio": 0.1}
    ],
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakePlanner:
    """Plays back specs (or exceptions) and records every call it receives."""

    def __init__(
        self, *steps, clock=None, seconds=0.0, requests=3, tool_calls=2, tokens=(1000, 200)
    ):
        self.steps = list(steps)
        self.calls = []
        self.clock, self.seconds = clock, seconds
        self.requests, self.tool_calls, self.tokens = requests, tool_calls, tokens

    def __call__(
        self,
        description,
        view=None,
        *,
        previous=None,
        report=None,
        limits=None,
        timeout=None,
        progress=None,
    ):
        self.calls.append(
            {
                "description": description,
                "view": view,
                "previous": previous,
                "report": report,
                "limits": limits,
                "timeout": timeout,
            }
        )
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if self.clock:
            self.clock.now += self.seconds
        if isinstance(step, BaseException):
            raise step
        if progress:
            progress("  [  0.1s] -> list_vocabulary()")
        return PlanResult(
            RigSpec.model_validate(step), self.requests, self.tool_calls, *self.tokens
        )


def make_deps(planner, *, guard=ACCEPT, clock=None, config=None, lines=None, unity=None):
    def check_input(text):
        if isinstance(guard, BaseException):
            raise guard
        return guard

    return GraphDeps(
        check_input=check_input,
        plan=planner,
        clock=clock or Clock(),
        say=(lines.append if lines is not None else (lambda m: None)),
        config=config or Settings(_env_file=None),
        unity=unity,
    )


class FakeDelivery:
    """A stand-in for UnityDelivery that records what the graph asks of it."""

    def __init__(self, apply_result=None, verify_result=None):
        self.apply_result = apply_result or UnityResult(status="applied", detail="import triggered")
        self.verify_result = verify_result or UnityResult(
            status="applied", detail="25 bones verified"
        )
        self.applied = []
        self.verified = []

    def apply(self, skeleton):
        self.applied.append(skeleton)
        return self.apply_result

    def verify(self, skeleton):
        self.verified.append(skeleton)
        return self.verify_result
