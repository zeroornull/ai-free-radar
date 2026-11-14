"""Behavioral acceptance tests for real SQLite task execution and daily scheduling."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pytest
from filelock import FileLock
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from aifreeradar import translation as translation_module
from aifreeradar.config import Settings
from aifreeradar.models import (
    UNKNOWN,
    Category,
    CollectedMessage,
    Evidence,
    FreeType,
    MessageSource,
    Policy,
    ResearchBatch,
    Run,
    RunStats,
    Scope,
)
from aifreeradar.scheduler import Scheduler
from aifreeradar.service import BusyError, TaskManager
from aifreeradar.settings_store import SettingsStore
from aifreeradar.storage import MESSAGE_FACT_FIELDS, Repository

CHECKED = datetime(2026, 11, 1, 1, tzinfo=UTC)
LOCAL = timezone(timedelta(hours=8))


def policy(service="Text API", category="text", **updates):
    values = {
        "provider": "Example Provider",
        "service": service,
        "category": category,
        "provider_domain": "example.com",
        "service_key": service.casefold().replace(" ", "-"),
        "api_url": "https://example.com/api",
        "docs_url": "https://example.com/docs",
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "claim_conditions": "Free registration",
        "payment_required": False,
        "payment_method_required": False,
        "status": "active",
    }
    values.update(updates)
    fields = {
        "api_url",
        "docs_url",
        "free_type",
        "quota",
        "quota_unit",
        "refresh_cycle",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
        "china_policy",
    }
    values.setdefault(
        "evidence",
        [
            Evidence(
                field=field,
                url="https://example.com/policy",
                quote=f"Official {field} policy: {values.get(field, 'unknown')}",
                source_type="official",
                checked_at=CHECKED,
            )
            for field in sorted(fields)
        ],
    )
    return Policy(**values)


class Researcher:
    def __init__(self, *results, blocked=False):
        self.results = list(results) or [ResearchBatch()]
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()
        self.last_stats = RunStats(
            search_calls=3,
            fetch_calls=5,
            model_requests=2,
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=40,
            reasoning_tokens=7,
        )

    async def research(self, scope, existing):
        self.calls.append((scope.model_copy(deep=True), list(existing)))
        self.entered.set()
        await self.release.wait()
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result.model_copy(deep=True)


@pytest.fixture
def runtime(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    return settings, Repository(tmp_path)


def seed(repository, *policies):
    run = Run(scope=Scope(), started_at=CHECKED, status="success", finished_at=CHECKED)
    repository.save_run(run)
    repository.apply_batch(ResearchBatch(resources=list(policies)), run, CHECKED)
    return repository.list_resources()


def clock(day=10, hour=9, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=LOCAL)


def prior_schedule(repository, day="2026-11-01", status: Literal["running", "success", "partial", "failed"] = "success"):
    run = Run(
        trigger="scheduled",
        schedule_day=day,
        status=status,
        started_at=CHECKED,
        finished_at=CHECKED,
    )
    repository.save_run(run)
    return run


@pytest.mark.asyncio
async def test_start_is_nonblocking_persisted_and_same_manager_rejects_overlap(runtime):
    settings, repository = runtime
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.start(Scope(categories=[Category.TEXT]))
        assert repository.get_run(run.id).status == "running"
        assert manager.active is not None and manager.active.id == run.id
        await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        with pytest.raises(BusyError):
            await manager.start(Scope(categories=[Category.IMAGE]))
        assert len(repository.list_runs()) == 1
        assert len(researcher.calls) == 1
        researcher.release.set()
        await manager.wait_idle()
        assert manager.active is None
        assert repository.get_run(run.id).status == "success"
    finally:
        researcher.release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_separate_managers_share_one_writer_lock(runtime):
    settings, repository = runtime
    researcher = Researcher(blocked=True)
    first = TaskManager(settings, repository, researcher)
    second_researcher = Researcher()
    second = TaskManager(settings, Repository(settings.data_dir), second_researcher)
    try:
        await first.start(Scope())
        await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        with pytest.raises(BusyError):
            await second.start(Scope())
        assert len(repository.list_runs()) == 1
        assert second_researcher.calls == []
        researcher.release.set()
        await first.wait_idle()
        accepted = await second.start(Scope())
        await second.wait_idle()
        assert repository.get_run(accepted.id).status == "success"
    finally:
        researcher.release.set()
        await first.close()
        await second.close()


def _hold_research_lock(path, acquired, release):
    with FileLock(path, timeout=5):
        acquired.set()
        release.wait(timeout=15)


@pytest.mark.asyncio
async def test_external_process_filelock_blocks_without_creating_a_run(runtime):
    settings, repository = runtime
    context = multiprocessing.get_context("spawn")
    acquired, release = context.Event(), context.Event()
    process = context.Process(
        target=_hold_research_lock,
        args=(str(settings.data_dir / "research.lock"), acquired, release),
    )
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    process.start()
    try:
        assert acquired.wait(timeout=10), "The independent writer did not acquire its lock"
        with pytest.raises(BusyError):
            await manager.start(Scope())
        assert repository.list_runs() == []
        assert researcher.calls == []
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        await manager.close()
    assert process.exitcode == 0


@pytest.mark.asyncio
async def test_manual_scope_loads_only_scoped_history_without_changing_defaults(runtime):
    settings, repository = runtime
    original_defaults = settings.default_scope.model_dump()
    resources = seed(repository, policy(), policy("Image API", "image"))
    text, image = resources
    researcher = Researcher(ResearchBatch(resources=[policy()]))
    manager = TaskManager(settings, repository, researcher)
    selection = Scope(categories=[Category.TEXT], region="china")
    run = await manager.start(selection)
    selection.categories.append(Category.VIDEO)
    await manager.wait_idle()
    supplied_scope, existing = researcher.calls[0]
    assert supplied_scope == Scope(categories=[Category.TEXT], region="china")
    assert [resource.id for resource in existing] == [text.id]
    assert repository.get_resource(image.id) == image
    assert repository.get_run(run.id).scope == supplied_scope
    assert settings.default_scope.model_dump() == original_defaults
    await manager.close()


@pytest.mark.asyncio
async def test_failure_preserves_confirmed_policy_and_persists_report_after_reopen(runtime):
    settings, repository = runtime
    original = seed(repository, policy())[0]
    manager = TaskManager(settings, repository, Researcher(RuntimeError("provider unavailable")))
    run = await manager.start(Scope(categories=[Category.TEXT], resource_ids=[original.id]))
    await manager.wait_idle()
    reopened = Repository(settings.data_dir)
    failed = reopened.get_run(run.id)
    current = reopened.get_resource(original.id)
    assert failed is not None and current is not None
    assert failed.status == "failed"
    assert failed.finished_at is not None
    assert failed.error is not None and "provider unavailable" in failed.error
    assert current.status == original.status == "active"
    assert current.quota == original.quota
    assert current.evidence == original.evidence
    assert current.last_success_at == original.last_success_at
    assert current.check_status in {"failed", "incomplete"}
    assert current.last_task_id == run.id
    assert current.failure_reason
    assert failed.briefing_path is not None
    report = Path(failed.briefing_path).read_text(encoding="utf-8")
    assert run.id in report and "provider unavailable" in report
    assert original.service in report
    assert reopened.history(original.id) == repository.history(original.id)
    await manager.close()


@pytest.mark.asyncio
async def test_mixed_category_failure_keeps_verified_records_and_partial_status(runtime):
    settings, repository = runtime
    researcher = Researcher(
        ResearchBatch(
            resources=[policy()],
            failures=["Image category source timed out"],
        )
    )
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT, Category.IMAGE]))
    await manager.wait_idle()
    saved = repository.get_run(run.id)
    assert saved is not None
    assert saved.status == "partial"
    assert saved.error is not None and "Image category source timed out" in saved.error
    assert repository.list_resources()[0].status == "active"
    assert repository.get_changes(run.id)[0].kind == "new"
    assert saved.briefing_path is not None
    assert "Image category source timed out" in Path(saved.briefing_path).read_text("utf-8")
    await manager.close()


@pytest.mark.asyncio
async def test_verification_missing_expected_rechecks_marks_partial_and_preserves_outside_scope(runtime):
    settings, repository = runtime
    first, missed, outside = seed(
        repository,
        policy(),
        policy("Other Text API"),
        policy("Image API", "image"),
    )
    manager = TaskManager(
        settings,
        repository,
        Researcher(ResearchBatch(resources=[policy(resource_id=first.id)])),
    )
    run = await manager.start(
        Scope(categories=[Category.TEXT], resource_ids=[first.id, missed.id])
    )
    await manager.wait_idle()
    partial = repository.get_run(run.id)
    checked = repository.get_resource(first.id)
    current = repository.get_resource(missed.id)
    untouched = repository.get_resource(outside.id)
    assert partial is not None and checked is not None and current is not None
    assert partial.status == "partial"
    assert checked.check_status == "success"
    assert current.check_status == "incomplete"
    assert current.status == missed.status == "active"
    assert current.last_success_at == missed.last_success_at
    assert current.last_task_id == run.id and current.failure_reason
    assert untouched == outside
    assert partial.briefing_path is not None
    assert missed.service in Path(partial.briefing_path).read_text("utf-8")
    await manager.close()


@pytest.mark.asyncio
async def test_close_cancels_research_persists_failure_and_releases_writer(runtime):
    settings, repository = runtime
    original = seed(repository, policy())[0]
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope())
    await asyncio.wait_for(researcher.entered.wait(), timeout=3)
    await manager.close()
    persisted = Repository(settings.data_dir).get_run(run.id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.finished_at is not None and persisted.error
    assert persisted.briefing_path is not None
    assert Path(persisted.briefing_path).is_file()
    assert repository.get_resource(original.id).status == "active"
    assert repository.get_resource(original.id).last_success_at == original.last_success_at
    assert manager.active is None
    next_manager = TaskManager(settings, repository, Researcher())
    following = await next_manager.start(Scope())
    await next_manager.wait_idle()
    assert repository.get_run(following.id).status != "running"
    await next_manager.close()


@pytest.mark.asyncio
async def test_same_day_runs_have_unique_briefings_and_survive_reopen(runtime):
    settings, repository = runtime
    manager = TaskManager(settings, repository, Researcher(ResearchBatch(resources=[policy()])))
    first = await manager.start(Scope())
    await manager.wait_idle()
    first_saved = repository.get_run(first.id)
    assert first_saved is not None and first_saved.briefing_path is not None
    first_bytes = Path(first_saved.briefing_path).read_bytes()
    second = await manager.start(Scope())
    await manager.wait_idle()
    reopened = Repository(settings.data_dir)
    second_saved = reopened.get_run(second.id)
    assert second_saved is not None and second_saved.briefing_path is not None
    assert first.id != second.id
    assert first_saved.briefing_path != second_saved.briefing_path
    assert Path(first_saved.briefing_path).read_bytes() == first_bytes
    assert first.id in first_bytes.decode("utf-8")
    second_report = Path(second_saved.briefing_path).read_text("utf-8")
    assert second.id in second_report and "本次无新增或变化" in second_report
    assert len(reopened.list_resources()) == 1
    assert reopened.get_changes(second.id) == []
    assert reopened.list_resources()[0].evidence
    assert reopened.history(reopened.list_resources()[0].id)
    await manager.close()


@pytest.mark.asyncio
async def test_run_stats_persist_and_survive_reopen(runtime):
    settings, repository = runtime
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    started = await manager.start(Scope())
    await manager.wait_idle()
    stored = repository.get_run(started.id)
    assert stored is not None and stored.stats == researcher.last_stats
    reopened = Repository(settings.data_dir)
    again = reopened.get_run(started.id)
    assert again is not None and again.stats == researcher.last_stats
    await manager.close()



@pytest.mark.asyncio
async def test_startup_after_due_catches_up_once_and_same_day_restart_is_idle(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    first_researcher = Researcher()
    manager = TaskManager(settings, repository, first_researcher)
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(hour=10), startup=True)
    await manager.wait_idle()
    run = repository.list_runs()[0]
    assert (run.trigger, run.schedule_day, run.status) == ("catchup", "2026-11-10", "success")
    await scheduler.tick(clock(hour=11), startup=True)
    assert len(first_researcher.calls) == 1
    await manager.close()
    reopened = Repository(settings.data_dir)
    researcher = Researcher()
    restarted_manager = TaskManager(settings, reopened, researcher)
    await Scheduler(settings, restarted_manager, reopened).tick(clock(hour=12), startup=True)
    await restarted_manager.wait_idle()
    assert researcher.calls == []
    assert len(reopened.list_runs()) == 1
    await restarted_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("completed_status", ["success", "partial", "failed"])
async def test_finished_schedule_statuses_do_not_rerun_on_restart(runtime, completed_status):
    settings, repository = runtime
    settings.schedule_enabled = True
    prior_schedule(repository, day="2026-11-10", status=completed_status)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    await Scheduler(settings, manager, repository).tick(clock(hour=10), startup=True)
    await manager.wait_idle()
    assert researcher.calls == []
    assert len(repository.list_runs()) == 1
    await manager.close()


@pytest.mark.asyncio
async def test_fresh_start_before_due_waits_for_normal_local_due_time(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    manager = TaskManager(settings, repository, Researcher())
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(hour=8, minute=59), startup=True)
    assert repository.list_runs() == []
    await scheduler.tick(clock(hour=9))
    await manager.wait_idle()
    run = repository.list_runs()[0]
    assert run.trigger == "scheduled" and run.schedule_day == "2026-11-10"
    await scheduler.tick(clock(hour=15))
    assert len(repository.list_runs()) == 1
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("hour, expected_day", [(8, "2026-11-09"), (10, "2026-11-10")])
async def test_multiple_offline_days_catch_up_only_latest_due_day(runtime, hour, expected_day):
    settings, repository = runtime
    settings.schedule_enabled = True
    prior_schedule(repository)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(hour=hour), startup=True)
    await manager.wait_idle()
    await scheduler.tick(clock(hour=hour), startup=True)
    assert len(researcher.calls) == 1
    new_runs = [run for run in repository.list_runs() if run.schedule_day != "2026-11-01"]
    assert len(new_runs) == 1
    assert new_runs[0].schedule_day == expected_day and new_runs[0].trigger == "catchup"
    await manager.close()


@pytest.mark.asyncio
async def test_manual_busy_defers_schedule_without_consuming_due_day(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    scheduler = Scheduler(settings, manager, repository)
    try:
        manual = await manager.start(Scope(categories=[Category.IMAGE], region="china"))
        await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        await scheduler.tick(clock())
        assert len(repository.list_runs()) == 1
        assert not repository.schedule_completed("2026-11-10")
        researcher.release.set()
        await manager.wait_idle()
        await scheduler.tick(clock(minute=1))
        await manager.wait_idle()
        runs = repository.list_runs()
        assert len(runs) == 2
        scheduled = next(run for run in runs if run.id != manual.id)
        assert scheduled.trigger == "scheduled" and scheduled.schedule_day == "2026-11-10"
        assert scheduled.scope == settings.default_scope
        assert repository.schedule_completed("2026-11-10")
    finally:
        researcher.release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_custom_schedule_and_default_scope_are_used(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    settings.schedule_time = "14:30"
    settings.default_scope = Scope(categories=[Category.IMAGE, Category.SPEECH], region="china")
    defaults = settings.default_scope.model_dump()
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(hour=14, minute=29), startup=True)
    assert repository.list_runs() == []
    await scheduler.tick(clock(hour=14, minute=30))
    await manager.wait_idle()
    assert researcher.calls[0][0] == Scope(categories=[Category.IMAGE, Category.SPEECH], region="china")
    assert repository.list_runs()[0].trigger == "scheduled"
    assert settings.default_scope.model_dump() == defaults
    await manager.close()


@pytest.mark.asyncio
async def test_disabled_schedule_never_runs_even_after_due_or_offline_gap(runtime):
    settings, repository = runtime
    prior_schedule(repository)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher)
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(hour=10), startup=True)
    await scheduler.tick(clock(day=11, hour=12))
    assert researcher.calls == []
    assert len(repository.list_runs()) == 1
    await manager.close()


@pytest.mark.asyncio
async def test_identity_conflict_from_repository_is_partial_and_visible_in_report(runtime):
    settings, repository = runtime
    original = seed(repository, policy())[0]
    conflicting = policy("Different API", resource_id=original.id)
    manager = TaskManager(
        settings,
        repository,
        Researcher(
            ResearchBatch(
                resources=[policy(), conflicting],
            )
        ),
    )
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    assert saved.status == "partial"
    assert conflicting.service in saved.error
    assert conflicting.service in Path(saved.briefing_path).read_text("utf-8")
    assert len(repository.list_resources()) == 1
    assert repository.get_resource(original.id).check_status == "success"
    assert repository.get_resource(original.id).service_key == original.service_key
    await manager.close()


@pytest.mark.asyncio
async def test_ignored_resource_is_never_researched_or_marked_missing(runtime):
    settings, repository = runtime
    kept, ignored, outside = seed(
        repository,
        policy(),
        policy("Ignored API"),
        policy("Image API", "image"),
    )
    repository.apply_review(ignored.id, "ignore")
    researcher = Researcher(ResearchBatch(resources=[policy()]))
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    supplied_scope, supplied = researcher.calls[0]
    assert supplied_scope == Scope(categories=[Category.TEXT])
    assert [resource.id for resource in supplied] == [kept.id]
    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    # The ignored record is absent from expected, so it cannot turn the run partial.
    assert saved.status == "success"
    report = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert ignored.service not in report
    assert repository.get_resource(ignored.id) == ignored
    assert repository.get_resource(kept.id).check_status == "success"
    assert repository.get_resource(outside.id) == outside
    await manager.close()


@pytest.mark.asyncio
async def test_failed_verification_does_not_mark_ignored_resource_incomplete(runtime):
    settings, repository = runtime
    kept, ignored = seed(repository, policy(), policy("Ignored API"))
    repository.apply_review(ignored.id, "ignore")
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT], resource_ids=[kept.id]))
    await asyncio.wait_for(researcher.entered.wait(), timeout=3)
    await manager.close()
    persisted = Repository(settings.data_dir).get_run(run.id)
    assert persisted is not None and persisted.status == "failed"
    reopened = Repository(settings.data_dir)
    assert reopened.get_resource(ignored.id) == ignored
    kept_after = reopened.get_resource(kept.id)
    assert kept_after is not None and kept_after.check_status == "incomplete"


@pytest.mark.asyncio
async def test_scheduled_run_honors_ignored_resources(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    kept, ignored = seed(repository, policy(), policy("Ignored API"))
    repository.apply_review(ignored.id, "ignore")
    researcher = Researcher(ResearchBatch(resources=[policy()]))
    manager = TaskManager(settings, repository, researcher)
    scheduler = Scheduler(settings, manager, repository)
    await scheduler.tick(clock(), startup=True)
    await manager.wait_idle()
    scheduled = next(run for run in repository.list_runs() if run.trigger == "catchup")
    assert scheduled.status == "success"
    assert [resource.id for resource in researcher.calls[0][1]] == [kept.id]
    assert scheduled.briefing_path is not None
    report = Path(scheduled.briefing_path).read_text(encoding="utf-8")
    assert ignored.service not in report
    assert repository.get_resource(ignored.id) == ignored
    await manager.close()


@pytest.mark.asyncio
async def test_ignored_resource_does_not_mask_missing_peer_or_scope_isolation(runtime):
    settings, repository = runtime
    kept, ignored, outside = seed(
        repository,
        policy(),
        policy("Ignored API"),
        policy("Image API", "image"),
    )
    repository.apply_review(ignored.id, "ignore")
    manager = TaskManager(settings, repository, Researcher(ResearchBatch()))
    run = await manager.start(Scope(categories=[Category.TEXT], resource_ids=[kept.id]))
    await manager.wait_idle()
    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    assert saved.status == "partial"
    assert repository.get_resource(kept.id).check_status == "incomplete"
    assert repository.get_resource(ignored.id) == ignored
    assert repository.get_resource(outside.id) == outside
    report = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert ignored.service not in report
    assert kept.service in report
    await manager.close()


@pytest.mark.asyncio
async def test_collection_run_never_marks_unreturned_history_incomplete(runtime):
    settings, repository = runtime
    kept, other = seed(repository, policy(), policy("Other Text API"))
    manager = TaskManager(settings, repository, Researcher(ResearchBatch()))
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    assert saved.status == "success"
    assert repository.get_resource(kept.id) == kept
    assert repository.get_resource(other.id) == other
    report = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "本次无新增或变化" in report
    assert "待核实线索" not in report
    await manager.close()


@pytest.mark.asyncio
async def test_collection_failure_is_partial_without_touching_history(runtime):
    settings, repository = runtime
    (original,) = seed(repository, policy())
    manager = TaskManager(
        settings,
        repository,
        Researcher(ResearchBatch(failures=["搜索服务超时"])),
    )
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    assert saved.status == "partial"
    assert "搜索服务超时" in saved.error
    assert repository.get_resource(original.id) == original
    report = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "搜索服务超时" in report
    await manager.close()


def store_for(settings, repository, document=None):
    document = document if document is not None else {
        "schedule_enabled": settings.schedule_enabled,
        "schedule_time": settings.schedule_time,
    }
    return SettingsStore(repository, settings, document)


@pytest.mark.asyncio
async def test_scheduled_time_runs_once_per_day_from_store(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    settings.schedule_time = "07:30"
    store = store_for(settings, repository)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher, settings_store=store)
    scheduler = Scheduler(settings, manager, repository, settings_store=store)

    await scheduler.tick(clock(hour=7, minute=29), startup=True)
    assert repository.list_runs() == []
    await scheduler.tick(clock(hour=7, minute=30))
    await manager.wait_idle()
    runs = repository.list_runs()
    assert len(runs) == 1
    assert runs[0].trigger == "scheduled" and runs[0].schedule_day == "2026-11-10"

    await scheduler.tick(clock(hour=7, minute=45))
    await scheduler.tick(clock(hour=20))
    await manager.wait_idle()
    assert len(repository.list_runs()) == 1
    assert len(researcher.calls) == 1
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("previous_time", "new_time"), [("09:00", "08:00"), ("08:00", "09:00")]
)
async def test_rescheduled_past_time_does_not_run_today_but_runs_next_day(
    runtime, previous_time, new_time
):
    settings, repository = runtime
    settings.schedule_enabled = True
    settings.schedule_time = previous_time
    store = store_for(settings, repository)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher, settings_store=store)
    scheduler = Scheduler(settings, manager, repository, settings_store=store)

    await scheduler.tick(clock(hour=7), startup=True)
    assert researcher.calls == []

    previous = store.effective()
    store.update({"schedule_time": new_time}, {}, store.version)
    scheduler.on_settings_changed(previous, store.effective(), now=clock(hour=10))

    # The new time already passed at the edit instant, so it is not caught up today.
    await scheduler.tick(clock(hour=10, minute=1))
    await manager.wait_idle()
    assert researcher.calls == []
    assert repository.list_runs() == []

    hour, minute = (int(part) for part in new_time.split(":"))
    await scheduler.tick(clock(day=11, hour=hour, minute=minute + 1))
    await manager.wait_idle()
    runs = repository.list_runs()
    assert len(runs) == 1
    assert runs[0].trigger == "scheduled" and runs[0].schedule_day == "2026-11-11"
    await manager.close()


@pytest.mark.asyncio
async def test_model_only_settings_change_keeps_pending_due_run(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    settings.schedule_time = "09:00"
    store = store_for(settings, repository)
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher, settings_store=store)
    scheduler = Scheduler(settings, manager, repository, settings_store=store)
    try:
        manual = await manager.start(Scope(categories=[Category.TEXT]))
        await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        await scheduler.tick(clock(hour=9, minute=5))
        assert not repository.schedule_completed("2026-11-10")

        previous = store.effective()
        store.update({"model": "openai:gpt-4.1"}, {}, store.version)
        scheduler.on_settings_changed(previous, store.effective(), now=clock(hour=9, minute=6))

        researcher.release.set()
        await manager.wait_idle()
        await scheduler.tick(clock(hour=9, minute=7))
        await manager.wait_idle()
        runs = repository.list_runs()
        assert len(runs) == 2
        scheduled = next(run for run in runs if run.id != manual.id)
        assert scheduled.trigger == "scheduled" and scheduled.schedule_day == "2026-11-10"
        assert repository.schedule_completed("2026-11-10")
    finally:
        researcher.release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_in_flight_task_keeps_its_settings_snapshot(runtime, monkeypatch):
    settings, repository = runtime
    secret = "sk-snapshot-secret-never-returned"
    monkeypatch.setenv("AIFREE_TEST_MODEL_KEY", secret)
    settings.model_api_key_env = "AIFREE_TEST_MODEL_KEY"
    store = store_for(settings, repository, {"model_api_key_env": "AIFREE_TEST_MODEL_KEY"})
    researcher = Researcher(RuntimeError(f"model rejected {secret}"), blocked=True)
    manager = TaskManager(settings, repository, researcher, settings_store=store)

    run = await manager.start(Scope(categories=[Category.TEXT]))
    await asyncio.wait_for(researcher.entered.wait(), timeout=3)

    # The settings store moves on while the task is running.
    store.update({"model_api_key_env": "AIFREE_TEST_SPARE_KEY"}, {}, store.version)
    monkeypatch.setenv("AIFREE_TEST_SPARE_KEY", "sk-spare-secret")
    researcher.release.set()
    await manager.wait_idle()

    failed = repository.get_run(run.id)
    assert failed is not None and failed.status == "failed"
    assert "[已隐藏凭据]" in failed.error
    assert secret not in failed.error
    await manager.close()

    # A run started after the edit redacts only the environment named by its own snapshot.
    later = Researcher(RuntimeError(f"model rejected {secret}"))
    later_manager = TaskManager(store.effective(), repository, later, settings_store=store)
    later_run = await later_manager.start(Scope(categories=[Category.TEXT]))
    await later_manager.wait_idle()
    persisted = repository.get_run(later_run.id)
    assert persisted is not None and persisted.status == "failed"
    assert secret in persisted.error
    assert "[已隐藏凭据]" not in persisted.error
    await later_manager.close()


@pytest.mark.asyncio
async def test_disabled_schedule_from_store_prevents_due_runs(runtime):
    settings, repository = runtime
    settings.schedule_enabled = True
    settings.schedule_time = "09:00"
    store = store_for(settings, repository)
    researcher = Researcher()
    manager = TaskManager(settings, repository, researcher, settings_store=store)
    scheduler = Scheduler(settings, manager, repository, settings_store=store)

    previous = store.effective()
    store.update({"schedule_enabled": False}, {}, store.version)
    scheduler.on_settings_changed(previous, store.effective(), now=clock(hour=8))

    await scheduler.tick(clock(hour=9, minute=30), startup=True)
    await scheduler.tick(clock(hour=12))
    await scheduler.tick(clock(day=11, hour=12), startup=True)
    await manager.wait_idle()
    assert researcher.calls == []
    assert repository.list_runs() == []
    await manager.close()


# --- Additive zh translation (contract: originals stay authoritative) ---

REAL_MODEL_TRANSLATOR = translation_module.ModelTranslator


def english_message(service="Free Text API", **updates):
    values = {
        "policy": policy(
            service,
            free_type="ongoing",
            quota="1000 requests per month",
            quota_unit="requests",
            refresh_cycle="monthly",
            rate_limit="10 requests per minute",
            claim_conditions="Free registration and no purchase required",
            expiry_notes="No fixed end date",
            region_restrictions="Available worldwide",
            status="pending",
        ),
        "title": f"{service} free tier announced",
        "summary": "Free API tier with 1000 monthly requests and no purchase required.",
        "sources": [
            MessageSource(
                url="https://example.com/free-api",
                title=f"{service} official page",
                excerpt="Free tier with 1000 requests per month.",
                source_type="official",
                access="page",
            )
        ],
    }
    values.update(updates)
    return CollectedMessage(**values)


def english_failure_lead():
    """A pending lead whose only unresolved detail is the English failure reason."""
    return policy(
        "Free Text API",
        status="pending",
        quota=UNKNOWN,
        failure_reason="Official documentation does not state the free quota",
    )


def translation_answer(value: str) -> str:
    return f"中文机器译文：{value}"


def translation_model(calls, *, fail=False):
    """Deterministic injected model: records prompts and answers fixed zh."""

    def respond(messages, info):
        text = "\n".join(
            str(getattr(part, "content", part))
            for message in messages
            for part in getattr(message, "parts", ())
        )
        calls.append(text)
        if fail:
            raise RuntimeError("translation model unavailable")
        payload = json.loads(text.strip().splitlines()[-1])
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "translations": {
                            key: translation_answer(value) for key, value in payload.items()
                        }
                    },
                )
            ]
        )

    return FunctionModel(respond)


def install_model_translator(monkeypatch, model):
    """Route the service's ModelTranslator through a deterministic injected model."""
    monkeypatch.setattr(
        translation_module,
        "ModelTranslator",
        lambda settings: REAL_MODEL_TRANSLATOR(settings, model=model),
    )


