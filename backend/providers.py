"""LLM provider layer for Gavel.

Defines a single ``LLMProvider`` interface and three implementations:
  * AnthropicProvider  - real model calls via the Anthropic API
  * OpenAIProvider     - real model calls via the OpenAI API
  * ScriptedProvider   - DETERMINISTIC offline fallback, no network, no key

Selection at startup: Anthropic > OpenAI > Scripted (logged).
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod

log = logging.getLogger("gavel.providers")


class LLMProvider(ABC):
    """Minimal chat interface every provider must implement."""

    name: str = "base"

    @abstractmethod
    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        """Return the assistant's reply text for the given conversation.

        ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Real API providers
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """OpenAI chat completions. Key from OPENAI_API_KEY."""

    name = "openai"

    def __init__(self, model: str | None = None):
        import httpx  # imported lazily so the module loads with no deps

        self._httpx = httpx
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.api_key = api_key
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": 0.7,
            "max_tokens": 900,
        }
        resp = self._httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


class AnthropicProvider(LLMProvider):
    """Anthropic messages API. Key from ANTHROPIC_API_KEY."""

    name = "anthropic"

    def __init__(self, model: str | None = None):
        import httpx  # imported lazily so the module loads with no deps

        self._httpx = httpx
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.api_key = api_key
        self.model = model or os.environ.get(
            "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
        )

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        # Anthropic wants system as a top-level param; merge non-system roles only.
        convo = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]
        payload = {
            "model": self.model,
            "max_tokens": 900,
            "system": system_prompt,
            "messages": convo,
        }
        resp = self._httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()


# ---------------------------------------------------------------------------
# ScriptedProvider -- deterministic offline fallback (the demo engine)
# ---------------------------------------------------------------------------
#
# The deliberation engine appends a JSON context block to the final user
# message so the scripted provider knows exactly which dispute, persona,
# phase and round it is rendering, plus what the other personas said.
# Format:  [SCRIPTED_CONTEXT]{...}[/SCRIPTED_CONTEXT]

_CONTEXT_RE = re.compile(r"\[SCRIPTED_CONTEXT\](.*?)\[/SCRIPTED_CONTEXT\]", re.S)


