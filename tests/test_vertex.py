"""paperpilot.vertex: first-party Gemini on Vertex AI.

Covers vertex_enabled() gating, the JSON and streaming call paths, and the
usage-recording choke point (_record_usage) that every Vertex call routes
through so gemini_usage stays complete without each surface remembering to
log it itself.
"""

from __future__ import annotations

from paperpilot import vertex


class FakeUsage:
    def __init__(self, prompt_tokens: int, output_tokens: int):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = output_tokens


class FakeCandidate:
    def __init__(self, finish_reason: str):
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, text: str, prompt_tokens: int, output_tokens: int, finish_reason="STOP"):
        self.text = text
        self.usage_metadata = FakeUsage(prompt_tokens, output_tokens)
        self.candidates = [FakeCandidate(finish_reason)]


class FakeModels:
    def __init__(self, response=None, chunks=None):
        self._response = response
        self._chunks = chunks or []
        self.last_call: dict = {}

    def generate_content(self, **kwargs):
        self.last_call = kwargs
        return self._response

    def generate_content_stream(self, **kwargs):
        self.last_call = kwargs
        return iter(self._chunks)


class FakeClient:
    def __init__(self, models: FakeModels):
        self.models = models


def test_vertex_enabled_reflects_env(monkeypatch):
    monkeypatch.setattr(vertex, "_VERTEX_PROJECT", "")
    assert vertex.vertex_enabled() is False
    monkeypatch.setattr(vertex, "_VERTEX_PROJECT", "my-project")
    assert vertex.vertex_enabled() is True


# ---------------------------------------------------------------------------
# generate_json
# ---------------------------------------------------------------------------


def test_generate_json_returns_normalized_result(monkeypatch):
    response = FakeResponse('{"ok": true}', 100, 20)
    fake_models = FakeModels(response=response)
    monkeypatch.setattr(vertex, "_client", lambda: FakeClient(fake_models))
    monkeypatch.setattr(vertex, "_record_usage", lambda *a, **k: None)

    result = vertex.generate_json(
        "google/gemini-2.5-flash", "sys", "user text", surface="ingest", tenant_id="u1"
    )

    assert result.text == '{"ok": true}'
    assert result.tokens_in == 100
    assert result.tokens_out == 20
    assert result.finish_reason == "STOP"
    # The gateway-style "google/" prefix must be stripped for the bare Vertex model id.
    assert fake_models.last_call["model"] == "gemini-2.5-flash"


def test_generate_json_records_usage_with_bare_model_id(monkeypatch):
    response = FakeResponse("{}", 7, 3)
    fake_models = FakeModels(response=response)
    monkeypatch.setattr(vertex, "_client", lambda: FakeClient(fake_models))

    recorded = []
    monkeypatch.setattr(
        vertex, "_record_usage", lambda *a, **k: recorded.append((a, k))
    )

    vertex.generate_json(
        "google/gemini-2.5-flash", "sys", "user text", surface="ingest", tenant_id="u1"
    )

    assert len(recorded) == 1
    args, _ = recorded[0]
    assert args == ("ingest", "gemini-2.5-flash", 7, 3, "u1")


# ---------------------------------------------------------------------------
# generate_text_stream
# ---------------------------------------------------------------------------


class FakeStreamChunk:
    def __init__(self, text, usage=None):
        self.text = text
        self.usage_metadata = usage


def test_generate_text_stream_yields_deltas(monkeypatch):
    chunks = [
        FakeStreamChunk("Hel"),
        FakeStreamChunk("lo"),
        FakeStreamChunk("", usage=FakeUsage(50, 10)),
    ]
    fake_models = FakeModels(chunks=chunks)
    monkeypatch.setattr(vertex, "_client", lambda: FakeClient(fake_models))
    monkeypatch.setattr(vertex, "_record_usage", lambda *a, **k: None)

    deltas = list(
        vertex.generate_text_stream(
            "google/gemini-2.5-flash", "sys", "question", surface="assist", tenant_id="u2"
        )
    )

    assert deltas == ["Hel", "lo"]
    assert fake_models.last_call["model"] == "gemini-2.5-flash"


def test_generate_text_stream_records_cumulative_usage_after_exhaustion(monkeypatch):
    chunks = [
        FakeStreamChunk("a", usage=FakeUsage(10, 1)),
        FakeStreamChunk("b", usage=FakeUsage(10, 2)),
    ]
    fake_models = FakeModels(chunks=chunks)
    monkeypatch.setattr(vertex, "_client", lambda: FakeClient(fake_models))

    recorded = []
    monkeypatch.setattr(
        vertex, "_record_usage", lambda *a, **k: recorded.append(a)
    )

    list(
        vertex.generate_text_stream(
            "google/gemini-2.5-flash", "sys", "question", surface="assist", tenant_id="u2"
        )
    )

    assert len(recorded) == 1
    assert recorded[0] == ("assist", "gemini-2.5-flash", 10, 2, "u2")


# ---------------------------------------------------------------------------
# _record_usage: the choke point every Vertex call routes through
# ---------------------------------------------------------------------------


def test_record_usage_noop_without_supabase_configured(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("must not write when SUPABASE_DB_URL is unset")

    monkeypatch.setattr("paperpilot.supabase_client.record_gemini_usage", explode)
    vertex._record_usage("ingest", "gemini-2.5-flash", 1, 1, "u1")


def test_record_usage_writes_when_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    calls = []
    monkeypatch.setattr(
        "paperpilot.supabase_client.record_gemini_usage",
        lambda *a, **k: calls.append(a),
    )

    vertex._record_usage("assist", "gemini-2.5-flash", 5, 6, "u2")

    assert calls == [("assist", "gemini-2.5-flash", 5, 6, "u2")]


def test_record_usage_write_failure_never_raises(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("paperpilot.supabase_client.record_gemini_usage", boom)
    vertex._record_usage("ingest", "gemini-2.5-flash", 1, 1, "u1")