@pytest.mark.asyncio
async def test_collection_translates_messages_and_lead_failure_reason(runtime, monkeypatch):
    settings, repository = runtime
    calls: list[str] = []
    install_model_translator(monkeypatch, translation_model(calls))
    seed(repository, english_failure_lead())
    researcher = Researcher(ResearchBatch(messages=[english_message()]))
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.start(Scope(categories=[Category.TEXT]))
        await manager.wait_idle()
    finally:
        await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None
    assert saved.status == "success"
    assert saved.error == ""
    (event,) = repository.list_messages(task_id=run.id, include_ended=True)
    assert event.title == "Free Text API free tier announced"
    assert event.title_zh == translation_answer(event.title)
    assert event.summary_zh == translation_answer(event.summary)
    assert event.policy.quota == "1000 requests per month"
    assert event.policy.quota_zh == translation_answer(event.policy.quota)
    assert event.policy.claim_conditions_zh == translation_answer(event.policy.claim_conditions)
    assert event.sources[0].excerpt == "Free tier with 1000 requests per month."
    resource = repository.get_resource(event.resource_id)
    assert resource is not None
    (offer,) = resource.messages
    assert (offer.title_zh, offer.summary_zh) == (event.title_zh, event.summary_zh)
    assert resource.failure_reason.startswith("Official documentation does not state the free quota")
    assert resource.failure_reason_zh == translation_answer(resource.failure_reason)
    assert calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["model_error", "translator_error"])
