import json
from unittest.mock import MagicMock, patch

from paperpilot.site_extract import build_pack, build_prompt


def _completion(payload: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=payload), finish_reason="stop")]
    completion.usage = None
    return completion


def test_prompt_carries_profile_repos_and_evidence():
    prompt = build_prompt(
        {"name": "Andre", "title": "AI Engineer", "about": "Builder"},
        [("AndreChuabio/mediguard", "README: a DLP layer")],
        [{"criterion": "awards", "title": "Hackathon winner", "description": "First"}],
    )
    assert "Andre" in prompt
    assert "AndreChuabio/mediguard" in prompt
    assert "Hackathon winner" in prompt


def test_build_pack_parses_a_clean_json_answer():
    payload = json.dumps(
        {
            "name": "Andre Chuabio",
            "title": "AI Engineer",
            "projects": [{"title": "MediGuard", "repo_url": "https://github.com/x/y"}],
            "theme": {"palette": "ember", "layout": "grid"},
        }
    )
    with patch("paperpilot.site_extract.get_client") as client:
        client.return_value.chat.completions.create.return_value = _completion(payload)
        pack = build_pack(profile={"name": "Andre Chuabio"}, repos=[], evidence=[], session_id="s1")
    assert pack.name == "Andre Chuabio"
    assert pack.projects[0].title == "MediGuard"
    assert pack.theme.palette == "ember"


def test_build_pack_recovers_json_wrapped_in_prose():
    payload = 'Sure, here you go:\n{"name": "Andre"}\nHope that helps.'
    with patch("paperpilot.site_extract.get_client") as client:
        client.return_value.chat.completions.create.return_value = _completion(payload)
        pack = build_pack(profile={"name": "Andre"}, repos=[], evidence=[], session_id="s1")
    assert pack.name == "Andre"
