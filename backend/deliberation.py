"""Gavel deliberation engine.

Three personas debate a dispute over three rounds:
  Round 1 -- opening statements (each persona, in order)
  Round 2 -- rebuttals (each persona responds to the others' openings)
  Round 3 -- closing positions + individual vote with one-line justification

Then a verdict synthesis: majority vote wins, with a consolidated reasoning
paragraph weaving the decisive arguments. ``transcript_hash`` is the sha256 of
the canonical JSON of the transcript.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

from providers import LLMProvider

log = logging.getLogger("gavel.deliberation")

PERSONAS = [
    {
        "id": "textualist",
        "name": "The Textualist",
        "system": (
            "You are The Textualist, an AI adjudicator on a small-claims panel. "
            "Your creed: the contract's text is the entire agreement. Parties are "
            "bound by what they wrote, not what they meant, felt, or assumed. "
            "Apply the four-corners rule: payment is owed exactly when the written "
            "terms say it is owed. No implied conditions, no rescue by fairness, no "
            "rewriting the deal after the fact. Aesthetic dissatisfaction is legally "
            "irrelevant unless the agreement makes it a condition of payment. "
            "Late-arising justifications cannot retroactively amend the contract. "
            "Write with clipped precision, cite the agreement's language, and "
            "dismiss extra-contractual appeals -- including your colleagues' -- "
            "as beside the point."
        ),
    },
    {
        "id": "consumer_advocate",
        "name": "The Consumer Advocate",
        "system": (
            "You are The Consumer Advocate, an AI adjudicator on a small-claims panel. "
            "Your creed: law serves people, and disputes are never fought on a level "
            "field. Watch for power imbalance -- the solo freelancer against the "
            "company, the individual against the institution. Enforce the duty of "
            "good faith: objections must be raised promptly and honestly, not "
            "warehoused until the invoice arrives. A party that accepts the benefit "
            "of work and only then invents a subjective reason not to pay is acting "
            "in bad faith, and you will say so plainly. Read contractual silence "
            "against the stronger party. Write with moral clarity and controlled "
            "indignation; name the tactics you see."
        ),
    },
    {
        "id": "precedent_analyst",
        "name": "The Precedent Analyst",
        "system": (
            "You are The Precedent Analyst, an AI adjudicator on a small-claims panel. "
            "Your creed: no case is decided alone -- decide by analogy. Reach for "
            "how similar disputes are actually resolved: industry practice, the "
            "customs of the trade, analogous rulings, governing principles. In "
            "creative work, the distinction between receipt and acceptance, and the "
            "custom of revision rounds for subjective deliverables, matters more "
            "than abstract doctrine. Custom interprets open terms; it is how real "
            "parties understand their deals. You are the panel's swing vote and you "
            "know it: do not be afraid to dissent when practice points the other "
            "way. Write like a scholar of the trade, with 'consider the analogous "
            "case' as your instinct."
        ),
    },
]

_VOTE_RE = re.compile(r"VOTE:\s*(claimant|respondent)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Transcript / verdict structures
# ---------------------------------------------------------------------------

def _scripted_context(
    persona_id: str,
    phase: str,
    round_no: int,
    dispute: dict,
    prior: dict | None = None,
    votes: list[dict] | None = None,
) -> str:
    """JSON block the ScriptedProvider uses to render deterministically."""
    return (
        "[SCRIPTED_CONTEXT]"
        + json.dumps(
            {
                "persona_id": persona_id,
                "phase": phase,
                "round": round_no,
                "dispute": dispute,
                "prior": prior or {},
                "votes": votes or [],
            },
            ensure_ascii=False,
        )
        + "[/SCRIPTED_CONTEXT]"
    )


def _dispute_brief(dispute: dict) -> str:
    parts = [
        f"CLAIM: {dispute.get('claim_title', '')}",
        f"Claimant: {dispute.get('claimant_name', '')}",
        f"Respondent: {dispute.get('respondent_name', '')}",
        f"Amount claimed: {dispute.get('amount_usdc')} USDC",
        f"Description: {dispute.get('claim_description', '')}",
        "Claimant's evidence:",
    ]
    for e in dispute.get("claimant_evidence") or []:
        parts.append(f"  - {e}")
    parts.append("Respondent's evidence:")
    for e in dispute.get("respondent_evidence") or []:
        parts.append(f"  - {e}")
    return "\n".join(parts)


def canonical_transcript(entries: list[dict]) -> str:
    """Canonical JSON encoding of the transcript (stable key order)."""
    slim = [
        {
            "type": e["type"],
            "persona": e.get("persona"),
            "round": e.get("round"),
            "text": e["text"],
        }
        for e in entries
    ]
    return json.dumps(slim, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def transcript_hash(entries: list[dict]) -> str:
    return hashlib.sha256(canonical_transcript(entries).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deliberation flow
# ---------------------------------------------------------------------------

def _ask(provider: LLMProvider, persona: dict, instruction: str,
         dispute: dict, phase: str, round_no: int,
         prior: dict | None = None, votes: list[dict] | None = None) -> str:
    user_content = (
        f"{instruction}\n\n"
        f"THE DISPUTE:\n{_dispute_brief(dispute)}\n\n"
        f"{_scripted_context(persona['id'], phase, round_no, dispute, prior, votes)}"
    )
    return provider.chat(
        persona["system"], [{"role": "user", "content": user_content}]
    ).strip()


def _parse_vote(text: str) -> str:
    m = _VOTE_RE.search(text)
    if m:
        return m.group(1).lower()
    low = text.lower()
    if "respondent" in low and "claimant" not in low:
        return "respondent"
    return "claimant"


def _extract_justification(text: str) -> str:
    m = re.search(r"JUSTIFICATION:\s*(.+)", text, re.IGNORECASE | re.S)
    if m:
        return m.group(1).strip().split("\n")[0][:300]
    # Fallback: first sentence.
    return text.split(".")[0].strip()[:300]


def deliberate(dispute: dict, provider: LLMProvider) -> tuple[list[dict], dict]:
    """Run the full three-round deliberation.

    Returns (transcript_entries, verdict). ``verdict`` has keys:
    winner ("claimant"|"respondent"), reasoning, transcript_hash,
    awarded_amount_usdc, votes (per-persona detail).
    """
    transcript: list[dict] = []

    # -- Round 1: opening statements -------------------------------------
    openings: dict[str, str] = {}
    for persona in PERSONAS:
        text = _ask(
            provider, persona,
            "ROUND 1 -- OPENING STATEMENT. State your reading of this dispute "
            "from your adjudicative philosophy. Ground your argument in the "
            "actual evidence. 2-4 short paragraphs.",
            dispute, phase="opening", round_no=1,
        )
        openings[persona["id"]] = text
        transcript.append({
            "type": "opening", "persona": persona["name"], "round": 1, "text": text,
        })
        log.info("opening done: %s", persona["name"])

    # -- Round 2: rebuttals ----------------------------------------------
    for persona in PERSONAS:
        others = {
            p["name"]: openings[p["id"]]
            for p in PERSONAS
            if p["id"] != persona["id"]
        }
        rebuttal_brief = "\n\n".join(
            f"--- {name}'s opening ---\n{txt}" for name, txt in others.items()
        )
        text = _ask(
            provider, persona,
            "ROUND 2 -- REBUTTAL. Respond directly to the other two personas' "
            "opening statements below. Attack their reasoning from your "
            "philosophy; do not merely restate your opening.\n\n"
            f"{rebuttal_brief}",
            dispute, phase="rebuttal", round_no=2, prior=openings,
        )
        transcript.append({
            "type": "rebuttal", "persona": persona["name"], "round": 2, "text": text,
        })
        log.info("rebuttal done: %s", persona["name"])

    # -- Round 3: closings + votes ----------------------------------------
    votes: list[dict] = []
    for persona in PERSONAS:
        closing = _ask(
            provider, persona,
            "ROUND 3 -- CLOSING POSITION. Give your final position in 2-3 short "
            "paragraphs. Hold your ground or concede where beaten, but state "
            "plainly which side you favor.",
            dispute, phase="closing", round_no=3, prior=openings,
        )
        transcript.append({
            "type": "closing", "persona": persona["name"], "round": 3, "text": closing,
        })
        vote_text = _ask(
            provider, persona,
            "CAST YOUR VOTE. Reply in exactly this format:\n"
            "VOTE: claimant   (or: VOTE: respondent)\n"
            "JUSTIFICATION: <one sentence>",
            dispute, phase="vote", round_no=3,
        )
        vote = _parse_vote(vote_text)
        justification = _extract_justification(vote_text)
        votes.append({
            "persona": persona["name"], "vote": vote, "justification": justification,
        })
        transcript.append({
            "type": "vote", "persona": persona["name"], "round": 3,
            "text": f"VOTE: {vote} -- {justification}",
        })
        log.info("vote done: %s -> %s", persona["name"], vote)

    # -- Verdict synthesis --------------------------------------------------
    counts = {"claimant": 0, "respondent": 0}
    for v in votes:
        counts[v["vote"]] += 1
    winner = "claimant" if counts["claimant"] >= 2 else "respondent"

    reasoning = _ask(
        provider, PERSONAS[0],
        "VERDICT SYNTHESIS. You are writing the panel's majority opinion. "
        "The votes are: "
        + "; ".join(f"{v['persona']}: {v['vote']}" for v in votes)
        + ". Write one consolidated reasoning paragraph (5-8 sentences) that "
        "weaves the decisive arguments of the majority side and answers the "
        "dissent. Do not vote again; the majority is decided.",
        dispute, phase="synthesis", round_no=3, votes=votes,
    )

    # The transcript hash covers everything up to (not including) the verdict.
    thash = transcript_hash(transcript)

    transcript.append({
        "type": "verdict", "persona": None, "round": 0, "text": reasoning,
    })

    amount = dispute.get("amount_usdc") or 0
    verdict = {
        "winner": winner,
        "reasoning": reasoning,
        "transcript_hash": thash,
        "awarded_amount_usdc": amount if winner == "claimant" else 0,
        "votes": votes,
    }
    return transcript, verdict
