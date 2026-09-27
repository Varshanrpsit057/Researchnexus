"""Column types shared by app/db/models.py.

`UTCDateTime` is the one time column type (remediation Phase 4). SQLite
stores a datetime as text with no zone, so every read used to come back
naive; the few reads patched by hand (`_utc`) left the rest -- jobs, runs,
stage runs, workspace members -- to be serialized without a zone and read
by the browser as its own local time (hours off, sometimes the wrong day).

- write: an aware value is converted to UTC; a naive one is refused, so
  "which zone was this?" can never be stored;
- read: always aware UTC, on SQLite (naive text -> UTC) and on a database
  that keeps the zone (converted to UTC).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class NaiveDatetimeError(ValueError):
    """A datetime without a zone was about to be stored."""


class UTCDateTime(TypeDecorator[dt.datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise NaiveDatetimeError(
                f"refusing to store a datetime without a zone ({value!r}); use datetime.now(timezone.utc)"
            )
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value: dt.datetime | None, dialect: Dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)  # stored as UTC wall time
        return value.astimezone(dt.timezone.utc)
