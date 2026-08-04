"""llm_ingest.summarize_repo: Vertex-first with Gateway fallback.

Vertex is a Merit-dime surface (see paperpilot/vertex.py), so when it's
enabled summarize_repo must call vertex.generate_json with surface="ingest"
and the tenant_id bound to the session -- not just flip a transport flag
silently. Tests mock Vertex per the ticket's AC; no real Vertex/Gateway
calls happen here.
"""

from __future__ import annotations

from paperpilot import llm_ingest, trace, vertex
from paperpilot.github_ingest import RepoBundle
from paperpilot.vertex import GeminiResult

VALID_JSON = (
    '{"problem": "p", "contribution": "c", "method": "m", '
    '"results": "r", "limitations": "l", "keywords": [], "venue_hints": []}'
)


def _bundle() -> RepoBundle:
    return RepoBundle(
        owner="acme",
        name="widget",
        description="a widget",
        readme="# widget",
        files=[("main.py", "print(1)")],
        file_count=1,
        total_tokens=10,
    )


def test_summarize_repo_uses_vertex_with_surface_and_tenant_id(monkeypatch):
    monkeypatch.setattr(vertex, "vertex_enabled", lambda: True)

    calls = []

    def fake_generate_json(model, system_prompt, user_content, surface, tenant_id, **kwargs):
        calls.append((model, surface, tenant_id))
        return GeminiResult(text=VALID_JSON, tokens_in=10, tokens_out=5, finish_reason="STOP")

    monkeypatch.setattr(vertex, "generate_json", fake_generate_json)

    sid = trace.new_session("11111111-1111-1111-1111-111111111111")
    summary = llm_ingest.summarize_repo(_bundle(), sid)

    assert summary.problem == "p"
    assert len(calls) == 1
    model, surface, tenant_id = calls[0]
    assert surface == "ingest"
    assert tenant_id == "11111111-1111-1111-1111-111111111111"


def test_summarize_repo_vertex_disabled_falls_back_to_gateway(monkeypatch):
    monkeypatch.setattr(vertex, "vertex_enabled", lambda: False)

    def explode(*args, **kwargs):
        raise AssertionError("must not call Vertex when disabled")

    monkeypatch.setattr(vertex, "generate_json", explode)

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        cost = None

    class FakeChoice:
        def __init__(self):
            self.message = type("Msg", (), {"content": VALID_JSON})()
            self.finish_reason = "stop"

    class FakeCompletion:
        def __init__(self):
            self.choices = [FakeChoice()]
            self.usage = FakeUsage()

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm_ingest, "get_client", lambda: FakeClient())

    sid = trace.new_session("22222222-2222-2222-2222-222222222222")
    summary = llm_ingest.summarize_repo(_bundle(), sid)

    assert summary.problem == "p"
