"""Gavel backend -- FastAPI app.

In-memory dispute store (a plain dict). All state is lost on restart;
that is intentional for the hackathon MVP.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from deliberation import deliberate
from providers import select_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gavel.app")

app = FastAPI(title="Gavel -- AI Small-Claims Court", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Provider chosen once at startup: Anthropic > OpenAI > Scripted.
PROVIDER_NAME, PROVIDER = select_provider()
log.info("LLM provider: %s", PROVIDER_NAME)

# In-memory store: dispute_id -> dispute dict.
STORE: dict[str, dict] = {}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "provider": PROVIDER_NAME}


@app.post("/api/disputes")
def create_dispute(body: dict):
    required = ["claimant_name", "respondent_name", "claim_title"]
    for field in required:
        if not body.get(field):
            raise HTTPException(400, f"missing required field: {field}")
    dispute_id = _new_id()
    STORE[dispute_id] = {
        "id": dispute_id,
        "claimant_name": body["claimant_name"],
        "respondent_name": body["respondent_name"],
        "claim_title": body["claim_title"],
        "claim_description": body.get("claim_description", ""),
        "amount_usdc": body.get("amount_usdc", 0),
        "claimant_evidence": body.get("claimant_evidence", []),
        "respondent_evidence": body.get("respondent_evidence", []),
        "status": "created",
        "transcript": [],
        "verdict": None,
    }
    log.info("dispute created: %s", dispute_id)
    return {"id": dispute_id}


@app.post("/api/disputes/{dispute_id}/deliberate")
def deliberate_dispute(dispute_id: str):
    dispute = STORE.get(dispute_id)
    if dispute is None:
        raise HTTPException(404, "dispute not found")
    transcript, verdict = deliberate(dispute, PROVIDER)
    dispute["transcript"] = transcript
    dispute["verdict"] = verdict
    dispute["status"] = "deliberated"
    log.info("dispute deliberated: %s -> %s", dispute_id, verdict["winner"])
    return verdict


@app.get("/api/disputes/{dispute_id}")
def get_dispute(dispute_id: str):
    dispute = STORE.get(dispute_id)
    if dispute is None:
        raise HTTPException(404, "dispute not found")
    return dispute


@app.get("/api/disputes")
def list_disputes():
    return [
        {"id": d["id"], "title": d["claim_title"], "status": d["status"]}
        for d in STORE.values()
    ]


@app.get("/api/disputes/{dispute_id}/stream")
def stream_dispute(dispute_id: str):
    dispute = STORE.get(dispute_id)
    if dispute is None:
        raise HTTPException(404, "dispute not found")

    def event_gen():
        for entry in dispute["transcript"]:
            frame = {
                "type": entry["type"],
                "persona": entry.get("persona"),
                "round": entry.get("round"),
                "text": entry["text"],
            }
            yield "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
