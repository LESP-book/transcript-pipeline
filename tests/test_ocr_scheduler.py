from __future__ import annotations

import threading

import pytest

from src.ocr_scheduler import OCRPageTask, StaggeredPageTaskError, run_staggered_page_ocr_tasks


def make_tasks(count: int) -> list[OCRPageTask]:
    return [
        OCRPageTask(page_number=page_number, image_url=f"page-{page_number}")
        for page_number in range(1, count + 1)
    ]


def test_staggered_page_tasks_restore_page_order_after_out_of_order_completion() -> None:
    second_page_finished = threading.Event()
    completion_order: list[int] = []
    tasks = make_tasks(3)

    def worker(task: OCRPageTask) -> str:
        if task.page_number == 1:
            assert second_page_finished.wait(timeout=2)
        if task.page_number == 2:
            completion_order.append(2)
            second_page_finished.set()
        else:
            completion_order.append(task.page_number)
        return f"第{task.page_number}页"

    results = run_staggered_page_ocr_tasks(
        [tasks[2], tasks[0], tasks[1]],
        worker,
        max_concurrency=2,
        submit_interval_seconds=0,
    )

    assert completion_order.index(2) < completion_order.index(1)
    assert results == ["第1页", "第2页", "第3页"]


def test_staggered_page_tasks_never_exceed_max_concurrency() -> None:
    lock = threading.Lock()
    first_pair_started = threading.Event()
    active = 0
    peak_active = 0
    starts = 0

    def worker(task: OCRPageTask) -> str:
        nonlocal active, peak_active, starts
        with lock:
            active += 1
            starts += 1
            peak_active = max(peak_active, active)
            if starts >= 2:
                first_pair_started.set()
        assert first_pair_started.wait(timeout=2)
        with lock:
            active -= 1
        return str(task.page_number)

    results = run_staggered_page_ocr_tasks(
        make_tasks(4),
        worker,
        max_concurrency=2,
        submit_interval_seconds=0,
    )

    assert results == ["1", "2", "3", "4"]
    assert peak_active == 2


def test_staggered_page_tasks_space_submissions_with_controllable_clock() -> None:
    now = 100.0
    dispatched_at: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    results = run_staggered_page_ocr_tasks(
        make_tasks(3),
        lambda task: str(task.page_number),
        max_concurrency=2,
        submit_interval_seconds=5,
        monotonic=monotonic,
        sleep=sleep,
        on_dispatched=lambda _task, submitted_at: dispatched_at.append(submitted_at),
    )

    assert results == ["1", "2", "3"]
    assert dispatched_at == [100.0, 105.0, 110.0]


def test_staggered_page_tasks_continuously_submit_without_waiting_for_previous_page() -> None:
    now = 0.0
    lock = threading.Lock()
    all_started = threading.Event()
    dispatched_at: list[float] = []
    active = 0
    peak_active = 0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def worker(task: OCRPageTask) -> str:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
            if active == 4:
                all_started.set()
        assert all_started.wait(timeout=2)
        with lock:
            active -= 1
        return str(task.page_number)

    results = run_staggered_page_ocr_tasks(
        make_tasks(4),
        worker,
        max_concurrency=0,
        submit_interval_seconds=5,
        monotonic=monotonic,
        sleep=sleep,
        on_dispatched=lambda _task, submitted_at: dispatched_at.append(submitted_at),
    )

    assert results == ["1", "2", "3", "4"]
    assert dispatched_at == [0.0, 5.0, 10.0, 15.0]
    assert peak_active == 4


def test_staggered_page_tasks_stop_new_submissions_after_failure() -> None:
    called_pages: list[int] = []

    def worker(task: OCRPageTask) -> str:
        called_pages.append(task.page_number)
        if task.page_number == 2:
            raise RuntimeError("account_stream_cap")
        return str(task.page_number)

    with pytest.raises(StaggeredPageTaskError, match="第 2 页") as error:
        run_staggered_page_ocr_tasks(
            make_tasks(4),
            worker,
            max_concurrency=1,
            submit_interval_seconds=0,
        )

    assert error.value.page_number == 2
    assert called_pages == [1, 2]
