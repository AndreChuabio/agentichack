"""The picker's repo selection has to survive a write and a read.

A column nobody writes is a knob that does nothing: the profile SELECT lists its
columns explicitly and Profile is a fixed dataclass, so selected_repos only
round trips if every layer names it.
"""

import json

from backend.services import market_service

_ROW_HEAD = (
    "Andre", "Engineer", "about", "plain",
    "https://github.com/andre", "", "", "", "resume",
)


class _FakeCursor:
    """Records SQL and replays queued rows, so persistence tests need no DB."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, rows=()):
        self.cur = _FakeCursor(rows)

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


def test_selected_repos_round_trips_through_the_profile():
    """A picker choice that is written but never read back is a knob that does nothing."""
    assert "selected_repos" in market_service._PROFILE_FIELDS
    assert hasattr(market_service.Profile(user_id="u1"), "selected_repos")
    assert market_service.Profile(user_id="u1").selected_repos == []


def test_get_profile_reads_the_selection_back(monkeypatch):
    conn = _FakeConn([(*_ROW_HEAD, ["andre/merit"])])
    monkeypatch.setattr(market_service.supabase_client, "get_conn", lambda: conn)
    assert market_service.get_profile("u1").selected_repos == ["andre/merit"]
    sql = conn.cur.executed[0][0]
    assert "selected_repos" in sql


def test_a_hand_edited_row_cannot_break_the_form(monkeypatch):
    """jsonb holds anything; the form only ever means a list of repo names."""
    conn = _FakeConn([(*_ROW_HEAD, {"not": "a list"})])
    monkeypatch.setattr(market_service.supabase_client, "get_conn", lambda: conn)
    assert market_service.get_profile("u1").selected_repos == []


def test_the_selection_is_written_as_json_not_a_python_repr(monkeypatch):
    conn = _FakeConn([None])
    monkeypatch.setattr(market_service.supabase_client, "get_conn", lambda: conn)
    market_service.upsert_profile("u1", {"selected_repos": ["andre/merit"]})
    insert = conn.cur.executed[0]
    assert "selected_repos" in insert[0]
    assert json.dumps(["andre/merit"]) in insert[1]
