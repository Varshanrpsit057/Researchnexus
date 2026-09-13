from __future__ import annotations

import time

from app.telemetry.stage_timer import StageTimer


def test_elapsed_ms_is_none_before_the_block_exits() -> None:
    t = StageTimer()
    assert t.elapsed_ms is None


def test_elapsed_ms_is_a_non_negative_int_after_the_block_exits() -> None:
    with StageTimer() as t:
        pass
    assert isinstance(t.elapsed_ms, int)
    assert t.elapsed_ms >= 0


def test_elapsed_ms_reflects_actual_time_spent() -> None:
    with StageTimer() as t:
        time.sleep(0.02)
    assert t.elapsed_ms is not None
    assert t.elapsed_ms >= 15  # allow scheduler slack below the 20ms sleep


def test_elapsed_ms_is_set_even_when_the_block_raises() -> None:
    t = StageTimer()
    try:
        with t:
            raise ValueError("boom")
    except ValueError:
        pass
    assert t.elapsed_ms is not None
