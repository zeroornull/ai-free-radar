"""Local daily scheduling with one latest missed run and a durable run ledger."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .service import BusyError

if TYPE_CHECKING:
    from .config import Settings
    from .service import TaskManager
    from .settings_store import SettingsStore
    from .storage import Repository


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        manager: TaskManager,
        repository: Repository,
        *,
        settings_store: SettingsStore | None = None,
    ) -> None:
        self.settings = settings
        self.manager = manager
        self.repository = repository
        self._settings_store = settings_store
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self._pending: tuple[str, str] | None = None
        self._schedule_epoch: datetime | None = None

    async def tick(self, now: datetime | None = None, startup: bool = False) -> None:
        """Attempt the latest due day; a busy writer defers rather than consumes it."""
        settings = (
            self._settings_store.effective()
            if self._settings_store is not None
            else self.settings
        )
        if not settings.schedule_enabled:
            return
        local_now = now if now is not None else datetime.now().astimezone()
        if local_now.tzinfo is None or local_now.utcoffset() is None:
            raise ValueError("定时调度需要带时区的本地时间")
        async with self._tick_lock:
            hour, minute = (int(part) for part in settings.schedule_time.split(":"))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("定时时刻必须为有效的 HH:MM")
            today = local_now.date()
            due_at = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            due: tuple[str, str] | None = None
            if (local_now.hour, local_now.minute) >= (hour, minute):
                # A rescheduled time is not caught up retroactively on the same day:
                # only instants strictly after the edit may start a run.
                if startup or self._schedule_epoch is None or due_at > self._schedule_epoch:
                    due = (today.isoformat(), "catchup" if startup else "scheduled")
            elif startup:
                # An existing schedule ledger distinguishes an offline gap from a
                # fresh install. Never invent yesterday's run for a new data dir.
                latest = self.repository.latest_schedule_day()
                yesterday = (today - timedelta(days=1)).isoformat()
                if latest is not None and latest < yesterday:
                    due = (yesterday, "catchup")
            if due is not None and (self._pending is None or due[0] > self._pending[0]):
                self._pending = due
            if self._pending is None:
                return
            day, trigger = self._pending
            if self.repository.schedule_completed(day):
                self._pending = None
                return
            try:
                await self.manager.start(
                    settings.default_scope.model_copy(deep=True),
                    trigger=trigger,
                    schedule_day=day,
                )
            except BusyError:
                # Manual tasks and other processes must not erase a due task.
                return
            self._pending = None

    def on_settings_changed(
        self,
        previous: Settings,
        current: Settings,
        now: datetime | None = None,
    ) -> None:
        """Start a new schedule epoch so an edited time is not caught up today."""
        if (
            previous.schedule_enabled != current.schedule_enabled
            or previous.schedule_time != current.schedule_time
        ):
            self._schedule_epoch = now if now is not None else datetime.now().astimezone()
            self._pending = None
        self._wake.set()

    async def run(self) -> None:
        if self._stop.is_set():
            return
        await self.tick(startup=True)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except TimeoutError:
                await self.tick()
                continue
            self._wake.clear()
            if self._stop.is_set():
                return
            await self.tick()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
