import uuid
from datetime import date, datetime, timezone

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,

)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    name: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    reminder_time: Mapped[str] = mapped_column(String(5), default="21:30")  # HH:MM local
    morning_push: Mapped[bool] = mapped_column(default=False)
    daily_available_hours: Mapped[float] = mapped_column(Float, default=3.0)
    gemini_key_enc: Mapped[str | None] = mapped_column(Text)
    last_reminded_on: Mapped[date | None] = mapped_column(Date)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="other")  # career/venture/health/learning/other
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/paused/done
    intake_status: Mapped[str] = mapped_column(String(20), default="interviewing")
    # interviewing -> roadmap_proposed (web) / commitment_pending (Claude) -> active
    # Agreed with the user during intake (Claude flow). Each *_agreed_at marks a confirmed checkpoint.
    statement: Mapped[str] = mapped_column(Text, default="")  # the exact, measurable goal
    success_criteria: Mapped[list] = mapped_column(JSON, default=list)
    hours_per_day: Mapped[float | None] = mapped_column(Float)  # agreed hours on a working day
    days_per_week: Mapped[int | None] = mapped_column(Integer)
    routine: Mapped[list] = mapped_column(JSON, default=list)  # [{days: ["mon",..], start, end, activity}]
    definition_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    roadmap_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commitment_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The plan as last agreed, for "planned so far": {"start", "done_at_start", "points": [[date, cumulative_h]]}.
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    # What's new: broader things to keep an eye on for this goal (e.g. "AI engineer job requirements").
    watch_topics: Mapped[list] = mapped_column(JSON, default=list)
    trends_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # facts gathered during intake
    proposed_roadmap: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    phases: Mapped[list["RoadmapPhase"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", order_by="RoadmapPhase.order", lazy="selectin"
    )


class GoalChatMessage(Base):
    __tablename__ = "goal_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user/assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapPhase(Base):
    __tablename__ = "roadmap_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    order: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)

    goal: Mapped[Goal] = relationship(back_populates="phases")
    items: Mapped[list["RoadmapItem"]] = relationship(
        back_populates="phase", cascade="all, delete-orphan", order_by="RoadmapItem.order", lazy="selectin"
    )


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("roadmap_phases.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(20), default="topic")  # topic/skill/task/milestone
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[list] = mapped_column(JSON, default=list)  # [{title, url}]
    est_hours: Mapped[float] = mapped_column(Float, default=1.0)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_due: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo/in_progress/done/skipped
    hours_logged: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(10), default="ai")  # ai/user/trend
    search_terms: Mapped[list] = mapped_column(JSON, default=list)  # phrases/synonyms for finding news on it

    phase: Mapped[RoadmapPhase] = relationship(back_populates="items")


class DailyEntry(Base):
    __tablename__ = "daily_entries"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    schedule: Mapped[list] = mapped_column(JSON, default=list)  # [{start, end, activity, notes}]
    free_text: Mapped[str] = mapped_column(Text, default="")
    energy: Mapped[int | None] = mapped_column(Integer)
    draft: Mapped[dict | None] = mapped_column(JSON)  # last analysis draft awaiting confirmation
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    activities: Mapped[list["Activity"]] = relationship(back_populates="entry", cascade="all, delete-orphan", lazy="selectin")
    review: Mapped["DailyReview | None"] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("daily_entries.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    source: Mapped[str] = mapped_column(String(10), default="ai")

    entry: Mapped[DailyEntry] = relationship(back_populates="activities")
    links: Mapped[list["ActivityLink"]] = relationship(back_populates="activity", cascade="all, delete-orphan", lazy="selectin")


class ActivityLink(Base):
    __tablename__ = "activity_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    roadmap_item_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_items.id", ondelete="SET NULL"))
    relevance: Mapped[float] = mapped_column(Float, default=1.0)
    impact: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    confirmed: Mapped[bool] = mapped_column(default=True)

    activity: Mapped[Activity] = relationship(back_populates="links")


class DailyReview(Base):
    __tablename__ = "daily_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("daily_entries.id", ondelete="CASCADE"), unique=True)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    per_goal: Mapped[dict] = mapped_column(JSON, default=dict)  # {goal_id: {score, minutes, rule, llm}}
    went_well: Mapped[list] = mapped_column(JSON, default=list)
    went_badly: Mapped[list] = mapped_column(JSON, default=list)
    tip: Mapped[str] = mapped_column(Text, default="")
    drift_minutes: Mapped[int] = mapped_column(Integer, default=0)
    adherence: Mapped[float | None] = mapped_column(Float)
    used_llm: Mapped[bool] = mapped_column(default=False)
    # Rest/off day: nothing was planned (or the user took the day off). Not scored, excluded from averages,
    # doesn't break the streak.
    rest_day: Mapped[bool] = mapped_column(default=False)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)  # how total_score was computed

    entry: Mapped[DailyEntry] = relationship(back_populates="review")


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date_for: Mapped[date] = mapped_column(Date, index=True)
    time_block: Mapped[str] = mapped_column(String(30), default="")  # e.g. "09:00-10:30"
    title: Mapped[str] = mapped_column(Text)
    minutes: Mapped[int] = mapped_column(Integer, default=60)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    roadmap_item_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_items.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="open")  # open/done/partial/skipped
    done_minutes: Mapped[int | None] = mapped_column(Integer)  # for partial: how much of the block was done


class TrendSource(Base):
    __tablename__ = "trend_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )  # NULL = global default
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # rss/hn/github
    url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # ranking boost for curated sources


class TrendItem(Base):
    __tablename__ = "trend_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("trend_sources.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TrendSuggestion(Base):
    __tablename__ = "trend_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    why_relevant: Mapped[str] = mapped_column(Text, default="")
    est_hours: Mapped[float] = mapped_column(Float, default=2.0)
    links: Mapped[list] = mapped_column(JSON, default=list)  # [{title, url}]
    status: Mapped[str] = mapped_column(String(20), default="new")  # new/added_to_roadmap/dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReplanProposal(Base):
    __tablename__ = "replan_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    # {"changes": [{item_id, title, old_due, new_due, action: shift|skip}], "new_target_date", "daily_hours"}
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending/accepted/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"
    __table_args__ = (UniqueConstraint("user_id", "week_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    wins: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    # 1-3 things to keep in mind the following week: [{"text": ..., "kept": true/false/null}]
    focus: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthClient(Base):
    """Apps (e.g. Claude) registered via OAuth dynamic client registration to use the remote MCP server."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    info: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthRecord(Base):
    """Pending authorizations, authorization codes, access and refresh tokens. Keys are stored as SHA-256 hashes."""

    __tablename__ = "oauth_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # pending/code/access/refresh
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[float] = mapped_column(Float)
