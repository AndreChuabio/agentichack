"""Guards on the one route that serves stored HTML to the public.

There is no live database in the suite, so this cannot exercise RLS end to end
-- and the Playwright spec that was supposed to cover it only asserts an unknown
slug 404s, which passes identically whether RLS is on, off, or bypassed. That is
a test that cannot fail.

What can be checked here is that neither property the draft boundary rests on
gets edited away:

1. The route reads ``live_html``. ``html`` is the working draft and changes on
   every rebuild, so serving it would put an unpublished render in front of
   visitors -- the exact failure the draft/live split was introduced to fix.
2. The route reads through the ordinary Supabase client, which is created with
   NEXT_PUBLIC_SUPABASE_ANON_KEY (see web/lib/supabase/server.ts). RLS is what
   hides a draft; a service-role client would bypass RLS entirely and serve every
   draft in the table to the world.

Both are one-line edits away from being wrong, and neither would fail any other
test in this suite.
"""

from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "web"
ROUTE = _WEB / "app" / "u" / "[slug]" / "page.tsx"
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260812210000_published_site_live_html.sql"
)


def test_the_public_route_exists():
    assert ROUTE.is_file(), f"expected the public site route at {ROUTE}"


def test_the_route_serves_live_html_and_never_the_draft():
    source = ROUTE.read_text()
    assert '.select("live_html")' in source
    assert '.select("html")' not in source
    assert "data.live_html" in source


def test_the_route_reads_through_the_anon_client_so_rls_applies():
    source = ROUTE.read_text()
    assert 'from "@/lib/supabase/server"' in source
    # A service-role key bypasses RLS, which would serve every draft publicly.
    assert "SERVICE_ROLE" not in source.upper()


def test_a_missing_row_is_a_404_rather_than_an_empty_page():
    """A draft returns no row under RLS, so this is the draft's user-visible
    behaviour as much as it is the unknown-slug behaviour."""
    source = ROUTE.read_text()
    assert "notFound()" in source


def test_the_live_html_column_exists_and_backfills_live_rows():
    sql = MIGRATION.read_text()
    assert "add column live_html text not null default ''" in sql
    # Rows that were already live must keep serving what they were serving
    # rather than going blank the moment the column lands.
    assert "update public.published_site set live_html = html where published = true" in sql
