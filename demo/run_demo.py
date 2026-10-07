#!/usr/bin/env python3
"""Gavel end-to-end demo: freelancer vs. client, $500 unpaid invoice.

Runs the full flow against the local backend (http://localhost:8000):
  1. Files the demo dispute from backend/demo_dispute.json
  2. Runs the 3-justice deliberation
  3. Prints the transcript + verdict + transcript hash

The hash is what gets anchored on-chain via GavelEscrow.submitRuling
(disputeId, winner, transcriptHash) — wiring that to a Base Sepolia
deployment is the second-pass step (needs a funded deployer key).

Usage:
    python demo/run_demo.py [--api http://localhost:8000]
"""
import argparse
import json
import sys
import urllib.request
import urllib.error

PERSONA_STYLE = {
    "textualist": ("THE TEXTUALIST", "§"),
    "consumer_advocate": ("THE CONSUMER ADVOCATE", "🛡"),
    "precedent_analyst": ("THE PRECEDENT ANALYST", "📚"),
}


def api(base, method, path, body=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except urllib.error.URLError as e:
        print(f"\n[!] API call {method} {path} failed: {e}", file=sys.stderr)
        print("[!] Is the backend running?  cd backend && uvicorn app:app --port 8000", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    base = args.api.rstrip("/")

    health = api(base, "GET", "/api/health")
    print(f"Backend OK — deliberation provider: {health.get('provider')}\n")

    with open("backend/demo_dispute.json") as f:
        dispute = json.load(f)

    created = api(base, "POST", "/api/disputes", dispute)
    did = created["id"]
    print(f"Dispute filed: {dispute['claim_title']}")
    print(f"  {dispute['claimant_name']}  vs  {dispute['respondent_name']}  —  ${dispute['amount_usdc']} USDC\n")

    print("The court is in session…\n")
    api(base, "POST", f"/api/disputes/{did}/deliberate")

    full = api(base, "GET", f"/api/disputes/{did}")
    transcript = full.get("transcript", [])
    print("=" * 70)
    print("  TRANSCRIPT OF DELIBERATION")
    print("=" * 70)
    current_round = 0
    for ev in transcript:
        etype = ev.get("type", "")
        if etype == "verdict":
            continue
        rnd = ev.get("round", 0)
        if rnd != current_round and etype in ("opening", "rebuttal", "closing"):
            current_round = rnd
            label = {1: "OPENING STATEMENTS", 2: "REBUTTALS", 3: "CLOSING POSITIONS"}.get(rnd, f"ROUND {rnd}")
            print(f"\n── {label} ──")
        name, icon = PERSONA_STYLE.get(ev.get("persona", ""), (ev.get("persona", "?").upper(), "•"))
        if etype == "vote":
            print(f"\n  {icon} {name} votes: {ev.get('text','').strip()}")
        else:
            print(f"\n{icon} {name}:")
            print(f"  {ev.get('text','').strip()}")

    v = full.get("verdict", {})
    print("\n" + "=" * 70)
    winner = v.get("winner", "?").upper()
    print(f"  ⚖  RULED FOR THE {winner}")
    print("=" * 70)
    print(f"\nReasoning:\n  {v.get('reasoning','')}")
    print(f"\nAwarded: ${v.get('awarded_amount_usdc', 0)} USDC")
    print(f"Transcript SHA-256: {v.get('transcript_hash','')}")
    print("\nNext step (second pass): deploy GavelEscrow to Base Sepolia and call")
    print("submitRuling(disputeId, winner, transcriptHash) to anchor + auto-pay.")


if __name__ == "__main__":
    main()
