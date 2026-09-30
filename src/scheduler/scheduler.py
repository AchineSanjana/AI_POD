"""Shared scheduling engine for background recurring jobs.

Provides a unified scheduling mechanism shared across:
- Step 20: Catalog feed sync (e.g., polling e-commerce feeds every few hours).
- Step 21: Model retraining triggers (e.g., periodic retraining runs).

Can run as:
1. In-process daemon background thread inside the FastAPI application.
2. Standalone script / cron task with single-pass (--once) or continuous execution.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any

from src.catalog.feed_sync import sync_all_tenant_catalogs

logger = logging.getLogger(__name__)

# Default intervals
DEFAULT_CATALOG_SYNC_INTERVAL_HOURS = 4.0
DEFAULT_CATALOG_SYNC_INTERVAL_SECONDS = DEFAULT_CATALOG_SYNC_INTERVAL_HOURS * 3600.0


class ScheduledJob:
    """Encapsulates a recurring task with an execution interval and state."""

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        interval_seconds: float,
        kwargs: dict[str, Any] | None = None,
        run_immediately: bool = True,
    ) -> None:
        self.name = name
        self.fn = fn
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.kwargs = kwargs or {}
        self.last_run: datetime | None = None
        self.last_status: str | None = None
        self.last_error: str | None = None
        self.run_count: int = 0
        # If run_immediately is False, wait until first interval elapses
        self.next_run_time: float = (
            time.monotonic() if run_immediately else (time.monotonic() + self.interval_seconds)
        )

    def is_due(self) -> bool:
        """Return True if job's scheduled interval has elapsed."""
        return time.monotonic() >= self.next_run_time

    def execute(self) -> Any:
        """Run the job function once, record metrics, and compute next run time."""
        logger.info("Executing scheduled job '%s'...", self.name)
        start_ts = datetime.now(timezone.utc)
        self.last_run = start_ts
        try:
            result = self.fn(**self.kwargs)
            self.last_status = "success"
            self.last_error = None
            self.run_count += 1
            logger.info("Scheduled job '%s' completed successfully.", self.name)
            return result
        except Exception as exc:
            self.last_status = "error"
            self.last_error = str(exc)
            logger.exception("Scheduled job '%s' failed: %s", self.name, exc)
            return None
        finally:
            self.next_run_time = time.monotonic() + self.interval_seconds


class BackgroundScheduler:
    """Manages recurring scheduled background tasks in a daemon thread."""

    def __init__(self, check_interval_seconds: float = 10.0) -> None:
        self.check_interval_seconds = check_interval_seconds
        self.jobs: dict[str, ScheduledJob] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def register_job(
        self,
        name: str,
        fn: Callable[..., Any],
        interval_seconds: float,
        kwargs: dict[str, Any] | None = None,
        run_immediately: bool = True,
    ) -> ScheduledJob:
        """Register a new recurring task."""
        with self._lock:
            job = ScheduledJob(
                name=name,
                fn=fn,
                interval_seconds=interval_seconds,
                kwargs=kwargs,
                run_immediately=run_immediately,
            )
            self.jobs[name] = job
            logger.info(
                "Registered scheduled job '%s' with interval %.1fs",
                name,
                job.interval_seconds,
            )
            return job

    def unregister_job(self, name: str) -> bool:
        """Remove a scheduled job by name."""
        with self._lock:
            if name in self.jobs:
                del self.jobs[name]
                logger.info("Unregistered scheduled job '%s'", name)
                return True
            return False

    def run_job_now(self, name: str) -> Any:
        """Trigger a specific registered job immediately."""
        with self._lock:
            job = self.jobs.get(name)
        if not job:
            raise KeyError(f"Scheduled job '{name}' not found")
        return job.execute()

    def run_all_due_jobs(self) -> dict[str, Any]:
        """Check all registered jobs and run those that are due."""
        results = {}
        with self._lock:
            jobs_to_run = [job for job in self.jobs.values() if job.is_due()]

        for job in jobs_to_run:
            results[job.name] = job.execute()

        return results

    def run_all_jobs_once(self) -> dict[str, Any]:
        """Force execution of every registered job once (useful for CLI/cron)."""
        results = {}
        with self._lock:
            all_jobs = list(self.jobs.values())

        for job in all_jobs:
            results[job.name] = job.execute()

        return results

    def _scheduler_loop(self) -> None:
        """Daemon worker loop checking pending jobs periodically."""
        logger.info("BackgroundScheduler started (check_interval=%.1fs)", self.check_interval_seconds)
        while not self._stop_event.is_set():
            try:
                self.run_all_due_jobs()
            except Exception as exc:
                logger.exception("Error in scheduler loop: %s", exc)

            self._stop_event.wait(self.check_interval_seconds)

        logger.info("BackgroundScheduler stopped gracefully.")

    def start(self) -> BackgroundScheduler:
        """Start the background scheduler thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("BackgroundScheduler is already running.")
            return self

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            name="app-background-scheduler",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background scheduler thread."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        """Return True if background scheduler thread is running."""
        return self._thread is not None and self._thread.is_alive()


# Global scheduler singleton
_GLOBAL_SCHEDULER: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Retrieve or create the global BackgroundScheduler instance."""
    global _GLOBAL_SCHEDULER
    if _GLOBAL_SCHEDULER is None:
        _GLOBAL_SCHEDULER = BackgroundScheduler()
        # Automatically register catalog feed sync job
        _GLOBAL_SCHEDULER.register_job(
            name="catalog_feed_sync",
            fn=sync_all_tenant_catalogs,
            interval_seconds=DEFAULT_CATALOG_SYNC_INTERVAL_SECONDS,
            run_immediately=False,
        )
    return _GLOBAL_SCHEDULER


def start_background_scheduler() -> BackgroundScheduler:
    """Start and return the global BackgroundScheduler instance."""
    scheduler = get_scheduler()
    scheduler.start()
    return scheduler


def stop_background_scheduler(timeout: float = 5.0) -> None:
    """Stop the global BackgroundScheduler instance."""
    global _GLOBAL_SCHEDULER
    if _GLOBAL_SCHEDULER is not None:
        _GLOBAL_SCHEDULER.stop(timeout=timeout)
        _GLOBAL_SCHEDULER = None