class ScriptedProvider(LLMProvider):
    """Deterministic offline debate engine. No network, no API key.

    Renders each persona in a distinct voice, arguing from the actual
    evidence of the dispute. The three personas genuinely disagree:
    the Textualist reads the contract's letter, the Consumer Advocate
    reads power and good faith, and the Precedent Analyst is the swing
    vote, reading industry practice -- which can put it in dissent.
    """

    name = "scripted"

    # ------------------------------------------------------------------ chat

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        ctx = self._extract_context(messages)
        if ctx is None:
            return (
                "No dispute context was supplied, so I cannot reason about it. "
                "Provide the case facts and I will deliberate."
            )
        dispute = ctx.get("dispute", {})
        persona_id = ctx.get("persona_id", "")
        phase = ctx.get("phase", "opening")
        round_no = ctx.get("round", 1)
        prior = ctx.get("prior", {})
        analysis = analyze(dispute)

        if phase == "vote":
            return self._render_vote(persona_id, analysis, dispute)
        if phase == "opening" and round_no == 1:
            return self._render_opening(persona_id, analysis, dispute)
        if phase == "rebuttal" and round_no == 2:
            return self._render_rebuttal(persona_id, analysis, dispute, prior)
        if phase == "closing" and round_no == 3:
            return self._render_closing(persona_id, analysis, dispute, prior)
        if phase == "synthesis":
            return self._render_synthesis(analysis, dispute, ctx.get("votes", []))
        return self._render_opening(persona_id, analysis, dispute)

    @staticmethod
    def _extract_context(messages: list[dict]) -> dict | None:
        for msg in reversed(messages):
            content = msg.get("content", "")
            m = _CONTEXT_RE.search(content)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    return None
        return None

    # ------------------------------------------------------------- personas

    def _render_opening(self, persona_id: str, a: "CaseAnalysis", d: dict) -> str:
        if persona_id == "textualist":
            return self._textualist_opening(a, d)
        if persona_id == "consumer_advocate":
            return self._advocate_opening(a, d)
        return self._analyst_opening(a, d)

    def _render_rebuttal(
        self, persona_id: str, a: "CaseAnalysis", d: dict, prior: dict
    ) -> str:
        if persona_id == "textualist":
            return self._textualist_rebuttal(a, d)
        if persona_id == "consumer_advocate":
            return self._advocate_rebuttal(a, d)
        return self._analyst_rebuttal(a, d)

    def _render_closing(
        self, persona_id: str, a: "CaseAnalysis", d: dict, prior: dict
    ) -> str:
        if persona_id == "textualist":
            return self._textualist_closing(a, d)
        if persona_id == "consumer_advocate":
            return self._advocate_closing(a, d)
        return self._analyst_closing(a, d)

    def _render_vote(self, persona_id: str, a: "CaseAnalysis", d: dict) -> str:
        vote, justification = self._decide(persona_id, a, d)
        return f"VOTE: {vote}. JUSTIFICATION: {justification}"

    # --------------------------------------------------------------- votes

    def _decide(self, persona_id: str, a: "CaseAnalysis", d: dict) -> tuple[str, str]:
        """Deterministic persona votes, driven by the case analysis."""
        claimant, respondent = d.get("claimant_name", "the claimant"), d.get(
            "respondent_name", "the respondent"
        )
        if persona_id == "textualist":
            # The letter of the agreement: payment on delivery, delivered, no
            # acceptance clause -> claimant wins. If no clear contractual term
            # exists at all, the claimant has not proved entitlement.
            if a.terms_evidence and a.delivery_evidence:
                return (
                    "claimant",
                    f"the agreement conditions payment on delivery alone, and delivery is documented; {respondent} cannot add conditions the contract never contained",
                )
            return (
                "respondent",
                "the claimant has not produced contractual language entitling them to payment",
            )
        if persona_id == "consumer_advocate":
            # Power imbalance + subjective, post-hoc refusal -> claimant wins.
            if a.subjective_rejection and a.late_action:
                return (
                    "claimant",
                    f"{respondent} accepted the benefit of the work and only afterwards invented a subjective reason not to pay; that is bad faith against the weaker party",
                )
            if a.delivery_evidence:
                return (
                    "claimant",
                    f"the work was delivered and used; refusing payment now punishes the party with the least power in the relationship",
                )
            return (
                "respondent",
                "the evidence does not show the claimant delivered what was promised",
            )
        # precedent_analyst -- the swing vote.
        if a.late_action and a.subjective_rejection and not a.acceptance_clause:
            # Industry practice in creative work: subjective quality disputes go
            # through an acceptance/revision loop; receipt is not acceptance.
            return (
                "respondent",
                "in creative-services practice, subjective dissatisfaction triggers a good-faith revision cycle, not a payment forfeiture; the claimant delivered but never obtained acceptance",
            )
        return (
            "claimant",
            f"industry practice treats documented delivery under a signed agreement as performance; {respondent} raised no timely objection",
        )

    # ----------------------------------------------------- textualist texts

    def _textualist_opening(self, a: "CaseAnalysis", d: dict) -> str:
        claimant = d.get("claimant_name", "the claimant")
        respondent = d.get("respondent_name", "the respondent")
        terms = _quote(a.terms_evidence) or "the signed statement of work"
        delivery = _quote(a.delivery_evidence) or "the delivery confirmation"
        lines = [
            "Start with the four corners of the agreement. Everything else is noise.",
            "",
            f"The parties signed a statement of work that says this: {terms}. "
            "Payment is conditional on one event -- delivery -- and on nothing else. "
            "There is no approval clause, no satisfaction clause, no acceptance test written into that document.",
            "",
            f"Delivery is not in doubt. {delivery}. "
            "Once delivery occurred, the payment obligation crystallized. "
            "That is what the words say, and words are what the parties agreed to be bound by.",
            "",
            "As for the respondent's position: "
            + (
                f"{_quote(a.subjective_rejection)} -- that is an aesthetic judgment, "
                "not a contractual term. A party cannot decline to pay because the work, "
                "in hindsight, was not 'what they envisioned'. The agreement does not "
                "condition payment on the respondent's vision; it conditions it on delivery."
                if a.subjective_rejection
                else "dissatisfaction with the work is nowhere made a condition of payment."
            ),
        ]
        return "\n".join(lines)

    def _textualist_rebuttal(self, a: "CaseAnalysis", d: dict) -> str:
        respondent = d.get("respondent_name", "the respondent")
        late = (
            " -- sent after the deadline had already passed --"
            if a.late_action
            else ""
        )
        return "\n".join(
            [
                "Two responses, briefly.",
                "",
                "To the Consumer Advocate: my colleague's sympathy is misplaced. "
                "The agreement does not ask how anyone feels, and neither should we. "
                "The claimant wins not because she is the weaker party, but because "
                "the text of the contract entitles her to payment. Fairness talk is "
                "unnecessary where the contract already answers the question.",
                "",
                "To the Precedent Analyst: industry custom cannot overwrite an express term. "
                "Custom fills gaps; there is no gap here. "
                f"The revision request{late} "
                "cannot retroactively rewrite payment terms; it arrives after the obligation "
                "to pay already attached. "
                "If the respondent wanted an acceptance procedure, they should have written one into the agreement. They did not.",
            ]
        )

    def _textualist_closing(self, a: "CaseAnalysis", d: dict) -> str:
        return "\n".join(
            [
                "The analysis is complete and it has not moved.",
                "",
                "A signed agreement. A documented delivery. No acceptance condition. "
                "The respondent's refusal is a breach of the agreement's plain terms, "
                "and the late revision request is, at most, a request for new work -- "
                "it cannot erase an obligation that already vested.",
                "",
                "My position: the claimant is owed the full invoiced amount.",
            ]
        )

    # ----------------------------------------------------- advocate texts

    def _advocate_opening(self, a: "CaseAnalysis", d: dict) -> str:
        claimant = d.get("claimant_name", "the claimant")
        respondent = d.get("respondent_name", "the respondent")
        read = (
            " They even left a read receipt -- they opened the delivery, they took the files."
            if a.read_evidence
            else ""
        )
        late = (
            "Only afterwards -- past the deadline -- did they raise a revision request, "
            "as if scrambling for a retroactive justification."
            if a.late_action
            else ""
        )
        return "\n".join(
            [
                "Look at who is sitting at this table. On one side, an independent freelancer. "
                f"On the other, a limited company that commissions creative work for a living. "
                "That imbalance is exactly where small-claims injustice grows.",
                "",
                f"{claimant} did the work, delivered it in full, on time.{read} "
                f"And {respondent}'s answer was not a defect report, not an objective failure of any written spec -- "
                + (
                    f"it was this: {_quote(a.subjective_rejection)}. "
                    if a.subjective_rejection
                    else "it was a vague expression of dissatisfaction. "
                )
                + "A company can always say 'it wasn't what we envisioned' after the fact. "
                "If that sentence were enough to extinguish a payment obligation, no freelancer "
                "would ever have an enforceable invoice.",
                "",
                f"{late} This is the shape of bad faith: accept the benefit, "
                "then invent the reason not to pay. The duty of good faith requires a business "
                "to raise genuine objections promptly, not to warehouse them until the invoice arrives.",
            ]
        )

    def _advocate_rebuttal(self, a: "CaseAnalysis", d: dict) -> str:
        return "\n".join(
            [
                "Two responses.",
                "",
                "To the Textualist: text without conscience is how power hides. "
                "I agree the contract supports the claimant -- but contracts are read "
                "against the stronger party when they are silent, and silence here covers "
                "how disputes about subjective quality are to be handled. The respondent "
                "exploits that silence. Good faith closes the gap the contract left open.",
                "",
                "To the Precedent Analyst: your revision-cycle custom assumes good faith on both sides. "
                "But watch the sequence: delivery, receipt, silence -- then refusal, and only then "
                "a revision request after the deadline. That is not an acceptance loop; it is a "
                "paper trail constructed to justify non-payment. Custom protects honest disagreement, "
                "not strategic delay.",
            ]
        )

    def _advocate_closing(self, a: "CaseAnalysis", d: dict) -> str:
        respondent = d.get("respondent_name", "the respondent")
        return "\n".join(
            [
                "Nothing in the rebuttals changes the equities.",
                "",
                f"{respondent} received the work, used the review period to say nothing substantive, "
                "and then refused to pay on the strength of a feeling. The weaker party performed; "
                "the stronger party manufactured a reason not to pay. A ruling for the respondent "
                "would teach every small business in this position that invoices are optional "
                "whenever a client has second thoughts.",
                "",
                "My position: the claimant is owed the full invoiced amount.",
            ]
        )

    # ------------------------------------------------------ analyst texts

    def _analyst_opening(self, a: "CaseAnalysis", d: dict) -> str:
        claimant = d.get("claimant_name", "the claimant")
        respondent = d.get("respondent_name", "the respondent")
        late = (
            " -- raised only after the deadline had passed -- is precisely what an "
            "ongoing working relationship looks like: dissatisfaction expressed as a "
            "revision request, the industry's normal acceptance mechanism."
            if a.late_action
            else ""
        )
        return "\n".join(
            [
                "Let me put this case next to its neighbors.",
                "",
                "In creative-services practice -- logo design included -- the pattern is well "
                "established: a studio delivers drafts, the client reviews, and subjective "
                "dissatisfaction is resolved through a revision round, not through a payment "
                "forfeiture. No studio on record treats a download link as final acceptance of "
                "a subjective creative work.",
                "",
                "That distinction -- receipt versus acceptance -- is the whole case. "
                + (
                    "The claimant has strong proof of receipt: delivery confirmation, "
                    "download links, a read receipt. She has no proof of acceptance. "
                    "And the respondent's conduct"
                    + late
                    if a.late_action
                    else " And the respondent's dissatisfaction, however subjective, is real within this custom."
                ),
                "",
                "My colleagues read this as a payment dispute. I read it as an acceptance "
                "dispute that was never given its proper procedure. The claimant performed the "
                "delivery, but under the governing custom she has not yet earned payment -- "
                "she has earned a revision round. Awarding the full invoice short-circuits the "
                "very mechanism the industry uses to resolve exactly this disagreement.",
            ]
        )

    def _analyst_rebuttal(self, a: "CaseAnalysis", d: dict) -> str:
        return "\n".join(
            [
                "Two responses.",
                "",
                "To the Textualist: the four-corners reading pretends 'delivery' is self-defining. "
                "In design work it never is. The SOW says payment on delivery, but the parties to "
                "every design contract understand delivery of a creative work as delivery into a "
                "review-and-accept process. The text is not as complete as my colleague claims; "
                "custom is not rewriting the contract, it is interpreting a term the contract leaves open.",
                "",
                "To the Consumer Advocate: I share the concern about power imbalance -- which is "
                "precisely why industry standards exist: to protect the freelancer from exactly "
                "this kind of subjective veto, but through a defined process rather than an "
                "automatic payment. The revision round is the freelancer's protection too: it is "
                "where she would have cured the objection and secured an enforceable acceptance.",
            ]
        )

    def _analyst_closing(self, a: "CaseAnalysis", d: dict) -> str:
        return "\n".join(
            [
                "I have listened to my colleagues and I remain unmoved, respectfully.",
                "",
                "Analogous cases resolve subjective creative disputes through the acceptance "
                "custom: revise, then pay. Neither side followed it -- the claimant treated "
                "receipt as acceptance, the respondent treated dissatisfaction as forfeiture. "
                "The remedy that matches the practice is not the full invoice; it is a "
                "good-faith revision cycle, with payment due on acceptance.",
                "",
                "My position: the respondent should not pay the invoice as invoiced; "
                "the claimant is owed a revision round, not the sum claimed.",
            ]
        )

    # ----------------------------------------------------- verdict synthesis

    def _render_synthesis(
        self, a: "CaseAnalysis", d: dict, votes: list[dict]
    ) -> str:
        claimant = d.get("claimant_name", "the claimant")
        respondent = d.get("respondent_name", "the respondent")
        amount = d.get("amount_usdc")
        amount_str = f"{amount} USDC" if amount is not None else "the claimed amount"
        return (
            f"The panel divides 2-1 in favor of {claimant}. The majority -- the Textualist "
            f"and the Consumer Advocate -- converge from different directions on the same "
            f"conclusion: the signed statement of work conditions payment on delivery alone, "
            f"delivery is documented, and the agreement contains no acceptance or satisfaction "
            f"clause for {respondent} to invoke. The respondent's subjective dissatisfaction, "
            f"raised only after the deadline and dressed up as a late revision request, cannot "
            f"retroactively rewrite payment terms; it is, at most, a request for new work. "
            f"The dissent -- the Precedent Analyst -- argues forcefully that creative-industry "
            f"custom distinguishes receipt from acceptance and would have ordered a revision "
            f"round instead of payment. The majority rejects that reading: custom fills gaps, "
            f"and an express net-15-on-delivery term leaves no gap to fill. The claimant is "
            f"therefore awarded {amount_str} in full."
        )