async def test_collection_succeeds_when_translation_fails(runtime, monkeypatch, mode):
    settings, repository = runtime

    class ExplodingTranslator:
        async def translate(self, texts):
            raise RuntimeError("translation backend down")

    if mode == "model_error":
        install_model_translator(monkeypatch, translation_model([], fail=True))
    else:
        monkeypatch.setattr(
            translation_module, "ModelTranslator", lambda settings: ExplodingTranslator()
        )
    seed(repository, english_failure_lead())
    researcher = Researcher(ResearchBatch(messages=[english_message()]))
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.start(Scope(categories=[Category.TEXT]))
        await manager.wait_idle()
    finally:
        await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None
    assert saved.status == "success"
    (event,) = repository.list_messages(task_id=run.id, include_ended=True)
    assert event.title == "Free Text API free tier announced"
    assert (event.title_zh, event.summary_zh, event.end_reason_zh) == ("", "", "")
    assert event.policy.quota_zh == event.policy.claim_conditions_zh == ""
    resource = repository.get_resource(event.resource_id)
    assert resource is not None
    assert resource.failure_reason.startswith("Official documentation does not state the free quota")
    assert resource.failure_reason_zh == ""
    (offer,) = resource.messages
    assert (offer.title_zh, offer.summary_zh) == ("", "")
    if mode == "translator_error":
        assert any("机器翻译未完成，保留原文" in note for note in saved.notes)
    else:
        assert not any("机器翻译未完成" in note for note in saved.notes)


