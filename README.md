# Gavel — the AI small-claims court

Two parties in a dispute lock funds in escrow and pre-agree to binding AI
arbitration. A panel of three AI agents with distinct legal personas debates
the evidence over several rounds in a public transcript, then issues a reasoned
ruling whose hash is anchored on-chain — and the escrow contract auto-pays the
winner.

## The three justices

- **The Textualist** — strict contract wording. What does the agreement *say*?
- **The Consumer Advocate** — fairness and power imbalance. Who had leverage?
- **The Precedent Analyst** — analogous cases and principles. What has been
  decided before in situations like this?

## Repo layout

- `contracts/` — `GavelEscrow.sol` (Solidity, Foundry tests). Escrow +
  binding ruling. Target: Base Sepolia for the demo.
- `backend/` — deliberation engine (Python/FastAPI). Runs the personas through
  debate rounds, streams the transcript, produces the verdict + transcript hash.
- `frontend/` — single-page courtroom app. File a dispute, watch deliberation
  live, see the verdict and on-chain proof.
- `demo/` — scripted end-to-end demo dispute (freelancer vs. client, $500
  unpaid invoice).

## Quick start

```bash
# 1. contracts
cd contracts && forge test

# 2. backend (no LLM key needed for the scripted demo)
cd backend && pip install -r requirements.txt && python app.py

# 3. frontend — open frontend/index.html, or serve it:
cd frontend && python3 -m http.server 8080
```

Without an `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) the backend runs the
deterministic scripted provider — distinct persona voices, real argument —
so the whole demo works offline.

## Status

MVP in progress for BLI Legal Tech Hackathon 2 (deadline Oct 31, 2026).
