"""Data Process 任务队列管理器。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import datetime
from pathlib import Path

from paper_plane_x_backend.models import DataProcessTaskStatus, SortOrder, TaskSortKey
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessQueueTask,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.stores import (
    DataProcessTaskStateStore,
    TaskStateStoreView,
)
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.paper.parser import PaperParser
from paper_plane_x_backend.services.paper.processor import (
    PaperProcessor,
    PaperProcessorError,
    PaperProcessResult,
)
from paper_plane_x_backend.services.paper.repository import PaperRepository
from paper_plane_x_backend.services.pdf_parser.factory import build_default_pdf_parser

logger = logging.getLogger(__name__)


class DataProcessTaskManager:
    """管理 data-process 后台任务。"""

    def __init__(
        self,
        worker_count: int = 1,
        state_store: DataProcessTaskStateStore | None = None,
        shutdown_timeout: float = 5.0,
        task_max_seconds: float = 600.0,
        on_status_change: (
            Callable[[DataProcessTaskState], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self.worker_count = max(1, worker_count)
        self._queue: asyncio.Queue[DataProcessQueueTask | None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        if state_store is None:
            db = get_db()
            db.init_tables()
            self._state_store = DataProcessTaskStateStore(db)
        else:
            self._state_store = state_store
        self._running_jobs: dict[str, asyncio.Task[object]] = {}
        self._cancel_requests: set[str] = set()
        self._shutdown_timeout = max(0.1, shutdown_timeout)
        self._task_max_seconds = max(0.1, task_max_seconds)
        self._task_states_view = TaskStateStoreView(self._state_store)
        self._on_status_change = on_status_change
        self._stopping = False

    async def _notify_status_change(self, state: DataProcessTaskState) -> None:
        """如果注册了状态变更回调，则异步调用。"""
        if self._on_status_change is not None:
            try:
                await self._on_status_change(state)
            except Exception:
                logger.debug(
                    "event=task_manager.notify_failed task_id=%s",
                    state.task_id,
                    exc_info=True,
                )

    async def _wait_tasks_with_timeout(
        self,
        tasks: list[asyncio.Task[object]] | list[asyncio.Task[None]],
        *,
        timeout: float,
        event_name: str,
    ) -> bool:
        """等待一组任务在超时内结束。"""
        pending_tasks = [task for task in tasks if not task.done()]
        if not pending_tasks:
            return True

        done, pending = await asyncio.wait(pending_tasks, timeout=timeout)
        await asyncio.gather(*done, return_exceptions=True)
        if pending:
            logger.warning(
                "event=%s timeout_seconds=%.1f pending_count=%s",
                event_name,
                timeout,
                len(pending),
            )
            return False
        return True

    @property
    def task_states(self) -> MutableMapping[str, DataProcessTaskState]:
        return self._task_states_view

    async def start(self) -> None:
        if self._workers:
            return

        self._running_jobs.clear()
        self._cancel_requests.clear()
        self._stopping = False
        self._queue = asyncio.Queue()
        await self._recover_tasks_on_startup()
        self._workers = [
            asyncio.create_task(
                self._worker_loop(index), name=f"data-process-worker-{index}"
            )
            for index in range(self.worker_count)
        ]
        logger.info(
            "event=task_manager.workers_started worker_count=%s", self.worker_count
        )

    async def _recover_tasks_on_startup(self) -> None:
        if self._queue is None:
            return

        states = self._state_store.list()
        recovered_count = 0
        resumed_count = 0

        for state in states:
            if state.status == DataProcessTaskStatus.CANCELING:
                state.status = DataProcessTaskStatus.CANCELED
                state.finished_at = datetime.now()
                state.error = "Task canceled before server restart"
                self._state_store.upsert(state)

            if state.status == DataProcessTaskStatus.RUNNING:
                state.status = DataProcessTaskStatus.QUEUED
                state.started_at = None
                state.finished_at = None
                state.error = None
                self._state_store.upsert(state)

            if state.status == DataProcessTaskStatus.QUEUED:
                await self._queue.put(
                    DataProcessQueueTask(
                        task_id=state.task_id,
                        paper_id=state.paper_id,
                        payload=state.payload,
                        retry_of_task_id=state.retry_of_task_id,
                    )
                )
                resumed_count += 1

            recovered_count += 1

        if recovered_count:
            logger.info(
                "event=task_manager.tasks_recovered total=%s resumed=%s",
                recovered_count,
                resumed_count,
            )

    async def stop(self) -> None:
        if self._queue is None:
            return

        # 停止取新任务；未执行的队列记录保留为 QUEUED，重启后恢复。
        self._stopping = True
        running_jobs = list(self._running_jobs.values())
        workers = list(self._workers)
        for worker in workers:
            worker.cancel()
        await self._wait_tasks_with_timeout(
            [*workers, *running_jobs],
            timeout=self._shutdown_timeout,
            event_name="task_manager.workers_stop_timeout",
        )

        self._workers = []
        self._queue = None
        self._running_jobs.clear()
        self._cancel_requests.clear()
        logger.info("event=task_manager.workers_stopped")

    async def submit_task(self, task: DataProcessQueueTask) -> DataProcessTaskState:
        if self._queue is None or self._stopping:
            logger.error(
                "event=task_manager.submit_rejected_not_started task_id=%s paper_id=%s",
                task.task_id,
                task.paper_id,
            )
            raise RuntimeError("DataProcessTaskManager is not started")
        if self._state_store.get(task.task_id) is not None:
            logger.warning(
                "event=task_manager.submit_rejected_duplicate task_id=%s paper_id=%s",
                task.task_id,
                task.paper_id,
            )
            raise ValueError(f"Task {task.task_id} already exists")

        state = DataProcessTaskState(
            task_id=task.task_id,
            paper_id=task.paper_id,
            payload=task.payload,
            status=DataProcessTaskStatus.QUEUED,
            created_at=datetime.now(),
            retry_of_task_id=task.retry_of_task_id,
        )
        self._state_store.upsert(state)
        await self._queue.put(task)
        logger.info(
            "event=task_manager.task_submitted task_id=%s paper_id=%s",
            task.task_id,
            task.paper_id,
        )
        await self._notify_status_change(state)
        return state

    def list_tasks(
        self,
        *,
        paper_id: str | None = None,
        keyword: str | None = None,
        offset: int = 0,
        limit: int = 20,
        sort_order: SortOrder = SortOrder.DESC,
        sort_by: TaskSortKey = TaskSortKey.CREATED_AT,
    ) -> list[DataProcessTaskState]:
        return self._state_store.list(
            paper_id=paper_id,
            keyword=keyword,
            offset=offset,
            limit=limit,
            sort_order=sort_order,
            sort_by=sort_by,
        )

    def count_total_tasks(
        self,
        paper_id: str | None = None,
        keyword: str | None = None,
    ) -> int:
        return self._state_store.count_total(paper_id=paper_id, keyword=keyword)

    def count_task_statuses(self) -> dict[str, int]:
        return self._state_store.count_statuses()

    def get_task(self, task_id: str) -> DataProcessTaskState | None:
        return self._state_store.get(task_id)

    def delete_task(self, task_id: str) -> None:
        self._state_store.delete(task_id)

    def cancel_task(self, task_id: str) -> DataProcessTaskState:
        state = self._state_store.get(task_id)
        if state is None:
            logger.warning("event=task_manager.cancel_not_found task_id=%s", task_id)
            raise KeyError(task_id)

        if state.status in {
            DataProcessTaskStatus.COMPLETED,
            DataProcessTaskStatus.FAILED,
            DataProcessTaskStatus.CANCELED,
        }:
            logger.warning(
                "event=task_manager.cancel_rejected_finished task_id=%s status=%s",
                task_id,
                state.status,
            )
            raise ValueError(f"Task {task_id} already finished")

        self._cancel_requests.add(task_id)
        if state.status == DataProcessTaskStatus.QUEUED:
            state.status = DataProcessTaskStatus.CANCELED
            state.finished_at = datetime.now()
            logger.info("event=task_manager.task_canceled_queued task_id=%s", task_id)
        else:
            state.status = DataProcessTaskStatus.CANCELING
            running = self._running_jobs.get(task_id)
            if running is not None:
                running.cancel()
            logger.info("event=task_manager.task_cancel_requested task_id=%s", task_id)
        self._state_store.upsert(state)
        asyncio.create_task(self._notify_status_change(state))
        return state

    async def _worker_loop(self, worker_id: int) -> None:
        queue = self._queue
        if queue is None:
            return

        while not self._stopping:
            task = await queue.get()
            if task is None:
                queue.task_done()
                logger.info("event=task_manager.worker_stopped worker_id=%s", worker_id)
                break

            state = self._state_store.get(task.task_id)
            if state is None:
                queue.task_done()
                continue

            if task.task_id in self._cancel_requests:
                state.status = DataProcessTaskStatus.CANCELED
                state.finished_at = datetime.now()
                self._cancel_requests.discard(task.task_id)
                self._state_store.upsert(state)
                logger.info(
                    "event=task_manager.task_canceled_before_start worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
                await self._notify_status_change(state)
                queue.task_done()
                continue

            state.status = DataProcessTaskStatus.RUNNING
            state.started_at = datetime.now()
            self._state_store.upsert(state)
            logger.info(
                "event=task_manager.task_started worker_id=%s task_id=%s paper_id=%s",
                worker_id,
                task.task_id,
                task.paper_id,
            )
            job = asyncio.create_task(self._run_data_process_task(task))
            self._running_jobs[task.task_id] = job
            try:
                await self._notify_status_change(state)
                if task.task_id in self._cancel_requests:
                    job.cancel()
                result = await asyncio.wait_for(job, timeout=self._task_max_seconds)
                self._sync_trace_ids_from_result(state, result)
                state.status = DataProcessTaskStatus.COMPLETED
                state.finished_at = datetime.now()
                logger.info(
                    "event=task_manager.task_completed worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
            except asyncio.TimeoutError:
                state.status = DataProcessTaskStatus.FAILED
                state.error = (
                    f"Task exceeded max execution time ({self._task_max_seconds:.1f}s)"
                )
                state.finished_at = datetime.now()
                logger.warning(
                    "event=task_manager.task_timeout worker_id=%s task_id=%s timeout_seconds=%.1f",
                    worker_id,
                    task.task_id,
                    self._task_max_seconds,
                )
            except asyncio.CancelledError:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
                state.status = DataProcessTaskStatus.CANCELED
                state.error = (
                    "Task canceled during server shutdown"
                    if self._stopping
                    else "Task canceled by user"
                )
                state.finished_at = datetime.now()
                logger.info(
                    "event=task_manager.task_canceled_running worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
                worker = asyncio.current_task()
                if self._stopping or (worker is not None and worker.cancelling()):
                    raise
            except Exception as exc:
                if isinstance(exc, PaperProcessorError):
                    state.extraction_trace_ids = list(exc.extraction_trace_ids)
                    state.analysis_trace_ids = list(exc.analysis_trace_ids)
                    state.extraction_fact_check_trace_ids = list(
                        exc.extraction_fact_check_trace_ids
                    )
                    state.analysis_fact_check_trace_ids = list(
                        exc.analysis_fact_check_trace_ids
                    )
                state.status = DataProcessTaskStatus.FAILED
                state.error = str(exc)
                state.finished_at = datetime.now()
                logger.exception(
                    "event=task_manager.task_failed worker_id=%s task_id=%s paper_id=%s error=%s",
                    worker_id,
                    task.task_id,
                    task.paper_id,
                    exc,
                )
            finally:
                self._state_store.upsert(state)
                await self._notify_status_change(state)
                self._running_jobs.pop(task.task_id, None)
                self._cancel_requests.discard(task.task_id)
                if task.cleanup_path and task.cleanup_path.exists():
                    try:
                        task.cleanup_path.unlink()
                    except Exception as exc:
                        logger.warning(
                            "event=task_manager.cleanup_failed path=%s error=%s",
                            task.cleanup_path,
                            exc,
                        )
                queue.task_done()

    @staticmethod
    def _sync_trace_ids_from_result(
        state: DataProcessTaskState, result: PaperProcessResult | object
    ) -> None:
        state.extraction_trace_ids = list(getattr(result, "extraction_trace_ids", []))
        state.analysis_trace_ids = list(getattr(result, "analysis_trace_ids", []))
        state.extraction_fact_check_trace_ids = list(
            getattr(result, "extraction_fact_check_trace_ids", [])
        )
        state.analysis_fact_check_trace_ids = list(
            getattr(result, "analysis_fact_check_trace_ids", [])
        )

    async def _run_data_process_task(
        self, task: DataProcessQueueTask
    ) -> PaperProcessResult:
        """执行单个 data-process 任务。"""
        paper_id = task.paper_id
        pdf_path = task.payload.get("pdf_path")

        if not isinstance(pdf_path, str) or not pdf_path:
            raise ValueError("Invalid pdf_path in task payload")

        logger.debug(
            "event=task_manager.task_payload_loaded task_id=%s paper_id=%s pdf_path=%s",
            task.task_id,
            paper_id,
            pdf_path,
        )

        repo = PaperRepository(get_db())
        processor = PaperProcessor(
            repo=repo,
            parser=PaperParser(pdf_parser=build_default_pdf_parser()),
            caller_id=task.task_id,
        )
        return await processor.process(
            paper_id=paper_id,
            pdf_path=Path(pdf_path),
            max_retries=get_app_settings_repo().get().data_process.max_retries,
        )
