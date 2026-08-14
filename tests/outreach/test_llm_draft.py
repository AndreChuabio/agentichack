"""Outreach drafting works with an LLM key alone, no Senso account.

Also pins the cross-user identity contract: every prompt presents the authed
caller's profile as the sender, carries the identity guard against retrieved
knowledge-base content, and an empty profile yields neutral placeholders
rather than an identity borrowed from the knowledge base.
"""

import pytest

from paperpilot.outreach import llm_draft
from paperpilot.outreach.orchestrator import generate_drafts
from paperpilot.outreach.purpose import Purpose

QA_PROFILE = {
    "name": "QA Tester",
    "title": "QA Engineer",
    "site_url": "https://qa-tester.example.com",
    "resume_text": "Five years of release QA across fintech platforms.",
}

ANDRE_PROFILE = {
    "name": "Andre Chuabio",
    "title": "Data Scientist",
}


class _FakeCompletions:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Msg:
            content = self._text

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, text="drafted markdown"):
        self.chat = type("chat", (), {"completions": _FakeCompletions(text)})()


def test_draft_channel_builds_prompt_from_content_type(monkeypatch):
    """The channel's template and writing rules are what shape the prompt."""
    fake = _FakeClient()
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake)

    out = llm_draft.draft_channel("linkedin_dm", "Audience: a peer.\n\nContext: x")

    assert out == "drafted markdown"
    prompt = fake.chat.completions.calls[0]["messages"][1]["content"]
    assert "under 600 chars" in prompt
    assert "End with one explicit ask." in prompt
    assert "Audience: a peer." in prompt


def test_generate_drafts_needs_no_senso(monkeypatch):
    """With senso=None, every channel still produces a card with markdown."""
    fake = _FakeClient("hello there")
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake)

    cards = generate_drafts(
        senso=None,
        purpose=Purpose.NETWORK,
        context="I work on pgvector retrieval.",
        session_id="sess_test",
        user_id="11111111-1111-1111-1111-111111111111",
        logger=None,
    )

    # NETWORK maps to two channels in purpose.PURPOSE_CHANNELS.
    assert len(cards) == 2
    assert all(c.markdown == "hello there" for c in cards)
    assert all(c.error is None for c in cards)


def _prompt_of(fake):
    """Return the user-message prompt captured by a _FakeClient."""
    return fake.chat.completions.calls[0]["messages"][1]["content"]


def test_prompt_presents_caller_profile_as_sender(monkeypatch):
    """The caller's saved profile is the sender identity in the prompt."""
    fake = _FakeClient()
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake)

    llm_draft.draft_channel("linkedin_dm", "ctx", sender_profile=QA_PROFILE)

    prompt = _prompt_of(fake)
    assert "Sender profile (the message is written by this person" in prompt
    assert "QA Tester" in prompt
    assert "QA Engineer" in prompt
    assert "https://qa-tester.example.com" in prompt
    assert "Five years of release QA" in prompt


def test_prompt_carries_identity_guard(monkeypatch):
    """The KB-identity guard is present whether or not a profile exists."""
    for profile in (QA_PROFILE, None):
        fake = _FakeClient()
        monkeypatch.setattr(llm_draft, "get_client", lambda f=fake: f)
        llm_draft.draft_channel("linkedin_dm", "ctx", sender_profile=profile)
        prompt = _prompt_of(fake)
        assert llm_draft.IDENTITY_GUARD in prompt
        assert "are NOT the sender's" in prompt


def test_different_profiles_yield_different_senders(monkeypatch):
    """Two users' prompts each carry only their own identity."""
    fake_a = _FakeClient()
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake_a)
    llm_draft.draft_channel("linkedin_dm", "ctx", sender_profile=QA_PROFILE)

    fake_b = _FakeClient()
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake_b)
    llm_draft.draft_channel("linkedin_dm", "ctx", sender_profile=ANDRE_PROFILE)

    prompt_a = _prompt_of(fake_a)
    prompt_b = _prompt_of(fake_b)
    assert "QA Tester" in prompt_a
    assert "Andre Chuabio" not in prompt_a
    assert "Andre Chuabio" in prompt_b
    assert "QA Tester" not in prompt_b


def test_empty_profile_uses_placeholders_not_kb_identity(monkeypatch):
    """No profile means neutral placeholders, never an invented identity."""
    for profile in (None, {}, {"name": "", "title": ""}):
        fake = _FakeClient()
        monkeypatch.setattr(llm_draft, "get_client", lambda f=fake: f)
        llm_draft.draft_channel("linkedin_dm", "ctx", sender_profile=profile)
        prompt = _prompt_of(fake)
        assert "[Your name]" in prompt
        assert "Do not invent a name" in prompt
        assert llm_draft.IDENTITY_GUARD in prompt


def test_style_reference_is_quarantined(monkeypatch):
    """Retrieved tone material is framed as style only, with the guard."""
    fake = _FakeClient()
    monkeypatch.setattr(llm_draft, "get_client", lambda: fake)

    kb_text = "I am Andre Chuabio, M.S. candidate, reach me at AC233@Fordham.edu"
    llm_draft.draft_channel(
        "linkedin_dm", "ctx", sender_profile=QA_PROFILE, style_reference=kb_text
    )

    prompt = _prompt_of(fake)
    assert "use for tone, register, and formatting only" in prompt
    assert "<style-reference>" in prompt
    assert kb_text in prompt
    assert "belonging to someone else" in prompt
    assert llm_draft.IDENTITY_GUARD in prompt


def test_system_prompt_forbids_kb_identity():
    """The system prompt itself blocks retrieved content as identity source."""
    assert (
        "never a source of the sender's identity" in llm_draft._SYSTEM_PROMPT
    )
    assert "sender profile" in llm_draft._SYSTEM_PROMPT


def test_one_channel_failing_does_not_cancel_the_others(monkeypatch):
    """A failure is isolated to its own card, as before."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model unavailable")
        return _FakeClient("second one worked")

    monkeypatch.setattr(llm_draft, "get_client", flaky)

    cards = generate_drafts(
        senso=None,
        purpose=Purpose.NETWORK,
        context="ctx",
        session_id="sess_test",
        user_id="11111111-1111-1111-1111-111111111111",
        logger=None,
    )
    assert cards[0].error is not None
    assert cards[1].markdown == "second one worked"
