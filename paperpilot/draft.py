"""Paper drafting with citation-gated related work.

Section-by-section streaming via Claude through the Gateway. Related work
gets the citation gate: model sees only approved arxiv candidate IDs and
can only cite those. Post-hoc regex strip removes any unsanctioned IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Generator, Iterable

import tiktoken

from paperpilot import senso_client, trace
from paperpilot.arxiv_lookup import (
    PaperMeta,
    candidates_from_clickhouse,
    lookup_paper,
)
from paperpilot.cfp_match import VenueMatch
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.llm_ingest import ResearchSummary


# Per-million-token USD prices used for fallback cost estimation when the
# Gateway does not propagate usage on streamed Anthropic responses. Numbers
# match public list pricing close enough for a demo pill -- judges see a
# nonzero, plausible figure rather than $0.00. Real `usage.cost` wins when
# the Gateway returns it.
_PRICE_PER_MTOK = {
    "anthropic/claude-sonnet-4-6":  (3.00, 15.00),
    "anthropic/claude-haiku-4-5":   (1.00,  5.00),
    "anthropic/claude-sonnet":      (3.00, 15.00),  # generic fallback
    "google/gemini-2.5-flash":      (0.30,  2.50),
}


def _tok_count(text: str) -> int:
    """Rough token count using cl100k_base; close enough for billing pills."""
    if not text:
        return 0
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001 -- never break the draft for a counter
        # 4 chars-per-token is the standard rough fallback.
        return max(1, len(text) // 4)


def _estimate_cost(model: str, t_in: int, t_out: int) -> float:
    """Estimate USD cost from token counts when Gateway omits usage.cost."""
    # Prefix-match so "anthropic/claude-sonnet-4-6-20251024" still picks up
    # the sonnet rate even if the exact suffix isn't in the table.
    rate = None
    for prefix, prices in _PRICE_PER_MTOK.items():
        if model.startswith(prefix):
            rate = prices
            break
    if rate is None:
        return 0.0
    in_rate, out_rate = rate
    return (t_in / 1_000_000) * in_rate + (t_out / 1_000_000) * out_rate


SECTIONS = ("abstract", "intro", "related", "method")


CITATION_RE = re.compile(r"\[arxiv:([^\]]+)\]")
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


def _norm_arxiv_id(aid: str) -> str:
    """Strip trailing version suffix and whitespace; lowercase for comparison."""
    return _VERSION_SUFFIX_RE.sub("", aid.strip().lower())


@dataclass
class DraftSection:
    name: str
    text: str
    citations: list[PaperMeta] = field(default_factory=list)
    stripped_ids: list[str] = field(default_factory=list)


def _section_prompt(
    section: str,
    summary: ResearchSummary,
    venue: VenueMatch,
    candidates: Iterable[PaperMeta] | None = None,
) -> tuple[str, str]:
    """Build (system, user) prompt for a section."""
    common_user = (
        f"Repository research summary:\n"
        f"- Problem: {summary.problem}\n"
        f"- Contribution: {summary.contribution}\n"
        f"- Method: {summary.method}\n"
        f"- Results: {summary.results}\n"
        f"- Limitations: {summary.limitations}\n"
        f"- Keywords: {', '.join(summary.keywords)}\n\n"
        f"Target venue: {venue.name} ({venue.scope})\n"
    )

    if section == "abstract":
        sys = (
            "You write tight, academically-toned paper abstracts (150-200 words). "
            "Single paragraph. No citations. No headers. Match the venue's tone."
        )
        return sys, common_user + "\nWrite the abstract."

    if section == "intro":
        sys = (
            "You write academic paper introductions (~350 words). Three paragraphs: "
            "problem motivation, limitations of prior work in general terms, and a "
            "preview of the contribution. Do not cite specific papers here -- save "
            "those for the related-work section. Match the venue's tone."
        )
        return sys, common_user + "\nWrite the introduction."

    if section == "related":
        cand_list = list(candidates or [])
        cand_block = "\n".join(
            f"- [arxiv:{c.id}] {c.title} ({c.year}). {c.abstract[:200]}..."
            for c in cand_list
        )
        sys = (
            "You write related-work sections for ML/CS papers. Cite work using "
            "inline markers like [arxiv:2401.12345]. Cite ONLY papers from the "
            "approved candidate list provided in the user message -- never invent "
            "arxiv IDs. Cite at least 4 distinct candidates, group by theme, "
            "~300 words. Match the venue's tone."
        )
        user = (
            common_user
            + "\nApproved candidates (cite ONLY these):\n"
            + cand_block
            + "\n\nWrite the related-work section."
        )
        return sys, user

    if section == "method":
        sys = (
            "You write the opening paragraph of a paper's method section (~200 "
            "words). Describe the high-level approach grounded in the repository "
            "summary -- no implementation details that aren't supported. No "
            "citations. Match the venue's tone."
        )
        return sys, common_user + "\nWrite the opening paragraph of the method section."

    raise ValueError(f"Unknown section: {section}")


def _strip_unapproved(text: str, approved_ids: set[str]) -> tuple[str, list[str]]:
    """Remove any [arxiv:id] markers not in approved_ids; return cleaned text + dropped ids.

    Comparison normalizes both sides (lowercase + strip vN suffix) so that
    `2401.12345v2` matches an approved `2401.12345`.
    """
    approved_norm = {_norm_arxiv_id(a) for a in approved_ids}
    dropped: list[str] = []

    def sub(match: re.Match[str]) -> str:
        aid = match.group(1).strip()
        if _norm_arxiv_id(aid) in approved_norm:
            return f"[arxiv:{aid}]"
        dropped.append(aid)
        return ""

    return CITATION_RE.sub(sub, text), dropped


def _senso_tone_block(
    section: str, summary: ResearchSummary, venue: VenueMatch, session_id: str
) -> str:
    """Pull 2-3 tone-reference chunks from Senso for this section + venue.

    Returns a formatted block to prepend to the user_prompt, or empty string
    when Senso isn't configured / KB returns nothing. Best-effort.
    """
    if not senso_client.is_configured():
        return ""
    keywords = ", ".join(summary.keywords[:4]) if summary.keywords else section
    query = f"{venue.name} {section} academic paper tone {keywords}"
    chunks = senso_client.search_context(query, session_id, max_results=3)
    if not chunks:
        return ""
    block_lines = [
        "Reference tone exemplars (from a curated Senso KB of accepted",
        f"papers similar to {venue.name}; match this register, do NOT quote).",
        "Identity guard: any names, biographies, emails, affiliations,",
        "credentials, or links inside these exemplars belong to other people.",
        "Never present them as the author's identity, contact details, or",
        "achievements, and never copy facts from them into the paper:",
    ]
    for c in chunks[:3]:
        snippet = c.text[:280].strip().replace("\n", " ")
        block_lines.append(f"- ({c.source}) {snippet}")
    return "\n".join(block_lines) + "\n\n"


def draft_section(
    section: str,
    summary: ResearchSummary,
    venue: VenueMatch,
    session_id: str,
    candidates: list[PaperMeta] | None = None,
) -> Generator[str, None, DraftSection]:
    """Stream a paper section, yielding deltas as they arrive."""
    sys_prompt, user_prompt = _section_prompt(section, summary, venue, candidates)
    # Inject Senso tone reference (no-op when Senso is not configured).
    tone_block = _senso_tone_block(section, summary, venue, session_id)
    if tone_block:
        user_prompt = tone_block + user_prompt
    model = DEFAULTS["draft"]

    with trace.step(
        session_id,
        f"draft.{section}",
        model=model,
        venue=venue.name,
        candidate_count=len(candidates) if candidates else 0,
    ) as ctx:
        client = get_client()
        # Cache the user prompt for Anthropic so repeated section calls reuse
        # the shared `common_user` block (Vercel AI Gateway honors the
        # OpenAI-compat extra_body cache_control passthrough for Anthropic).
        is_anthropic = model.startswith("anthropic/")
        user_message: dict[str, Any] = {"role": "user", "content": user_prompt}
        if is_anthropic:
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                user_message,
            ],
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=900,
            temperature=0.5,
        )
        chunks: list[str] = []
        final_usage = None
        for event in stream:
            if getattr(event, "usage", None):
                # Gateway emits usage in the FINAL chunk (choices=[]).
                final_usage = event.usage
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                chunks.append(delta)
                yield delta
        full_text = "".join(chunks)
        ctx["chars"] = len(full_text)
        if final_usage:
            ctx["tokens_in"] = final_usage.prompt_tokens
            ctx["tokens_out"] = final_usage.completion_tokens
            gw_cost = getattr(final_usage, "cost", None)
            ctx["cost_usd"] = (
                gw_cost
                if gw_cost is not None
                else _estimate_cost(model, ctx["tokens_in"], ctx["tokens_out"])
            )
            ctx["cost_source"] = "gateway" if gw_cost is not None else "estimated"
        else:
            # Vercel AI Gateway streaming for Anthropic does not always emit
            # a final usage chunk. Fall back to tiktoken so the observability
            # pill stays non-zero on every section.
            t_in = _tok_count(sys_prompt) + _tok_count(user_prompt)
            t_out = _tok_count(full_text)
            ctx["tokens_in"] = t_in
            ctx["tokens_out"] = t_out
            ctx["cost_usd"] = _estimate_cost(model, t_in, t_out)
            ctx["cost_source"] = "estimated"

    citations: list[PaperMeta] = []
    stripped: list[str] = []
    if section == "related" and candidates is not None:
        approved = {c.id for c in candidates}
        full_text, stripped = _strip_unapproved(full_text, approved)
        # After strip, every remaining citation is an approved candidate
        # already loaded in arxiv_lookup._CACHE -- avoid a flaky external
        # arxiv API call by going straight to the cache when possible.
        candidate_by_norm = {_norm_arxiv_id(c.id): c for c in candidates}
        for aid in set(CITATION_RE.findall(full_text)):
            meta = candidate_by_norm.get(_norm_arxiv_id(aid)) or lookup_paper(aid)
            if meta is not None:
                citations.append(meta)

    return DraftSection(
        name=section, text=full_text, citations=citations, stripped_ids=stripped
    )


def draft_paper(
    summary: ResearchSummary,
    venue: VenueMatch,
    session_id: str,
) -> Generator[tuple[str, str], None, dict[str, DraftSection]]:
    """Stream all sections in order. Yields (section_name, delta) tuples.

    Returns the assembled dict[section_name -> DraftSection] at the end.
    """
    summary_text = (
        f"{summary.problem} {summary.contribution} {summary.method} "
        f"Keywords: {', '.join(summary.keywords)}"
    )
    candidates = candidates_from_clickhouse(summary_text, session_id, limit=10)
    out: dict[str, DraftSection] = {}
    for section in SECTIONS:
        gen = draft_section(
            section,
            summary,
            venue,
            session_id,
            candidates if section == "related" else None,
        )
        try:
            while True:
                delta = next(gen)
                yield section, delta
        except StopIteration as stop:
            out[section] = stop.value
    return out