@pytest.mark.asyncio
async def test_backfill_translates_stored_records_idempotently(runtime, monkeypatch):
    settings, repository = runtime
    calls: list[str] = []
    install_model_translator(monkeypatch, translation_model(calls))
    seed(repository, english_failure_lead())
    collected = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED,
        status="success",
        finished_at=CHECKED,
    )
    repository.save_run(collected)
    (event,) = repository.apply_messages(
        ResearchBatch(messages=[english_message()]), collected, CHECKED
    )

    manager = TaskManager(settings, repository, Researcher())
    try:
        first = await manager.backfill_translations()
        assert isinstance(first, Run)
        assert first.trigger == "manual" and first.status == "running"
        await manager.wait_idle()
        saved = repository.get_run(first.id)
        assert saved is not None
        assert saved.status == "success"
        assert saved.finished_at is not None
        assert saved.notes and "译文回填完成" in saved.notes[0]

        (stored,) = repository.list_messages(include_ended=True)
        assert stored.id == event.id
        assert stored.title_zh == translation_answer(stored.title)
        assert stored.summary_zh == translation_answer(stored.summary)
        resource = repository.get_resource(event.resource_id)
        assert resource is not None
        (offer,) = resource.messages
        assert offer.title_zh == stored.title_zh
        assert offer.summary_zh == stored.summary_zh
        assert resource.failure_reason.startswith(
            "Official documentation does not state the free quota"
        )
        assert resource.failure_reason_zh == translation_answer(resource.failure_reason)

        first_calls = len(calls)
        assert first_calls

        second = await manager.backfill_translations()
        assert second.trigger == "manual"
        await manager.wait_idle()
        replay = repository.get_run(second.id)
        assert replay is not None and replay.status == "success"
        assert replay.notes and replay.notes[0].startswith("译文回填完成")
        assert len(calls) == first_calls, "unchanged originals must never be re-translated"
        again = repository.get_resource(event.resource_id)
        assert again is not None
        (again_offer,) = again.messages
        assert again_offer.title_zh == offer.title_zh
        assert again_offer.summary_zh == offer.summary_zh
        assert again.failure_reason_zh == resource.failure_reason_zh
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_backfill_translations_rejects_active_research(runtime, monkeypatch):
    settings, repository = runtime
    calls: list[str] = []
    install_model_translator(monkeypatch, translation_model(calls))
    researcher = Researcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    try:
        await manager.start(Scope(categories=[Category.TEXT]))
        await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        with pytest.raises(BusyError):
            await manager.backfill_translations()
        assert len(repository.list_runs()) == 1
        assert calls == []
        researcher.release.set()
        await manager.wait_idle()
        backfill = await manager.backfill_translations()
        await manager.wait_idle()
        saved = repository.get_run(backfill.id)
        assert saved is not None and saved.status == "success"
    finally:
        researcher.release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_backfill_translations_rejects_a_second_backfill(runtime, monkeypatch):
    settings, repository = runtime
    collected = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED,
        status="success",
        finished_at=CHECKED,
    )
    repository.save_run(collected)
    repository.apply_messages(ResearchBatch(messages=[english_message()]), collected, CHECKED)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(messages, info):
        entered.set()
        await release.wait()
        return ModelResponse([ToolCallPart(info.output_tools[0].name, {"translations": {}})])

    install_model_translator(monkeypatch, FunctionModel(respond))
    manager = TaskManager(settings, repository, Researcher())
    try:
        first = await manager.backfill_translations()
        await asyncio.wait_for(entered.wait(), timeout=3)
        with pytest.raises(BusyError):
            await manager.backfill_translations()
        release.set()
        await manager.wait_idle()
        saved = repository.get_run(first.id)
        assert saved is not None and saved.status == "success"
    finally:
        release.set()
        await manager.close()


