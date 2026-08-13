"""One Gateway LLM call turning a profile, repo bundles and chosen evidence
into a structured SitePack.

The model writes prose and picks a palette and a layout. It never writes
markup: site_render.py owns every tag on the page, and everything this call
returns is escaped before it gets there.
"""

from __future__ import annotations

import json
import re
from typing import Any

from paperpilot import trace
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.site_models import Layout, Palette, SitePack

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_PALETTES = ", ".join(p.value for p in Palette)
_LAYOUTS = ", ".join(layout.value for layout in Layout)

SYSTEM_PROMPT = f"""You are a senior engineer writing the copy for a developer's personal portfolio site.

You will receive a profile, zero or more repository bundles, and zero or more pieces of recognition the person has explicitly chosen to publish. Write the site's prose.

Rules:

- Write in the person's stated voice and tone when one is given.
- One project entry per repository bundle. The blurb says what the project does and why it is interesting, in one or two sentences, grounded in the code you were shown. Do not invent features the bundle does not evidence.
- `tech` lists the real technologies visible in the bundle. `highlights` are at most three short factual bullets.
- Keep `about` to two or three short paragraphs.
- Recognition entries are rewritten for a public audience: no case numbers, no immigration or petition wording, no personal contact details.
- You are writing text, never HTML. Do not emit tags, markdown, or scripts. Anything that looks like markup is escaped and shown to the reader literally.

Pick a theme that suits the person. `palette` must be one of: {_PALETTES}. `layout` must be one of: {_LAYOUTS}. Anything else falls back to a default.

Output a JSON object matching this schema EXACTLY:

{{
  "name": "Full Name",
  "title": "Their role, short",
  "tagline": "One line under the title.",
  "about": ["paragraph", "paragraph"],
  "projects": [
    {{"title": "Name", "repo_url": "https://github.com/owner/name", "blurb": "...", "tech": ["Python"], "highlights": ["..."]}}
  ],
  "evidence": [
    {{"criterion": "awards", "title": "...", "blurb": "...", "url": "https://...", "date": "2026-03-01"}}
  ],
  "links": {{"github": "", "linkedin": "", "scholar": "", "site": ""}},
  "theme": {{"palette": "slate", "layout": "stack"}}
}}

Return only the JSON object."""


def build_prompt(
    profile: dict[str, str],
    repos: list[tuple[str, str]],
    evidence: list[dict[str, str]],
) -> str:
    """Assemble the user-side message. Pure, so it tests without a client."""
    blocks = ["## Profile", json.dumps(profile, indent=2)]
    if repos:
        blocks.append("## Repositories")
        for label, bundle in repos:
            blocks.append(f"### {label}\n{bundle}")
    if evidence:
        blocks.append("## Recognition the person chose to publish")
        blocks.append(json.dumps(evidence, indent=2))
    return "\n\n".join(blocks)


def build_pack(
    *,
    profile: dict[str, str],
    repos: list[tuple[str, str]],
    evidence: list[dict[str, str]],
    session_id: str,
) -> SitePack:
    """Single LLM call to a structured SitePack. Traced through trace.step."""
    model = DEFAULTS["ingest"]
    with trace.step(
        session_id,
        "site.extract",
        repos=len(repos),
        evidence=len(evidence),
        model=model,
    ) as ctx:
        client = get_client()
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(profile, repos, evidence)},
            ],
            max_tokens=8000,
            temperature=0.4,
        )
        raw = completion.choices[0].message.content or "{}"
        ctx["finish_reason"] = completion.choices[0].finish_reason
        if completion.usage:
            ctx["tokens_in"] = completion.usage.prompt_tokens
            ctx["tokens_out"] = completion.usage.completion_tokens
        try:
            parsed: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(raw)
            if match is None:
                ctx["error"] = "json_extract_failed"
                ctx["raw_preview"] = raw[:400]
                raise
            parsed = json.loads(match.group(0))
            ctx["json_recovered"] = True
        pack = SitePack.model_validate(parsed)
        ctx["projects"] = len(pack.projects)
    return pack
