"""gemini_usage: per-call token usage logging for Gemini-on-Vertex-AI calls.

Covers the Supabase write helper (paperpilot.supabase_client.record_gemini_usage)
and paperpilot.vertex's usage-recording choke point that every Vertex call
routes through. tests/test_supabase_client_tenancy.py documents why these
tests capture the actual SQL/params rather than mocking the write away.
"""

from __future__ import annotations

import inspect

from paperpilot import supabase_client


def test_record_gemini_usage_has_expected_signature():
    sig = inspect.signature(supabase_client.record_gemini_usage)
    assert list(sig.parameters) == [
        "surface",
        "model",
        "tokens_in",
        "tokens_out",
        "tenant_id",
        "conn",
    ]


def test_record_gemini_usage_writes_all_fields(monkeypatch):
    captured = {}

    class FakeConn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def close(self):
            pass

    monkeypatch.setattr(supabase_client, "get_conn", lambda: FakeConn())

    supabase_client.record_gemini_usage(
        "ingest", "gemini-2.5-flash", 120, 45, "11111111-1111-1111-1111-111111111111"
    )

    assert "gemini_usage" in captured["sql"]
    assert "ingest" in captured["params"]
    assert "gemini-2.5-flash" in captured["params"]
    assert 120 in captured["params"]
    assert 45 in captured["params"]
    assert "11111111-1111-1111-1111-111111111111" in captured["params"]


def test_record_gemini_usage_tenant_id_may_be_none(monkeypatch):
    """A Vertex call outside a bound session (CLI/system) must still log --
    tenant_id is nullable, mirroring trace_log.user_id."""
    captured = {}

    class FakeConn:
        def execute(self, sql, params):
            captured["params"] = params

        def close(self):
            pass

    monkeypatch.setattr(supabase_client, "get_conn", lambda: FakeConn())

    supabase_client.record_gemini_usage("ingest", "gemini-2.5-flash", 1, 1, None)

    assert captured["params"][-1] is None
