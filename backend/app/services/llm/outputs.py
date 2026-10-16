"""Structured outputs we ask the LLM for. Kept flat and simple so free-tier models follow them."""

from typing import Literal

from pydantic import BaseModel, Field


class Resource(BaseModel):
    title: str
    url: str = ""


class ItemDraft(BaseModel):
    type: Literal["topic", "skill", "task", "milestone"] = "topic"
    title: str
    description: str = ""
    est_hours: float = Field(default=4, ge=0.25, le=500)
    resources: list[Resource] = []


class PhaseDraft(BaseModel):
    title: str
    items: list[ItemDraft]


class RoadmapDraft(BaseModel):
    summary: str = ""
    suggested_target_date: str | None = Field(default=None, description="YYYY-MM-DD")
    phases: list[PhaseDraft]


class Fact(BaseModel):
    key: str
    value: str


class IntakeTurn(BaseModel):
    action: Literal["ask", "propose"]
    message: str = Field(description="What to say to the user, in a friendly coaching tone")
    questions: list[str] = []
    facts: list[Fact] = Field(default=[], description="Facts learned about the user so far")
    roadmap: RoadmapDraft | None = None


class LinkDraft(BaseModel):
    goal_id: int
    roadmap_item_id: int | None = None
    relevance: float = Field(default=1.0, ge=0, le=1)
    reason: str = ""


class ActivityDraft(BaseModel):
    description: str
    minutes: int = Field(ge=0, le=1440)
    kind: Literal["learn", "build", "ship", "network", "apply", "admin", "job", "leisure", "waste", "other"] = "other"
    links: list[LinkDraft] = []


class GoalImpact(BaseModel):
    goal_id: int
    impact: float = Field(ge=0, le=10, description="0 = no progress, 10 = exceptional progress today")
    note: str = ""


class ItemProgress(BaseModel):
    roadmap_item_id: int
    hours: float = Field(ge=0, le=24)
    completed: bool = False


class PlanDraft(BaseModel):
    time_block: str = Field(default="", description="e.g. 09:00-10:30")
    title: str
    minutes: int = Field(default=60, ge=5, le=720)
    goal_id: int | None = None
    roadmap_item_id: int | None = None


class DayAnalysis(BaseModel):
    activities: list[ActivityDraft]
    goal_impacts: list[GoalImpact] = []
    item_progress: list[ItemProgress] = []
    went_well: list[str] = []
    went_badly: list[str] = []
    tomorrow: list[PlanDraft] = []
    tip: str = ""


class ReplanDraft(BaseModel):
    strategy: Literal["shift", "reduce_scope", "increase_hours"]
    reason: str
    skip_item_ids: list[int] = []
    new_goal_hours_per_day: float | None = Field(default=None, ge=0.25, le=16)
    message: str = ""


class TrendPick(BaseModel):
    title: str
    why_relevant: str
    est_hours: float = Field(default=3, ge=0.5, le=100)
    links: list[Resource] = []


class TrendPicks(BaseModel):
    suggestions: list[TrendPick] = Field(default=[], max_length=3)


class WeeklyText(BaseModel):
    summary: str
    wins: list[str] = []
    gaps: list[str] = []
    recommendations: list[str] = []