def test_zh_fields_never_enter_message_change_detection(runtime):
    _settings, repository = runtime
    assert MESSAGE_FACT_FIELDS == (
        "access_mode",
        "free_type",
        "quota",
        "quota_unit",
        "refresh_cycle",
        "rate_limit",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
        "expires_at",
        "expiry_notes",
        "region_restrictions",
        "china_policy",
        "models",
    )
    assert not any(name.endswith("_zh") for name in MESSAGE_FACT_FIELDS)

    message = english_message()
    first_run = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED,
        status="success",
        finished_at=CHECKED,
    )
    repository.save_run(first_run)
    (first,) = repository.apply_messages(ResearchBatch(messages=[message]), first_run, CHECKED)
    assert first.kind == "new"
    repository.save_news_translations(
        [first.model_copy(update={"title_zh": "免费层级发布", "summary_zh": "每月一千次免费请求"})]
    )

    translated = message.model_copy(
        update={
            "title_zh": "免费层级发布",
            "summary_zh": "每月一千次免费请求",
            "policy": message.policy.model_copy(update={"quota_zh": "每月一千次请求"}),
        }
    )
    second_run = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED + timedelta(days=1),
        status="success",
        finished_at=CHECKED + timedelta(days=1),
    )
    repository.save_run(second_run)
    assert (
        repository.apply_messages(
            ResearchBatch(messages=[translated]), second_run, CHECKED + timedelta(days=1)
        )
        == []
    )
    (unchanged,) = repository.list_messages(include_ended=True)
    assert unchanged.kind == "new"
    assert unchanged.title_zh == "免费层级发布"

    changed = translated.model_copy(
        update={"policy": translated.policy.model_copy(update={"quota": "2000 requests per month"})}
    )
    third_run = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED + timedelta(days=2),
        status="success",
        finished_at=CHECKED + timedelta(days=2),
    )
    repository.save_run(third_run)
    (event,) = repository.apply_messages(
        ResearchBatch(messages=[changed]), third_run, CHECKED + timedelta(days=2)
    )
    assert event.kind == "changed"
    assert event.policy.quota == "2000 requests per month"
    assert event.policy.quota_zh == "每月一千次请求"


