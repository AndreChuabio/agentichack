"""backend.services.assist_service: Vertex-first with Gateway fallback.

The help assistant runs on Merit's own key (backend/quotas.py), which makes
it a Merit-dime surface per paperpilot/vertex.py -- so when Vertex is
enabled the assistant must stream through Gemini-on-Vertex, not Claude via
the Gateway, and still record usage with surface="assist". When Vertex is
disabled, behavior must be unchanged from before this ticket: Claude via
the Gateway. Tests mock Vertex and the Gateway client; no real calls happen.
"""

from __future__ import annotations

from paperpilot import trace, vertex
from paperpilot.gateway import DEFAULTS
from backend.services import assist_service


def test_assist_answer_uses_vertex_when_enabled(monkeypatch):
    monkeypatch.setattr(vertex, "vertex_enabled", lambda: True)

    calls = []

    def fake_stream(model, system_prompt, user_content, surface, tenant_id, **kwargs):
        calls.append((model, surface, tenant_id))
        yield "Hel"
        yield "lo"

    monkeypatch.setattr(vertex, "generate_text_stream", fake_stream)

    def explode(*args, **kwargs):
        raise AssertionError("must not call the Gateway when Vertex is enabled")

    monkeypatch.setattr(assist_service, "get_client", explode)

    sid = trace.new_session("33333333-3333-3333-3333-333333333333")
    deltas = list(assist_service.assist_answer("How do I win?", "track", None, sid))

    assert deltas == ["Hel", "lo"]
    assert len(calls) == 1
    model, surface, tenant_id = calls[0]
    assert model == DEFAULTS["assist_vertex"]
    assert surface == "assist"
    assert tenant_id == "33333333-3333-3333-3333-333333333333"


def test_assist_answer_falls_back_to_gateway_when_vertex_disabled(monkeypatch):
    monkeypatch.setattr(vertex, "vertex_enabled", lambda: False)

    def explode(*args, **kwargs):
        raise AssertionError("must not call Vertex when disabled")

    monkeypatch.setattr(vertex, "generate_text_stream", explode)

    class FakeDelta:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.delta = FakeDelta(content)

    class FakeEvent:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return iter([FakeEvent("Hi"), FakeEvent(" there")])

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(assist_service, "get_client", lambda: FakeClient())

    sid = trace.new_session("44444444-4444-4444-4444-444444444444")
    deltas = list(assist_service.assist_answer("How do I win?", "track", None, sid))

    assert deltas == ["Hi", " there"]
    assert captured["kwargs"]["model"] == DEFAULTS["draft"]
