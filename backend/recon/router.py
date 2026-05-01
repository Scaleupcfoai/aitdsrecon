"""TDS Reconciliation routes — mounted into the main backend API.

Originally lived at tds-recon/api_server.py as a standalone FastAPI app.
Refactored into an APIRouter so the lekha tds-calculator backend and the
TDS reconciliation backend can run as a single uvicorn process.

Routes (mounted at /api/...):
  GET  /api/status      → parsed/results/rules readiness
  POST /api/run         → execute the full reconciliation pipeline
  GET  /api/results     → cached match/checker/summary results
  GET  /api/rules       → learned rules + summary
  POST /api/review      → submit human review decisions
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["tds-recon"])

BASE = Path(__file__).parent
RESULTS_DIR = BASE / "data" / "results"
RULES_DIR = BASE / "data" / "rules"
PARSED_DIR = BASE / "data" / "parsed"


@router.get("/api/status")
def get_status():
    """Check if parsed data and results exist."""
    return {
        "parsed_ready": (PARSED_DIR / "parsed_form26.json").exists(),
        "results_ready": (RESULTS_DIR / "match_results.json").exists(),
        "rules_ready": (RULES_DIR / "learned_rules.json").exists(),
    }


@router.post("/api/run")
def run_pipeline():
    """Execute the full reconciliation pipeline and return events + results."""
    from .reconcile import run_pipeline as _run
    result = _run()
    results_data = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results_data[fname.replace(".json", "")] = json.load(f)
    result["results"] = results_data
    return result


@router.get("/api/results")
def get_results():
    """Read cached results from disk."""
    results = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results[fname.replace(".json", "")] = json.load(f)
    return results


@router.get("/api/rules")
def get_rules():
    """Get current learned rules."""
    from .agents.learning_agent import load_rules, summarize_rules
    db = load_rules(str(RULES_DIR))
    summary = summarize_rules(str(RULES_DIR))
    return {"rules": db, "summary": summary}


class ReviewDecision(BaseModel):
    vendor: str
    decision: str  # below_threshold, exempt, ignore, alias, section_override
    params: dict = {}
    reason: str = ""


class ReviewRequest(BaseModel):
    decisions: list[ReviewDecision]


@router.post("/api/review")
def submit_review(request: ReviewRequest):
    """Submit human review decisions — apply corrections to affected entries only.

    Does NOT re-run the full pipeline. Instead:
    1. Stores decisions as learned rules
    2. Applies corrections to current unmatched entries
    3. Re-runs only Checker + Reporter on updated results
    """
    from .agents.learning_agent import apply_corrections

    decisions = [d.model_dump() for d in request.decisions]
    result = apply_corrections(str(RULES_DIR), str(RESULTS_DIR), decisions)
    return result
