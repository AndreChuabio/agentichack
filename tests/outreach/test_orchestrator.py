from unittest.mock import MagicMock

from paperpilot.outreach import llm_draft
from paperpilot.outreach.orchestrator import generate_drafts, DraftCard
from paperpilot.outreach.purpose import Purpose


def _capture_draft_channel(monkeypatch, reply="llm draft as caller"):
    """Replace llm_draft.draft_channel with a recorder returning `reply`."""
    calls = []

    def fake(channel, full_context, sender_profile=None, style_reference=""):
        calls.append(
            {
                "channel": channel,
                "full_context": full_context,
                "sender_profile": sender_profile,
                "style_reference": style_reference,
            }
        )
        return reply

    monkeypatch.setattr(llm_draft, "draft_channel", fake)
    return calls


def test_generate_drafts_returns_one_card_per_channel(monkeypatch):
    calls = _capture_draft_channel(monkeypatch)
    senso = MagicMock()
    senso.get_or_create_content_type.side_effect = lambda name, cfg: f"ct-{name}"
    senso.generate_sample.side_effect = lambda content_type_id, context: f"job-{content_type_id}"
    senso.poll_until_done.side_effect = lambda jid, **kw: {
        "status": "completed",
        "result": {
            "raw_markdown": f"tone sample for {jid}",
            "content_id": f"d-{jid}",
        },
    }

    cards = generate_drafts(
        senso=senso,
        purpose=Purpose.BRAND,
        context="ML4H paper on retrieval calibration",
        session_id="sess_test",
        user_id="andre",
        logger=MagicMock(),
    )

    assert [c.channel for c in cards] == ["linkedin_post_brand", "x_thread_brand"]
    assert all(isinstance(c, DraftCard) for c in cards)
    # The user-visible markdown is always the LLM's output written as the
    # caller; the Senso sample only rides along as a style reference.
    assert all(c.markdown == "llm draft as caller" for c in cards)
    assert all(c.sample_job_id.startswith("job-ct-") for c in cards)
    assert [c["style_reference"] for c in calls] == [
        "tone sample for job-ct-linkedin_post_brand",
        "tone sample for job-ct-x_thread_brand",
    ]


def test_senso_output_is_never_the_returned_draft(monkeypatch):
    """The identity-laden Senso markdown must not surface as the card body."""
    _capture_draft_channel(monkeypatch, reply="written as the caller")
    senso = MagicMock()
    senso.get_or_create_content_type.return_value = "ct-1"
    senso.generate_sample.return_value = "job-1"
    senso.poll_until_done.return_value = {
        "status": "completed",
        "result": {
            "raw_markdown": "I am Andre Chuabio, reach me at AC233@Fordham.edu",
            "content_id": "d-1",
        },
    }

    cards = generate_drafts(
        senso=senso,
        purpose=Purpose.CAREER,
        context="ctx",
        session_id="sess_test",
        user_id="qa-user",
        logger=MagicMock(),
    )

    assert cards[0].markdown == "written as the caller"
    assert "Andre Chuabio" not in cards[0].markdown


def test_sender_profile_reaches_the_draft_call(monkeypatch):
    """The caller's profile threads through to every channel's LLM call."""
    calls = _capture_draft_channel(monkeypatch)
    profile = {"name": "QA Tester", "title": "QA Engineer"}

    generate_drafts(
        senso=None,
        purpose=Purpose.NETWORK,
        context="ctx",
        session_id="sess_test",
        user_id="qa-user",
        logger=None,
        sender_profile=profile,
    )

    assert len(calls) == 2
    assert all(c["sender_profile"] == profile for c in calls)


def test_generate_drafts_continues_when_one_channel_fails(monkeypatch):
    _capture_draft_channel(monkeypatch)
    senso = MagicMock()
    senso.get_or_create_content_type.side_effect = lambda name, cfg: f"ct-{name}"

    def gen(content_type_id, context):
        if "x_thread" in content_type_id:
            raise RuntimeError("simulated failure")
        return f"job-{content_type_id}"

    senso.generate_sample.side_effect = gen
    senso.poll_until_done.side_effect = lambda jid, **kw: {
        "status": "completed",
        "result": {"raw_markdown": f"tone sample for {jid}", "content_id": "d"},
    }

    cards = generate_drafts(
        senso=senso,
        purpose=Purpose.BRAND,
        context="ctx",
        session_id="sess_test",
        user_id="andre",
        logger=MagicMock(),
    )

    assert len(cards) == 2
    assert cards[0].error is None
    assert cards[1].error is not None
    assert cards[1].markdown == ""


def test_generate_drafts_calls_logger_for_each_success(monkeypatch):
    _capture_draft_channel(monkeypatch)
    senso = MagicMock()
    senso.get_or_create_content_type.side_effect = lambda name, cfg: f"ct-{name}"
    senso.generate_sample.side_effect = lambda content_type_id, context: f"job-{content_type_id}"
    senso.poll_until_done.side_effect = lambda jid, **kw: {
        "status": "completed",
        "result": {"raw_markdown": "x", "content_id": "d"},
    }
    logger = MagicMock()

    generate_drafts(
        senso=senso,
        purpose=Purpose.SERVICE,
        context="ctx",
        session_id="sess_test",
        user_id="andre",
        logger=logger,
    )
    # SERVICE has 3 channels -> 3 log_generate calls.
    assert logger.log_generate.call_count == 3
