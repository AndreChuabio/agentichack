import pytest

from backend.services import publish_target as pt


class _FakeCursor:
    """Records SQL and replays queued rows, so slug logic tests without a DB."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
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


# reserve_slug queries the caller's own row FIRST, so every fixture below leads
# with what that lookup returns: (None,) for "this user holds no slug yet".
_HOLDS_NOTHING = (None,)


def test_reserved_slug_is_never_handed_out(monkeypatch):
    conn = _FakeConn([_HOLDS_NOTHING, (None,), (None,)])
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    slug = pt.HostedTarget().reserve_slug("u1", "Market")
    assert slug not in pt.RESERVED_SLUGS
    assert slug.startswith("market-")


def test_slug_collision_appends_a_counter(monkeypatch):
    # This user holds nothing; the first candidate is taken by somebody else.
    conn = _FakeConn([_HOLDS_NOTHING, ("someone-else",), (None,)])
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    slug = pt.HostedTarget().reserve_slug("u1", "Andre Chuabio")
    assert slug == "andre-chuabio-2"


def test_slug_is_stable_for_the_same_user(monkeypatch):
    conn = _FakeConn([_HOLDS_NOTHING, ("u1",)])
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    assert pt.HostedTarget().reserve_slug("u1", "Andre Chuabio") == "andre-chuabio"


def test_a_held_slug_survives_the_name_drifting(monkeypatch):
    """The name is model output and an editable profile field; the URL is not.

    Re-deriving the slug from the name on every build would move the user onto
    a new URL the moment either string changed by a word, silently 404ing a link
    they had already shared.
    """
    conn = _FakeConn([("andre-chuabio",)])
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    slug = pt.HostedTarget().reserve_slug("u1", "Andre Chuabio Portfolio 2026")
    assert slug == "andre-chuabio"


def test_unpublish_deletes_rather_than_flagging(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    pt.HostedTarget().unpublish("u1")
    sql = " ".join(s for s, _ in conn.cur.executed).lower()
    assert "delete from published_site" in sql
    assert "set published = false" not in sql


def test_public_url_uses_the_configured_base(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_BASE_URL", "https://meritai.me")
    assert pt.HostedTarget().public_url("andre") == "https://meritai.me/u/andre"


# ---------------------------------------------------------------------------
# Regression: the draft boundary. `html` is the working draft and `live_html` is
# what /u/<slug> serves. When one column did both jobs, a rebuild of an
# already-live site replaced the public page instantly with no second action --
# so ticking another piece of evidence and rebuilding to look at it published
# it, while the wizard still said "draft".
# ---------------------------------------------------------------------------


def test_save_draft_never_touches_what_is_being_served(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    pt.HostedTarget().save_draft("u1", "andre-chuabio", "<p>new</p>")
    sql = " ".join(s for s, _ in conn.cur.executed).lower()
    # Match the assignment, not the bare word: the table itself is named
    # published_site, so "published" appears in every statement here.
    assert "live_html" not in sql, "a rebuild must not change the served page"
    assert "published =" not in sql, "a rebuild must not publish or unpublish"
    assert "set slug = excluded.slug, html = excluded.html" in sql


def test_publish_is_the_only_thing_that_changes_the_served_page(monkeypatch):
    conn = _FakeConn([("andre-chuabio",)])
    monkeypatch.setattr(pt.supabase_client, "get_conn", lambda: conn)
    url = pt.HostedTarget().publish("u1")
    sql = " ".join(s for s, _ in conn.cur.executed).lower()
    assert "set live_html = html" in sql
    assert "published = true" in sql
    assert url.endswith("/u/andre-chuabio")


def test_publishing_with_no_built_site_raises():
    """RETURNING gives no row when the user has never built, so this is not a
    silent success that would report a URL serving nothing."""
    import pytest as _pytest

    conn = _FakeConn([])
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(pt.supabase_client, "get_conn", lambda: conn)
        with _pytest.raises(ValueError):
            pt.HostedTarget().publish("u1")
