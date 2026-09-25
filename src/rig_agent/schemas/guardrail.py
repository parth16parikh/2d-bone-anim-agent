"""GuardResult: the typed accept/reject decision the input guardrail returns (LLD 3.8.2)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GuardCategory = Literal[
    "ok",
    "non_humanoid",
    "off_topic",
    "unsupported_view",
    "manipulation",
    "unsafe",
    "too_long",
    "ambiguous",
]


class GuardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    category: GuardCategory
    reason: str = Field(min_length=1)  # one sentence
    suggestion: str | None = None  # suggested rephrasing when the request is not accepted

    @model_validator(mode="after")
    def accepted_matches_category(self):
        if self.accepted != (self.category == "ok"):
            raise ValueError("accepted must be true exactly when the category is 'ok'")
        return self
