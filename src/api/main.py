from functools import lru_cache
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from config.settings import PIPELINE_VERSION
from src.pipeline.engine import analyze
from src.pipeline.export import render_dashboard

app = FastAPI(
    title="VIGIL-CHAIN API (SIH26146)",
    description="Offline AI-Powered Bitcoin Network & Transaction Traffic Intelligence Engine",
    version=PIPELINE_VERSION,
)


@lru_cache(maxsize=1)
def _result() -> Dict[str, Any]:
    return analyze()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Analyst console."""
    return render_dashboard(_result())


@app.get("/api/status")
def status():
    return {
        "status": "ONLINE (AIR-GAPPED MODE)",
        "challenge": "SIH26146",
        "system": "VIGIL-CHAIN Forensic Engine",
        "pipeline_version": PIPELINE_VERSION,
    }


@app.get("/api/summary")
def get_summary():
    result = _result()
    return {"meta": result["meta"], "summary": result["summary"], "evaluation": result["evaluation"]}


@app.get("/api/cases")
def get_cases():
    """Ranked cases: flagged transactions grouped by money flow, each with its explanation."""
    cases = _result()["cases"]
    return {"total": len(cases), "cases": cases}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    for case in _result()["cases"]:
        if case["case_id"] == case_id.upper():
            return case
    raise HTTPException(status_code=404, detail=f"Unknown case: {case_id}")


@app.get("/api/leads")
def get_leads():
    """Returns ranked, explainable transaction-level leads."""
    leads = _result()["leads"]
    return {"total": len(leads), "leads": leads}


@app.post("/api/refresh")
def refresh():
    """Re-runs the pipeline on the files currently in the data directory."""
    _result.cache_clear()
    return {"summary": _result()["summary"]}
