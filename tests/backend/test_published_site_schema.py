"""The migration is the contract for the draft boundary, so assert its text.

A live database is not available in CI, so this reads the SQL and checks the
properties the design depends on: anon may select only published rows, and
there is no policy that would let a client flip the flag itself.
"""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260812200000_published_site.sql"
)


def test_migration_exists():
    assert MIGRATION.is_file()


def test_rls_is_enabled_and_anon_sees_only_published():
    sql = MIGRATION.read_text()
    assert "alter table public.published_site enable row level security" in sql
    assert "using (published = true)" in sql
    assert "to anon, authenticated" in sql


def test_no_client_write_policy_exists():
    """A client that could insert or update could publish itself live."""
    sql = MIGRATION.read_text().lower()
    assert "for insert" not in sql
    assert "for update" not in sql
    assert "for all" not in sql


def test_selected_repos_column_is_added_with_a_default():
    sql = MIGRATION.read_text()
    assert "add column selected_repos jsonb not null default '[]'::jsonb" in sql
