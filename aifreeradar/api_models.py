"""Public JSON contracts, independent of application startup and persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from .models import (
    Category,
    Change,
    NewsItem,
    Record,
    Resource,
    ResourceReview,
    ReviewAction,
    RunStats,
    Scope,
    UserAction,
)


class CreateTaskRequest(Scope):
    categories: list[Category] = Field(...)


class RunRead(Record):
    id: str
    trigger: Literal["manual", "scheduled", "catchup"]
    scope: Scope
    status: Literal["running", "success", "partial", "failed"]
    started_at: datetime
    finished_at: datetime | None
    error: str
    notes: list[str]
    schedule_day: str | None
    stats: RunStats | None
    has_briefing: bool


class LeadRead(Record):
    resource: Resource
    review: ResourceReview


class ReviewRead(Record):
    review: ResourceReview
    actions: list[UserAction]


class ReviewRequest(Record):
    action: ReviewAction
    note: str = ""


class ResourceDetailRead(Record):
    resource: Resource
    history: list[Change]
    review: ResourceReview
    actions: list[UserAction]
    messages: list[NewsItem] = Field(default_factory=list)


class TaskDetailRead(Record):
    run: RunRead
    changes: list[Change]
    messages: list[NewsItem] = Field(default_factory=list)


class BriefingRead(Record):
    run: RunRead
    html: str


class ApiError(Record):
    detail: str


class AppRead(Record):
    version: str
    default_scope: Scope
    schedule_enabled: bool
    schedule_time: str
    active_run: RunRead | None
    categories: dict[str, str]
    resource_statuses: dict[str, str]
    china_policies: dict[str, str]
    review_states: dict[str, str]
    open_leads: int
    labels: dict[str, str]


class SettingFieldRead(Record):
    value: JsonValue | None = None
    configured: bool = False
    source: Literal["db", "toml", "default", "env", "missing", "read_only"]


class SettingsRead(Record):
    version: int
    fields: dict[str, SettingFieldRead]


class SettingsPatchRequest(Record):
    version: int
    values: dict[str, JsonValue] = Field(default_factory=dict)
    secrets: dict[str, str | None] = Field(default_factory=dict)


class SettingsResetRequest(Record):
    version: int
    keys: list[str] = Field(...)


class SettingsTestRequest(Record):
    target: Literal["model", "search"]


class SettingsTestRead(Record):
    ok: bool
    detail: str
