"""
FastAPI bridge for TDS Reconciliation agents.
Wraps the Python pipeline and exposes it to the React UI.

Run: uvicorn api_server:app --reload --port 8000
"""

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent to path so agents module is importable
sys.path.insert(0, str(Path(__file__).parent))

app = FastAPI(title="TDS Recon API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = Path(__file__).parent
RESULTS_DIR = BASE / "data" / "results"
RULES_DIR = BASE / "data" / "rules"
PARSED_DIR = BASE / "data" / "parsed"


@app.get("/api/status")
def get_status():
    """Check if parsed data and results exist."""
    return {
        "parsed_ready": (PARSED_DIR / "parsed_form26.json").exists(),
        "results_ready": (RESULTS_DIR / "match_results.json").exists(),
        "rules_ready": (RULES_DIR / "learned_rules.json").exists(),
    }


@app.post("/api/run")
def run_pipeline():
    """Execute the full reconciliation pipeline and return events + results."""
    from reconcile import run_pipeline as _run
    result = _run()
    # Also load the full results files for the UI
    results_data = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results_data[fname.replace(".json", "")] = json.load(f)
    result["results"] = results_data
    return result


@app.get("/api/results")
def get_results():
    """Read cached results from disk."""
    results = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results[fname.replace(".json", "")] = json.load(f)
    return results


@app.get("/api/rules")
def get_rules():
    """Get current learned rules."""
    from agents.learning_agent import load_rules, summarize_rules
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


@app.post("/api/review")
def submit_review(request: ReviewRequest):
    """Submit human review decisions, create rules, and re-run pipeline."""
    from agents.learning_agent import process_human_review

    decisions = [d.model_dump() for d in request.decisions]
    review_result = process_human_review(str(RULES_DIR), decisions)

    # Re-run pipeline with new rules
    from reconcile import run_pipeline as _run
    pipeline_result = _run()

    # Load updated results
    results_data = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results_data[fname.replace(".json", "")] = json.load(f)
    pipeline_result["results"] = results_data
    pipeline_result["review"] = review_result
    return pipeline_result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
