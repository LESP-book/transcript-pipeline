from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class OCRPageTask:
    page_number: int
    image_url: str


class StaggeredPageTaskError(RuntimeError):
    """单页 OCR 任务失败，并保留原始页码与异常。"""

    def __init__(self, page_number: int, cause: Exception) -> None:
        super().__init__(f"第 {page_number} 页 OCR 任务失败: {cause}")
        self.page_number = page_number
        self.cause = cause


def run_staggered_page_ocr_tasks(
    tasks: Sequence[OCRPageTask],
    worker: Callable[[OCRPageTask], str],
    *,
    max_concurrency: int,
    submit_interval_seconds: float,
    logger: logging.Logger | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_dispatched: Callable[[OCRPageTask, float], None] | None = None,
) -> list[str]:
    """连续错峰执行单页 OCR，并将乱序结果恢复为页码顺序。"""

    if max_concurrency < 0:
        raise ValueError("max_concurrency 不能小于 0")
    if submit_interval_seconds < 0:
        raise ValueError("submit_interval_seconds 不能小于 0")
    if not tasks:
        return []

    ordered_tasks = sorted(tasks, key=lambda task: task.page_number)
    if len({task.page_number for task in ordered_tasks}) != len(ordered_tasks):
        raise ValueError("OCR 页任务的页码不能重复")
    results: dict[int, str] = {}

    next_task_index = 0
    next_submit_at = monotonic()
    first_failure: tuple[OCRPageTask, Exception] | None = None
    active: dict[Future[str], OCRPageTask] = {}

    # 0 表示按固定间隔持续投递、不限制活动请求数；线程仍只会在页面实际投递时按需创建。
    worker_count = max_concurrency or len(ordered_tasks)
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="pdf-ocr") as executor:
        while next_task_index < len(ordered_tasks) or active:
            completed = [future for future in active if future.done()]
            for future in completed:
                task = active.pop(future)
                try:
                    page_text = future.result()
                except Exception as exc:
                    if first_failure is None:
                        first_failure = (task, exc)
                    if logger:
                        logger.error("OCR 页任务失败 | page=%s/%s | %s", task.page_number, len(ordered_tasks), exc)
                else:
                    results[task.page_number] = page_text
                    if logger:
                        logger.info(
                            "OCR 页任务完成 | page=%s/%s | active=%s",
                            task.page_number,
                            len(ordered_tasks),
                            len(active),
                        )

            if first_failure is not None:
                if active:
                    wait(active, return_when=FIRST_COMPLETED)
                    continue
                break

            has_capacity = max_concurrency == 0 or len(active) < max_concurrency
            if next_task_index < len(ordered_tasks) and has_capacity:
                delay = next_submit_at - monotonic()
                if delay > 0:
                    sleep(delay)
                    continue

                task = ordered_tasks[next_task_index]
                submitted_at = monotonic()
                active[executor.submit(worker, task)] = task
                next_task_index += 1
                next_submit_at = submitted_at + submit_interval_seconds
                if on_dispatched:
                    on_dispatched(task, submitted_at)
                if logger:
                    logger.info(
                        "OCR 页任务已投递 | page=%s/%s | active=%s",
                        task.page_number,
                        len(ordered_tasks),
                        len(active),
                    )
                continue

            if active:
                wait(active, return_when=FIRST_COMPLETED)

    if first_failure is not None:
        failed_task, cause = first_failure
        raise StaggeredPageTaskError(failed_task.page_number, cause) from cause
    if len(results) != len(ordered_tasks):
        raise RuntimeError("OCR 页任务结束后仍存在缺失结果")
    return [results[task.page_number] for task in ordered_tasks]