class SourceResearcher(Researcher):
    async def collect_sources(self, resources):
        return await self.research(Scope(), resources)


@pytest.mark.asyncio
async def test_source_backfill_recovers_local_first_and_targets_only_remaining_missing(runtime, monkeypatch):
    settings, repository = runtime
    calls: list[str] = []
    install_model_translator(monkeypatch, translation_model(calls))
    original = {
        resource.service: resource for resource in seed(
            repository,
            policy("Local API"),
            policy("Missing API", status="pending", evidence=[]),
            policy("Ignored API", status="pending", evidence=[]),
        )
    }
    repository.apply_review(original["Ignored API"].id, "ignore")
    collected = Run(
        scope=Scope(categories=[Category.TEXT]),
        started_at=CHECKED,
        status="success",
        finished_at=CHECKED,
    )
    repository.save_run(collected)
    repository.apply_messages(
        ResearchBatch(messages=[english_message("Local API")]), collected, CHECKED
    )
    local_after_seed = repository.get_resource(original["Local API"].id)
    missing = original["Missing API"]
    message = english_message("Missing API")
    message.policy.resource_id = missing.id
    message.policy.free_type = FreeType.UNKNOWN
    message.policy.api_url = UNKNOWN
    message.policy.quota = UNKNOWN
    message.policy.payment_required = None
    message.policy.payment_method_required = None
    researcher = SourceResearcher(ResearchBatch(messages=[message]))
    real_recover = repository.recover_legacy_messages
    order: list[str] = []
    real_collect = researcher.collect_sources

    async def collect(resources):
        order.append("collect")
        return await real_collect(resources)

    researcher.collect_sources = collect
    monkeypatch.setattr(
        repository, "recover_legacy_messages",
        lambda: order.append("recover") or real_recover(),
    )
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.backfill_sources()
        assert run.scope.resource_ids == []
        await manager.wait_idle()
        saved = repository.get_run(run.id)
        assert saved is not None and saved.status == "success" and not saved.error
        assert saved.stats == researcher.last_stats
        (supplied,) = researcher.calls[0][1]
        assert supplied.id == missing.id and supplied.category == missing.category
        assert order == ["recover", "collect"]
        assert repository.get_resource(original["Local API"].id) == local_after_seed
        restored = repository.get_resource(missing.id)
        assert restored is not None and restored.messages[0].sources
        assert restored.first_seen_at == missing.first_seen_at
        assert restored.status == missing.status
        assert restored.last_success_at == missing.last_success_at
        assert repository.get_resource(original["Ignored API"].id) == original["Ignored API"]
        (event,) = repository.list_messages(task_id=run.id, include_ended=True)
        assert event.discovered_at == missing.first_seen_at
        assert event.title_zh

        again = await manager.backfill_sources()
        await manager.wait_idle()
        repeated = repository.get_run(again.id)
        assert repeated is not None and repeated.status == "success"
        assert repeated.stats == RunStats()
        assert len(researcher.calls) == 1
        assert repository.list_messages(task_id=again.id, include_ended=True) == []
    finally:
        await manager.close()
