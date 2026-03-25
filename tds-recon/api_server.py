"""
FastAPI bridge for TDS Reconciliation agents.
Wraps the Python pipeline and exposes it to the React UI.

Run: uvicorn api_server:app --reload --port 8000
"""

import json
import queue
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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


@app.get("/api/run/stream")
def run_pipeline_stream():
    """Run the full pipeline with real-time SSE streaming.

    Each event is sent as it happens — no batching, no fake delays.
    Final event includes the full results payload.
    """
    event_queue = queue.Queue()

    def on_event(event):
        event_queue.put(event)

    def run_in_thread():
        from agents.event_logger import reset_logger
        from reconcile import run_pipeline as _run

        logger = reset_logger()
        logger.set_callback(on_event)
        result = _run()

        # Send final results as a special event
        results_data = _load_results()
        event_queue.put({
            "type": "pipeline_complete",
            "agent": "Pipeline",
            "message": f"Complete in {result.get('elapsed_s', 0)}s",
            "results": results_data,
        })
        event_queue.put(None)  # Sentinel to end stream

    # Start pipeline in background thread
    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def event_generator():
        while True:
            try:
                event = event_queue.get(timeout=30)
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
            except queue.Empty:
                # Keep-alive
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/run")
def run_pipeline():
    """Execute the full pipeline (non-streaming fallback)."""
    from reconcile import run_pipeline as _run
    result = _run()
    result["results"] = _load_results()
    return result


# ---------------------------------------------------------------------------
# Individual Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/run/parser")
def run_parser():
    """Run only the Parser Agent."""
    from agents.event_logger import reset_logger
    logger = reset_logger()
    start = time.time()
    logger.agent_start("Parser Agent", "Starting Parser Agent...")

    if not (PARSED_DIR / "parsed_form26.json").exists():
        logger.error("Parser Agent", "parsed_form26.json not found")
        return {"events": logger.get_events(), "error": "Missing parsed data"}
    if not (PARSED_DIR / "parsed_tally.json").exists():
        logger.error("Parser Agent", "parsed_tally.json not found")
        return {"events": logger.get_events(), "error": "Missing parsed data"}

    with open(PARSED_DIR / "parsed_form26.json") as f:
        f26 = json.load(f)
    with open(PARSED_DIR / "parsed_tally.json") as f:
        tally = json.load(f)

    f26_count = len(f26.get("entries", []))
    sections = set(e["section"] for e in f26.get("entries", []))
    jr_count = len(tally.get("journal_register", {}).get("entries", []))
    gst_count = len(tally.get("purchase_gst_exp_register", {}).get("entries", []))
    pr_count = len(tally.get("purchase_register", {}).get("entries", []))

    logger.detail("Parser Agent", f"Form 26: {f26_count} entries across {len(sections)} sections")
    logger.detail("Parser Agent", f"Sections found: {', '.join(sorted(sections))}")
    logger.detail("Parser Agent", f"Tally Journal Register: {jr_count} entries")
    logger.detail("Parser Agent", f"Tally GST Expense Register: {gst_count} entries")
    logger.detail("Parser Agent", f"Tally Purchase Register: {pr_count} entries")

    elapsed = time.time() - start
    logger.agent_done("Parser Agent", f"Parsing complete ({elapsed:.1f}s)")
    return {"events": logger.get_events(), "elapsed_s": round(elapsed, 2)}


@app.post("/api/run/matcher")
def run_matcher():
    """Run only the Matcher Agent."""
    from agents.event_logger import reset_logger
    from agents.matcher_agent import run as matcher_run
    logger = reset_logger()
    start = time.time()

    logger.agent_start("Matcher Agent", "Starting Matcher Agent...")
    match_results = matcher_run(str(PARSED_DIR), str(RESULTS_DIR), rules_dir=str(RULES_DIR))

    summary = match_results.get("summary", {})
    matched = summary.get("form26_matched", 0)
    total = summary.get("form26_total", 0)
    pct = (matched / total * 100) if total > 0 else 0
    logger.success("Matcher Agent", f"Result: {matched}/{total} matched ({pct:.0f}%)")

    elapsed = time.time() - start
    logger.agent_done("Matcher Agent", f"Matching complete ({elapsed:.1f}s)")
    return {"events": logger.get_events(), "elapsed_s": round(elapsed, 2), "results": {"match_results": match_results}}


@app.post("/api/run/checker")
def run_checker():
    """Run only the TDS Checker Agent."""
    from agents.event_logger import reset_logger
    from agents.tds_checker_agent import run as checker_run
    logger = reset_logger()
    start = time.time()

    if not (RESULTS_DIR / "match_results.json").exists():
        return {"events": [], "error": "Run Matcher first"}

    logger.agent_start("TDS Checker", "Starting TDS Checker Agent...")
    checker_results = checker_run(str(PARSED_DIR), str(RESULTS_DIR))
    findings = checker_results.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    logger.success("TDS Checker", f"Complete: {len(errors)} errors, {len(warnings)} warnings")

    elapsed = time.time() - start
    logger.agent_done("TDS Checker", f"Compliance checks complete ({elapsed:.1f}s)")
    return {"events": logger.get_events(), "elapsed_s": round(elapsed, 2), "results": {"checker_results": checker_results}}


@app.post("/api/run/reporter")
def run_reporter():
    """Run only the Reporter Agent."""
    from agents.event_logger import reset_logger
    from agents.reporter_agent import run as reporter_run
    logger = reset_logger()
    start = time.time()

    if not (RESULTS_DIR / "match_results.json").exists():
        return {"events": [], "error": "Run Matcher first"}

    logger.agent_start("Reporter Agent", "Generating reports...")
    report = reporter_run(str(PARSED_DIR), str(RESULTS_DIR))

    elapsed = time.time() - start
    logger.agent_done("Reporter Agent", f"Reports generated ({elapsed:.1f}s)")
    return {"events": logger.get_events(), "elapsed_s": round(elapsed, 2), "results": {"reconciliation_summary": report.get("summary", {})}}


# ---------------------------------------------------------------------------
# Results + Review
# ---------------------------------------------------------------------------

@app.get("/api/results")
def get_results():
    return _load_results()


@app.get("/api/rules")
def get_rules():
    from agents.learning_agent import load_rules, summarize_rules
    db = load_rules(str(RULES_DIR))
    summary = summarize_rules(str(RULES_DIR))
    return {"rules": db, "summary": summary}


class ReviewDecision(BaseModel):
    vendor: str
    decision: str
    params: dict = {}
    reason: str = ""


class ReviewRequest(BaseModel):
    decisions: list[ReviewDecision]


@app.post("/api/review")
def submit_review(request: ReviewRequest):
    from agents.learning_agent import apply_corrections
    decisions = [d.model_dump() for d in request.decisions]
    result = apply_corrections(str(RULES_DIR), str(RESULTS_DIR), decisions)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_results() -> dict:
    results = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results[fname.replace(".json", "")] = json.load(f)
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
