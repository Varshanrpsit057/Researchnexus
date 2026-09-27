"""`UTCDateTime` (remediation Phase 4): every stored time reads back as an
aware UTC datetime, whatever zone it was written in, and a time without a
zone can't be stored at all."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select, text
from sqlalchemy.exc import StatementError

from app.db.types import NaiveDatetimeError, UTCDateTime

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@pytest.fixture()
def table():  # noqa: ANN201
    engine = create_engine("sqlite://")
    meta = MetaData()
    t = Table("t", meta, Column("id", Integer, primary_key=True), Column("at", UTCDateTime(), nullable=True))
    meta.create_all(engine)
    return engine, t


def _write_read(table, value: dt.datetime | None) -> dt.datetime | None:  # noqa: ANN001
    engine, t = table
    with engine.begin() as conn:
        conn.execute(insert(t).values(id=1, at=value))
        return conn.execute(select(t.c.at)).scalar_one()


def test_a_utc_time_reads_back_aware_and_unchanged(table) -> None:  # noqa: ANN001
    at = dt.datetime(2026, 9, 27, 4, 11, 50, 409852, tzinfo=dt.timezone.utc)
    got = _write_read(table, at)
    assert got == at and got is not None and got.tzinfo == dt.timezone.utc


def test_a_local_time_is_stored_as_the_same_instant_in_utc(table) -> None:  # noqa: ANN001
    # 09:41 in India is 04:11 UTC: the instant is kept, never the wall-clock reading
    ist = dt.datetime(2026, 9, 27, 9, 41, 50, tzinfo=IST)
    got = _write_read(table, ist)
    assert got == ist and got is not None
    assert (got.hour, got.minute, got.utcoffset()) == (4, 11, dt.timedelta(0))
    engine, t = table
    with engine.connect() as conn:
        raw = conn.execute(text("select at from t")).scalar_one()
    assert raw.startswith("2026-09-27 04:11:50")  # stored as UTC wall time


def test_a_time_without_a_zone_is_refused(table) -> None:  # noqa: ANN001
    with pytest.raises(StatementError) as info:
        _write_read(table, dt.datetime(2026, 9, 27, 4, 11))
    assert isinstance(info.value.orig, NaiveDatetimeError)


def test_rows_written_before_as_zoneless_text_read_back_as_utc(table) -> None:  # noqa: ANN001
    engine, t = table
    with engine.begin() as conn:
        conn.execute(text("insert into t (id, at) values (1, '2026-09-26 23:43:05.549886')"))
        got = conn.execute(select(t.c.at)).scalar_one()
    assert got == dt.datetime(2026, 9, 26, 23, 43, 5, 549886, tzinfo=dt.timezone.utc)


def test_no_time_stays_no_time(table) -> None:  # noqa: ANN001
    assert _write_read(table, None) is None