@pytest.mark.asyncio
async def test_source_backfill_without_recoverable_sources_preserves_lead_without_failure(runtime):
    settings, repository = runtime
    (original,) = seed(repository, policy("Unknown API", evidence=[], status="pending"))
    researcher = SourceResearcher(ResearchBatch(notes=["No matching source report was observed"]))
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.backfill_sources()
        await manager.wait_idle()
        saved = repository.get_run(run.id)
        assert saved is not None and saved.status == "success" and not saved.error
        assert saved.stats == researcher.last_stats and saved.notes
        assert repository.get_resource(original.id) == original
        assert repository.list_messages(include_ended=True) == []
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_before_start", [False, True])
async def test_source_backfill_cancellation_releases_shared_lock_without_policy_recheck(runtime, cancel_before_start):
    settings, repository = runtime
    (original,) = seed(repository, policy("Unknown API", evidence=[], status="pending"))
    researcher = SourceResearcher(blocked=True)
    manager = TaskManager(settings, repository, researcher)
    other = TaskManager(settings, repository, SourceResearcher())
    try:
        run = await manager.backfill_sources()
        if not cancel_before_start:
            await asyncio.wait_for(researcher.entered.wait(), timeout=3)
        with pytest.raises(BusyError):
            await manager.start(Scope())
        with pytest.raises(BusyError):
            await manager.backfill_translations()
        with pytest.raises(BusyError):
            await manager.backfill_sources()
        with pytest.raises(BusyError):
            await other.backfill_sources()
        await manager.close()
        saved = repository.get_run(run.id)
        assert saved is not None and saved.status == "failed" and saved.finished_at is not None
        assert repository.get_resource(original.id) == original
        following = await other.backfill_sources()
        await other.wait_idle()
        assert repository.get_run(following.id).status == "success"
    finally:
        await manager.close()
        await other.close()


