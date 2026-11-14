"""Same-origin JSON API; importing the router never constructs application services."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from filelock import FileLock, Timeout
from pydantic import BaseModel, JsonValue, ValidationError

from .api_models import (
    ApiError,
    AppRead,
    BriefingRead,
    CreateTaskRequest,
    LeadRead,
    ResourceDetailRead,
    ReviewRead,
    ReviewRequest,
    RunRead,
    SettingFieldRead,
    SettingsPatchRequest,
    SettingsRead,
    SettingsResetRequest,
    SettingsTestRead,
    SettingsTestRequest,
    SourceRead,
    TaskDetailRead,
)
from .config import ConfigurationError, Settings
from .models import (
    ACCESS_MODE_LABELS,
    CATEGORY_LABELS,
    CHECK_STATUS_LABELS,
    CHINA_POLICY_LABELS,
    FREE_TYPE_LABELS,
    REVIEW_STATE_LABELS,
    RUN_STATUS_LABELS,
    STATUS_LABELS,
    TRIGGER_LABELS,
    CheckStatus,
    NewsItem,
    Resource,
    ResourceReview,
    ResourceStatus,
    ReviewState,
    Run,
    Scope,
    SourceDefinition,
    SourceEntry,
    SourceSnapshot,
)
from .probes import SettingsProbeError, probe_model, probe_search
from .service import BusyError
from .settings_store import (
    SettingsConflictError,
    SettingsSecretUnavailableError,
    SettingsStore,
    SettingsWriteError,
)
from .sources import SourcePipeline, configured_sources
from .storage import UnknownResource
from .web_content import redact_json, redact_text, render_markdown

try:
    APP_VERSION = version("aifreeradar")
except PackageNotFoundError:
    APP_VERSION = "0.1.0"

CATEGORIES = CATEGORY_LABELS
RESOURCE_STATUSES = {**STATUS_LABELS, "pending": "未核验", "active": "政策已核验"}
CHINA_POLICIES = CHINA_POLICY_LABELS
LABELS = {
    **CATEGORY_LABELS,
    **RESOURCE_STATUSES,
    **CHECK_STATUS_LABELS,
    **FREE_TYPE_LABELS,
    **CHINA_POLICY_LABELS,
    **RUN_STATUS_LABELS,
    **TRIGGER_LABELS,
    **ACCESS_MODE_LABELS,
    "global": "全球资源",
    "china": "中国大陆相关消息（可用性以来源为准）",
    "official": "官方来源",
    "community": "社区线索",
    "new": "新增",
    "changed": "重要变化",
    "restored": "恢复",
    "collection": "收集免费 API 消息",
    "verification": "按需核验政策",
}
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
INVALID_INPUT = "研究范围或筛选条件无效，请检查输入后重试。"
TASK_NOT_FOUND = "未找到这项任务。请返回任务历史选择已有任务。"
RESOURCE_NOT_FOUND = "未找到此资源。请返回资源库选择已有资源。"
IGNORED_RECHECK = "该资源已标记忽略，请先恢复处理后再重查。"
BUSY_MESSAGE = "已有研究任务运行中，当前无法发起另一项任务。查看运行中的任务，完成后再试。"
SOURCE_NOT_FOUND = "未找到此来源。请返回来源管理选择已有来源。"
SOURCE_SNAPSHOT_NOT_FOUND = "未找到此网页版本。请返回来源管理查看已有版本。"
SOURCE_ID_MISMATCH = "来源标识与地址不一致，请刷新页面后重试。"
SOURCE_WRITE_BUSY = "已有研究任务运行中，来源暂不可写入。完成后再试。"
SOURCE_PROCESS_BUSY = "另一进程正在研究，来源暂不可写入。请稍后重试。"
SOURCE_PAGING = "来源条目分页参数无效，请检查后重试。"
SOURCE_INVALID_INPUT = "来源定义无效：请检查公开地址、CSS 选择器、正则表达式、规则标签与类别后重试。"
SETTINGS_CONFLICT = "配置已被其他页面修改，请刷新后重试。"
SETTINGS_SECRET_UNAVAILABLE = "服务端未配置 AIFREERADAR_SECRET_KEY，无法保存密钥。"
SETTINGS_PROBE_FAILED = "设置探测失败，请检查配置后重试。"

router = APIRouter(prefix="/api")


def briefing_file(data_dir: Path, task_id: str) -> Path:
    """Resolve a report by task identity, never by a saved database path."""
    if not TASK_ID.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="简报文件不存在。")
    briefings_dir = (data_dir / "briefings").resolve()
    candidate = (briefings_dir / f"{task_id}.md").resolve()
    if candidate.parent != briefings_dir or not candidate.is_file():
        raise HTTPException(status_code=404, detail="此任务尚无简报文件。请查看任务状态。")
    return candidate


def run_read(run: Run, data_dir: Path) -> RunRead:
    try:
        briefing_file(data_dir, run.id)
        has_briefing = True
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        has_briefing = False
    return RunRead(
        id=run.id,
        trigger=run.trigger,
        scope=run.scope,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        notes=run.notes,
        schedule_day=run.schedule_day,
        stats=run.stats,
        has_briefing=has_briefing,
        research_traces=run.research_traces,
    )


def source_definitions(request: Request) -> list[SourceDefinition]:
    """Effective sources: stored overrides layered over configured definitions."""
    settings = request.app.state.settings
    return request.app.state.repository.list_source_definitions(configured_sources(settings))


def known_source(request: Request, source_id: str) -> SourceDefinition:
    for definition in source_definitions(request):
        if definition.id == source_id:
            return definition
    raise HTTPException(status_code=404, detail=SOURCE_NOT_FOUND)


def source_read(request: Request, definition: SourceDefinition) -> SourceRead:
    state = request.app.state.repository.get_source_state(definition.id)
    return SourceRead(definition=definition, state=state)


@contextmanager
def source_write_lock(request: Request) -> Iterator[None]:
    """Serialise source writes with research, in-process and across processes."""
    manager = request.app.state.manager
    if manager.active is not None:
        raise HTTPException(status_code=409, detail=SOURCE_WRITE_BUSY)
    data_dir = Path(request.app.state.settings.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(data_dir / "research.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise HTTPException(status_code=409, detail=SOURCE_PROCESS_BUSY) from exc
    try:
        if manager.active is not None:
            raise HTTPException(status_code=409, detail=SOURCE_WRITE_BUSY)
        yield
    finally:
        lock.release()


def json_response(
    value: BaseModel | Sequence[BaseModel], settings: Settings, *, status_code: int = 200
) -> JSONResponse:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else [item.model_dump(mode="json") for item in value]
    )
    return JSONResponse(redact_json(cast(JsonValue, payload), settings), status_code=status_code)


def error_response(
    settings: Settings, detail: str, status_code: int, *, headers: dict[str, str] | None = None
) -> JSONResponse:
    response = json_response(ApiError(detail=detail), settings, status_code=status_code)
    if headers:
        response.headers.update(headers)
    return response


def settings_read(store: SettingsStore) -> SettingsRead:
    version, fields = store.describe()
    return SettingsRead(
        version=version,
        fields={
            name: SettingFieldRead.model_validate(field)
            for name, field in fields.items()
        },
    )


def apply_settings(request: Request, current: Settings) -> None:
    previous = request.app.state.settings
    request.app.state.settings = current
    request.app.state.scheduler.on_settings_changed(previous, current)


def _known_run(request: Request, task_id: str) -> Run:
    run = request.app.state.repository.get_run(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    return run


def offers_ended(resource: Resource) -> bool:
    """A resource is history-only when every collected offer has ended explicitly."""
    if resource.messages:
        return all(message.ended for message in resource.messages)
    return resource.status == ResourceStatus.EXPIRED


def open_leads(repository) -> list[tuple[Resource, ResourceReview]]:
    """Historical records still awaiting a traceable source and human review."""
    resources = repository.list_resources()
    reviews = repository.reviews()
    leads: list[tuple[Resource, ResourceReview]] = []
    for resource in resources:
        review = reviews.get(resource.id) or ResourceReview(resource_id=resource.id)
        if review.state != ReviewState.OPEN:
            continue
        if (
            resource.status == ResourceStatus.PENDING
            or resource.check_status != CheckStatus.SUCCESS
        ) and not any(message.sources for message in resource.messages):
            leads.append((resource, review))
    return leads


@router.get("/app", response_model=AppRead)
async def app_info(request: Request):
    settings = request.app.state.settings
    active = request.app.state.manager.active
    return json_response(
        AppRead(
            version=APP_VERSION,
            default_scope=settings.default_scope,
            schedule_enabled=settings.schedule_enabled,
            schedule_time=settings.schedule_time,
            active_run=run_read(active, settings.data_dir) if active is not None else None,
            categories=CATEGORIES,
            resource_statuses=RESOURCE_STATUSES,
            china_policies=CHINA_POLICIES,
            review_states=REVIEW_STATE_LABELS,
            open_leads=len(open_leads(request.app.state.repository)),
            labels=LABELS,
        ),
        settings,
    )


@router.get("/settings", response_model=SettingsRead)
async def read_settings(request: Request):
    settings = request.app.state.settings
    return json_response(settings_read(request.app.state.settings_store), settings)


@router.patch(
    "/settings",
    response_model=SettingsRead,
    responses={
        409: {"model": ApiError},
        422: {"model": ApiError},
        503: {"model": ApiError},
    },
)
async def update_settings(request: Request, body: SettingsPatchRequest):
    settings = request.app.state.settings
    try:
        current = request.app.state.settings_store.update(
            dict(body.values), dict(body.secrets), body.version
        )
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail=SETTINGS_CONFLICT) from exc
    except SettingsSecretUnavailableError as exc:
        raise HTTPException(status_code=503, detail=SETTINGS_SECRET_UNAVAILABLE) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="配置值无效，请检查后重试。") from exc
    except (SettingsWriteError, ConfigurationError) as exc:
        raise HTTPException(status_code=422, detail=redact_text(str(exc), settings)) from exc
    apply_settings(request, current)
    return json_response(
        settings_read(request.app.state.settings_store), request.app.state.settings
    )


@router.post(
    "/settings/reset",
    response_model=SettingsRead,
    responses={
        409: {"model": ApiError},
        422: {"model": ApiError},
        503: {"model": ApiError},
    },
)
async def reset_settings(request: Request, body: SettingsResetRequest):
    settings = request.app.state.settings
    try:
        current = request.app.state.settings_store.reset(body.keys, body.version)
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail=SETTINGS_CONFLICT) from exc
    except SettingsSecretUnavailableError as exc:
        raise HTTPException(status_code=503, detail=SETTINGS_SECRET_UNAVAILABLE) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="配置值无效，请检查后重试。") from exc
    except (SettingsWriteError, ConfigurationError) as exc:
        raise HTTPException(status_code=422, detail=redact_text(str(exc), settings)) from exc
    apply_settings(request, current)
    return json_response(
        settings_read(request.app.state.settings_store), request.app.state.settings
    )


@router.post(
    "/settings/test",
    response_model=SettingsTestRead,
    responses={422: {"model": ApiError}, 502: {"model": ApiError}},
)
async def test_settings(request: Request, body: SettingsTestRequest):
    settings = request.app.state.settings
    try:
        detail = (
            await probe_model(settings)
            if body.target == "model"
            else await probe_search(settings)
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=422, detail=redact_text(str(exc), settings)) from exc
    except SettingsProbeError as exc:
        raise HTTPException(status_code=502, detail=redact_text(str(exc), settings)) from exc
    except Exception:  # noqa: BLE001 - probe transport failures must not leak details
        raise HTTPException(status_code=502, detail=SETTINGS_PROBE_FAILED) from None
    return json_response(SettingsTestRead(ok=True, detail=detail), settings)


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(request: Request):
    settings = request.app.state.settings
    return json_response(
        [source_read(request, definition) for definition in source_definitions(request)],
        settings,
    )


@router.put(
    "/sources/{source_id}",
    response_model=SourceRead,
    responses={
        404: {"model": ApiError},
        409: {"model": ApiError},
        422: {"model": ApiError},
    },
)
async def save_source(request: Request, source_id: str, body: SourceDefinition):
    if body.id != source_id:
        raise HTTPException(status_code=422, detail=SOURCE_ID_MISMATCH)
    known_source(request, source_id)
    with source_write_lock(request):
        saved = request.app.state.repository.save_source_definition(body)
    return json_response(source_read(request, saved), request.app.state.settings)


@router.get(
    "/sources/{source_id}/entries",
    response_model=list[SourceEntry],
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def source_entries(request: Request, source_id: str, limit: int = 100, offset: int = 0):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=422, detail=SOURCE_PAGING)
    known_source(request, source_id)
    entries = request.app.state.repository.list_source_entries(
        source_id, limit=limit, offset=offset
    )
    return json_response(entries, request.app.state.settings)


@router.get(
    "/sources/{source_id}/snapshots",
    response_model=list[SourceSnapshot],
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def source_snapshots(request: Request, source_id: str, limit: int = 20):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail=SOURCE_PAGING)
    known_source(request, source_id)
    snapshots = request.app.state.repository.list_source_snapshots(source_id, limit=limit)
    return json_response(snapshots, request.app.state.settings)


@router.get(
    "/source-snapshots/{snapshot_id}",
    response_model=SourceSnapshot,
    responses={404: {"model": ApiError}},
)
async def source_snapshot(request: Request, snapshot_id: str):
    snapshot = request.app.state.repository.get_source_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=SOURCE_SNAPSHOT_NOT_FOUND)
    return json_response(snapshot, request.app.state.settings)


@router.post(
    "/sources/{source_id}/replay",
    response_model=list[SourceEntry],
    responses={
        404: {"model": ApiError},
        409: {"model": ApiError},
    },
)
async def replay_source_rules(request: Request, source_id: str):
    known_source(request, source_id)
    settings = request.app.state.settings
    with source_write_lock(request):
        try:
            entries = SourcePipeline(settings, request.app.state.repository).replay_rules(source_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=SOURCE_NOT_FOUND) from exc
    return json_response(entries, settings)


@router.get("/leads", response_model=list[LeadRead])
async def leads(request: Request):
    settings = request.app.state.settings
    records = open_leads(request.app.state.repository)
    # Pending records first; within each group the most recently checked leads.
    records.sort(
        key=lambda item: (
            item[0].status != ResourceStatus.PENDING,
            -item[0].last_checked_at.timestamp(),
        )
    )
    return json_response(
        [LeadRead(resource=resource, review=review) for resource, review in records],
        settings,
    )


@router.get("/messages", response_model=list[NewsItem], responses={422: {"model": ApiError}})
async def messages(
    request: Request, category: str = "", include_ended: bool = False, resource_id: str = ""
):
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=INVALID_INPUT)
    records = request.app.state.repository.list_messages(
        category=category or None,
        include_ended=include_ended,
        resource_id=resource_id or None,
    )
    return json_response(records, request.app.state.settings)


@router.get("/resources", response_model=list[Resource], responses={422: {"model": ApiError}})
async def resources(
    request: Request,
    category: str = "",
    china_policy: str = "",
    status: str = "",
    include_ended: bool = False,
):
    if (
        (category and category not in CATEGORIES)
        or (china_policy and china_policy not in CHINA_POLICIES)
        or (status and status not in RESOURCE_STATUSES)
    ):
        raise HTTPException(status_code=422, detail=INVALID_INPUT)
    records = request.app.state.repository.list_resources(
        category=category or None, china_policy=china_policy or None
    )
    if status:
        # Explicit expired history includes resources whose collected offers all ended,
        # even while their strict verification status stays pending.
        records = [
            resource
            for resource in records
            if resource.status.value == status
            or (status == ResourceStatus.EXPIRED.value and offers_ended(resource))
        ]
    if not include_ended and status != ResourceStatus.EXPIRED.value:
        records = [resource for resource in records if not offers_ended(resource)]
    return json_response(records, request.app.state.settings)


@router.get(
    "/resources/{resource_id}",
    response_model=ResourceDetailRead,
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def resource_detail(request: Request, resource_id: str):
    repository = request.app.state.repository
    resource = repository.get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="未找到此资源。请返回资源库选择已有资源。")
    return json_response(
        ResourceDetailRead(
            resource=resource,
            history=repository.history(resource_id),
            review=repository.review(resource_id),
            actions=repository.actions(resource_id),
            messages=repository.list_messages(resource_id=resource_id, include_ended=True),
        ),
        request.app.state.settings,
    )


@router.get("/reviews", response_model=list[ResourceReview])
async def reviews(request: Request):
    settings = request.app.state.settings
    return json_response(list(request.app.state.repository.reviews().values()), settings)


@router.post(
    "/resources/{resource_id}/review",
    response_model=ReviewRead,
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def review_resource(request: Request, resource_id: str, body: ReviewRequest):
    repository = request.app.state.repository
    if len(body.note.strip()) > 2000:
        raise HTTPException(status_code=422, detail=INVALID_INPUT)
    try:
        review, _ = repository.apply_review(resource_id, body.action, note=body.note)
    except UnknownResource as exc:
        raise HTTPException(status_code=404, detail=RESOURCE_NOT_FOUND) from exc
    return json_response(
        ReviewRead(review=review, actions=repository.actions(resource_id)),
        request.app.state.settings,
    )


@router.post(
    "/resources/{resource_id}/recheck",
    status_code=202,
    response_model=RunRead,
    responses={404: {"model": ApiError}, 409: {"model": ApiError}},
)
async def recheck_resource(request: Request, resource_id: str):
    settings = request.app.state.settings
    repository = request.app.state.repository
    resource = repository.get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail=RESOURCE_NOT_FOUND)
    if repository.review(resource_id).state == ReviewState.IGNORED:
        raise HTTPException(status_code=409, detail=IGNORED_RECHECK)
    scope = Scope(categories=[resource.category], region="global", resource_ids=[resource.id])
    try:
        run = await request.app.state.manager.start(scope, trigger="manual")
    except BusyError as exc:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE) from exc
    return json_response(run_read(run, settings.data_dir), settings, status_code=202)


@router.get("/tasks", response_model=list[RunRead])
async def tasks(request: Request):
    settings = request.app.state.settings
    return json_response(
        [run_read(run, settings.data_dir) for run in request.app.state.repository.list_runs()],
        settings,
    )


@router.post(
    "/tasks",
    status_code=202,
    response_model=RunRead,
    responses={409: {"model": ApiError}, 422: {"model": ApiError}},
)
async def start_task(request: Request, body: CreateTaskRequest):
    settings = request.app.state.settings
    scope = Scope(
        categories=body.categories, region=body.region, resource_ids=body.resource_ids
    )
    try:
        run = await request.app.state.manager.start(scope, trigger="manual")
    except BusyError as exc:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE) from exc
    return json_response(run_read(run, settings.data_dir), settings, status_code=202)

@router.post(
    "/translations/backfill",
    status_code=202,
    response_model=RunRead,
    responses={409: {"model": ApiError}},
)
async def backfill_translations(request: Request):
    # Same-origin write guard: the application middleware checks Origin/Host
    # for every non-GET request, exactly as for POST /api/tasks.
    settings = request.app.state.settings
    try:
        run = await request.app.state.manager.backfill_translations()
    except BusyError as exc:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE) from exc
    return json_response(run_read(run, settings.data_dir), settings, status_code=202)


@router.post(
    "/messages/backfill",
    status_code=202,
    response_model=RunRead,
    responses={409: {"model": ApiError}},
)
async def backfill_sources(request: Request):
    settings = request.app.state.settings
    try:
        run = await request.app.state.manager.backfill_sources()
    except BusyError as exc:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE) from exc
    return json_response(run_read(run, settings.data_dir), settings, status_code=202)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetailRead,
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def task_detail(request: Request, task_id: str):
    run = _known_run(request, task_id)
    settings = request.app.state.settings
    return json_response(
        TaskDetailRead(
            run=run_read(run, settings.data_dir),
            changes=request.app.state.repository.get_changes(task_id),
            messages=request.app.state.repository.list_messages(task_id=task_id, include_ended=True),
        ),
        settings,
    )


@router.get("/briefings", response_model=list[RunRead])
async def briefings(request: Request):
    settings = request.app.state.settings
    runs = [run_read(run, settings.data_dir) for run in request.app.state.repository.list_runs()]
    return json_response([run for run in runs if run.has_briefing], settings)


@router.get(
    "/briefings/{task_id}/download",
    response_class=Response,
    response_model=None,
    responses={
        200: {
            "content": {"text/markdown": {"schema": {"type": "string"}}},
            "headers": {"Content-Disposition": {"schema": {"type": "string"}}},
        },
        404: {"model": ApiError},
        422: {"model": ApiError},
    },
)
async def download_briefing(request: Request, task_id: str):
    _known_run(request, task_id)
    settings = request.app.state.settings
    source = briefing_file(settings.data_dir, task_id).read_text(encoding="utf-8")
    return Response(
        redact_text(source, settings),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{task_id}.md"'},
    )


@router.get(
    "/briefings/{task_id}",
    response_model=BriefingRead,
    responses={404: {"model": ApiError}, 422: {"model": ApiError}},
)
async def briefing_detail(request: Request, task_id: str):
    run = _known_run(request, task_id)
    settings = request.app.state.settings
    source = briefing_file(settings.data_dir, task_id).read_text(encoding="utf-8")
    # Redact structured data and Markdown independently, before HTML escaping.
    payload = {
        "run": redact_json(cast(JsonValue, run_read(run, settings.data_dir).model_dump(mode="json")), settings),
        "html": render_markdown(redact_text(source, settings)),
    }
    return JSONResponse(payload)