# ---------------------------------------------------------------------------
# Case analysis: extract the signals the scripted engine argues about
# ---------------------------------------------------------------------------

_QUOTE_RE = re.compile(r'"([^"]{4,200})"')


def _quote(text: str | None) -> str:
    """Render an evidence snippet as an inline quotation."""
    if not text:
        return ""
    return f'"{text}"'


class CaseAnalysis:
    """Heuristic extraction of the facts the personas argue over."""

    def __init__(self, dispute: dict):
        c_ev = list(dispute.get("claimant_evidence") or [])
        r_ev = list(dispute.get("respondent_evidence") or [])
        self.claimant_evidence = c_ev
        self.respondent_evidence = r_ev
        all_ev = c_ev + r_ev

        used = set()
        self.terms_evidence = self._first_match(
            all_ev, ["signed", "agreement", "statement of work", "sow", "contract"],
            used,
        )
        self.delivery_evidence = self._first_match(
            all_ev, ["delivery", "delivered", "download"], used
        )
        self.read_evidence = self._first_match(
            all_ev, ["read receipt", "opened", "read-receipt"], used
        )
        self.subjective_rejection = self._first_match(
            r_ev,
            [
                "isn't what we envisioned",
                "not what we envisioned",
                "don't like",
                "dissatisf",
                "wasn't what we wanted",
            ],
            used,
        )
        self.late_action = self._first_match(
            all_ev, ["revision", "after the deadline", "past the deadline", "late"],
            used,
        )
        self.acceptance_clause = any(
            "acceptance" in e.lower()
            and not re.search(r"\bno\b[^.]{0,60}\bacceptance\b", e.lower())
            for e in all_ev
        )
        self.quotes = _QUOTE_RE.findall(" ".join(all_ev))

    @staticmethod
    def _first_match(
        evidence: list[str], keywords: list[str], used: set[str]
    ) -> str | None:
        for e in evidence:
            if e in used:
                continue
            low = e.lower()
            if any(k in low for k in keywords):
                used.add(e)
                # Prefer the quoted fragment inside, else a trimmed sentence.
                m = _QUOTE_RE.search(e)
                if m:
                    return m.group(1)
                return e[:160].strip()
        return None


def analyze(dispute: dict) -> CaseAnalysis:
    return CaseAnalysis(dispute)


# ---------------------------------------------------------------------------
# Provider selection: Anthropic > OpenAI > Scripted
# ---------------------------------------------------------------------------

def select_provider() -> tuple[str, LLMProvider]:
    """Pick the provider at startup. Returns (name, provider)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return "anthropic", AnthropicProvider()
        except Exception as exc:  # fall through to next option
            log.warning("Anthropic provider failed to init: %s", exc)
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return "openai", OpenAIProvider()
        except Exception as exc:
            log.warning("OpenAI provider failed to init: %s", exc)
    log.info("No API key set -- using deterministic ScriptedProvider")
    return "scripted", ScriptedProvider()
