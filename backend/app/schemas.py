import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.llm.outputs import DayAnalysis, RoadmapDraft


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----- settings -----
class SettingsOut(BaseModel):
    name: str | None
    email: str
    timezone: str
    reminder_time: str
    morning_push: bool
    daily_available_hours: float
    has_own_key: bool
    server_llm_available: bool
    vapid_public_key: str


class SettingsIn(BaseModel):
    name: str | None = None
    timezone: str | None = None
    reminder_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    morning_push: bool | None = None
    daily_available_hours: float | None = Field(default=None, gt=0, le=16)
    gemini_api_key: str | None = None  # "" clears it


class PushSubIn(BaseModel):
    endpoint: str
    keys: dict[str, str]


# ----- goals & roadmap -----
GoalCategory = Literal["career", "venture", "health", "learning", "other"]


class GoalIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = ""
    why: str = ""
    category: GoalCategory = "other"
    priority: int = Field(default=3, ge=1, le=5)
    target_date: date | None = None


class GoalPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    why: str | None = None
    category: GoalCategory | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    target_date: date | None = None
    status: Literal["active", "paused", "done"] | None = None


class TimelineOut(BaseModel):
    planned_hours: float
    done_hours: float
    behind_hours: float
    behind_days: float
    behind_pct: float
    overdue_items: int
    hours_per_day: float
    state: str
    threshold_days: int = 3


class GoalOut(ORM):
    id: int
    title: str
    description: str
    why: str
    category: str
    priority: int
    target_date: date | None
    status: str
    intake_status: str
    context: dict
    proposed_roadmap: dict | None
    created_at: datetime
    statement: str = ""
    success_criteria: list = []
    hours_per_day: float | None = None
    days_per_week: int | None = None
    routine: list = []
    progress_pct: float = 0
    timeline: TimelineOut | None = None
    pending_replan_id: int | None = None


class ChatMessageOut(ORM):
    id: int
    role: str
    content: str
    created_at: datetime


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    messages: list[ChatMessageOut]
    goal: GoalOut


class RoadmapItemOut(ORM):
    id: int
    order: int
    type: str
    title: str
    description: str
    resources: list
    est_hours: float
    planned_start: date | None
    planned_due: date | None
    status: str
    hours_logged: float
    completed_at: date | None
    source: str


class RoadmapPhaseOut(ORM):
    id: int
    title: str
    order: int
    start_date: date | None
    due_date: date | None
    items: list[RoadmapItemOut]


class FeasibilityOut(BaseModel):
    feasible: bool
    realistic_date: date
    required_hours_per_day: float | None


class RoadmapOut(BaseModel):
    goal: GoalOut
    phases: list[RoadmapPhaseOut]
    feasibility: FeasibilityOut | None = None


class ApproveIn(BaseModel):
    roadmap: RoadmapDraft
    target_date: date | None = None


ItemType = Literal["topic", "skill", "task", "milestone"]


class ItemIn(BaseModel):
    phase_id: int
    type: ItemType = "topic"
    title: str
    description: str = ""
    est_hours: float = Field(default=2, gt=0, le=500)


class ItemPatch(BaseModel):
    type: ItemType | None = None
    title: str | None = None
    description: str | None = None
    est_hours: float | None = Field(default=None, gt=0, le=500)
    status: Literal["todo", "in_progress", "done", "skipped"] | None = None
    planned_start: date | None = None
    planned_due: date | None = None
    hours_logged: float | None = Field(default=None, ge=0)


# ----- entries -----
class ScheduleBlock(BaseModel):
    start: str = ""
    end: str = ""
    activity: str = ""
    notes: str = ""
    kind: str | None = None
    goal_id: int | None = None
    roadmap_item_id: int | None = None


class EntryIn(BaseModel):
    schedule: list[ScheduleBlock] = []
    free_text: str = ""
    energy: int | None = Field(default=None, ge=1, le=5)


class ReviewOut(ORM):
    total_score: float
    per_goal: dict
    went_well: list
    went_badly: list
    tip: str
    drift_minutes: int
    adherence: float | None
    used_llm: bool
    rest_day: bool = False
    breakdown: dict = {}


class ActivityLinkOut(ORM):
    goal_id: int
    roadmap_item_id: int | None
    relevance: float
    reason: str


class ActivityOut(ORM):
    id: int
    description: str
    minutes: int
    kind: str
    links: list[ActivityLinkOut]


class EntryOut(ORM):
    id: int | None = None
    date: date
    schedule: list
    free_text: str
    energy: int | None
    draft: dict | None
    analyzed_at: datetime | None
    activities: list[ActivityOut] = []
    review: ReviewOut | None = None


class DraftOut(BaseModel):
    draft: DayAnalysis
    used_llm: bool


class ConfirmIn(BaseModel):
    analysis: DayAnalysis
    used_llm: bool = True


# ----- plan -----
class PlanItemOut(ORM):
    id: int
    date_for: date
    time_block: str
    title: str
    minutes: int
    goal_id: int | None
    roadmap_item_id: int | None
    status: str
    done_minutes: int | None = None
    details: dict = {}


class PlanItemIn(BaseModel):
    date_for: date
    title: str
    time_block: str = ""
    minutes: int = 60
    goal_id: int | None = None
    roadmap_item_id: int | None = None


class PlanPatch(BaseModel):
    status: Literal["open", "done", "partial", "skipped"] | None = None
    done_minutes: int | None = None
    title: str | None = None
    time_block: str | None = None
    minutes: int | None = None
    done_steps: list[int] | None = None  # indexes of the block's steps the user has ticked off


# ----- replans / trends / reviews -----
class ReplanOut(ORM):
    id: int
    goal_id: int
    reason: str
    diff: dict
    status: str
    created_at: datetime


class TrendSuggestionOut(ORM):
    id: int
    goal_id: int
    title: str
    why_relevant: str
    est_hours: float
    links: list
    status: str
    created_at: datetime


class TrendSourceOut(ORM):
    id: int
    name: str
    kind: str
    url: str
    enabled: bool
    user_id: uuid.UUID | None = None


class TrendSourceIn(BaseModel):
    name: str
    url: str
    kind: Literal["rss", "github"] = "rss"


class WeeklyOut(ORM):
    id: int
    week_start: date
    stats: dict
    summary: str
    wins: list
    gaps: list
    recommendations: list
    focus: list = []
    created_at: datetime
