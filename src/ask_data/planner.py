"""Step 1: ask the model how a question should be answered (a plan, not an answer)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .periods import Period
from .semantic import SemanticQuery

Route = Literal["semantic", "verified", "sql", "clarify", "out_of_scope"]


class VerifiedCall(BaseModel):
    id: str
    period: Period | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    days: int | None = Field(default=None, ge=1, le=3650)


class Clarify(BaseModel):
    question: str
    options: list[str] = []


class Plan(BaseModel):
    route: Route
    restated: str = ""
    query: SemanticQuery | None = None
    verified: VerifiedCall | None = None
    clarify: Clarify | None = None
    reason: str | None = None


class PlanError(ValueError):
    pass


def parse(text: str) -> Plan:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanError(f"not valid JSON: {e}") from e
    try:
        plan = Plan.model_validate(data)
    except ValidationError as e:
        raise PlanError(str(e)) from e
    required = {"semantic": plan.query, "verified": plan.verified, "clarify": plan.clarify}
    if plan.route in required and required[plan.route] is None:
        raise PlanError(f"route '{plan.route}' needs its '{ {'semantic': 'query'}.get(plan.route, plan.route)}' block")
    return plan