@pytest.mark.asyncio
async def test_source_backfill_recreates_production_researcher_with_each_settings_snapshot(runtime, monkeypatch):
    settings, repository = runtime
    seed(repository, policy("Unknown API", evidence=[], status="pending"))
    store = store_for(settings, repository)
    instances = []

    constructed = asyncio.Event()
    class SnapshotResearcher(SourceResearcher):
        def __init__(self, snapshot):
            super().__init__(blocked=not instances)
            self.snapshot = snapshot
            instances.append(self)
            constructed.set()

    monkeypatch.setattr("aifreeradar.research.HarnessResearcher", SnapshotResearcher)
    manager = TaskManager(settings, repository, settings_store=store)
    try:
        first = await manager.backfill_sources()
        # Let production construction enter its blocked source request.
        await asyncio.wait_for(constructed.wait(), timeout=3)
        await asyncio.wait_for(instances[0].entered.wait(), timeout=3)
        before = instances[0].snapshot.model
        store.update({"model": "openai:new-model"}, {}, store.version)
        assert instances[0].snapshot.model == before
        instances[0].release.set()
        await manager.wait_idle()
        assert repository.get_run(first.id).status == "success"
        second = await manager.backfill_sources()
        await manager.wait_idle()
        assert repository.get_run(second.id).status == "success"
        assert len(instances) == 2 and instances[1].snapshot.model == "openai:new-model"
    finally:
        await manager.close()
