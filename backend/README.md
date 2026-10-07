# Gavel Backend

FastAPI backend for **Gavel**, the AI small-claims court (hackathon MVP).

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --port 8000
```

No API key is required: with no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set,
the backend uses the deterministic `ScriptedProvider` (offline demo engine).

Provider selection at startup (logged): **Anthropic > OpenAI > Scripted**.
- `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_MODEL`, default `claude-sonnet-4-20250514`)
- `OPENAI_API_KEY` (+ optional `OPENAI_MODEL`, default `gpt-4o-mini`)

## REST contract

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | `{"ok": true, "provider": "<name>"}` |
| POST | `/api/disputes` | Create a dispute → `{"id": ...}` |
| POST | `/api/disputes/{id}/deliberate` | Run deliberation (synchronous), returns the verdict object |
| GET | `/api/disputes/{id}` | Full dispute incl. `transcript[]` and `verdict` |
| GET | `/api/disputes` | List disputes: `id`, `title`, `status` |
| GET | `/api/disputes/{id}/stream` | SSE replay of the stored transcript |

`POST /api/disputes` body:

```json
{
  "claimant_name": "Maya Chen",
  "respondent_name": "Brightline Media Ltd.",
  "claim_title": "Unpaid $500 invoice for logo design package",
  "claim_description": "...",
  "amount_usdc": 500,
  "claimant_evidence": ["..."],
  "respondent_evidence": ["..."]
}
```

Verdict shape:

```json
{
  "winner": "claimant",
  "reasoning": "...",
  "transcript_hash": "sha256-of-canonical-transcript",
  "awarded_amount_usdc": 500,
  "votes": [{"persona": "...", "vote": "claimant", "justification": "..."}]
}
```

SSE events are shaped `{"type": "opening|rebuttal|closing|vote|verdict",
"persona": str|null, "round": int, "text": str}`.

## Demo

```bash
curl -s -X POST localhost:8000/api/disputes \
  -H 'Content-Type: application/json' -d @demo_dispute.json
# → {"id": "<id>"}
curl -s -X POST localhost:8000/api/disputes/<id>/deliberate | python3 -m json.tool
curl -s localhost:8000/api/disputes/<id>/stream   # SSE replay
```

## Notes

- **In-memory store**: disputes live in a process-local dict. Restarting the
  server wipes them. Intentional for the MVP.
- `transcript_hash` = sha256 over canonical JSON of the transcript entries
  (everything up to, not including, the verdict frame).
- The ScriptedProvider votes deterministically from heuristic case analysis;
  the Precedent Analyst is the designed swing/dissent vote.
