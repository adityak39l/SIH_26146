from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.pipeline.engine import run_offline_pipeline
from typing import Dict, Any

app = FastAPI(
    title="VIGIL-CHAIN API (SIH26146)",
    description="Offline AI-Powered Bitcoin Network & Transaction Traffic Intelligence Engine for NTRO",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "status": "ONLINE (AIR-GAPPED LINUX MODE)",
        "challenge": "SIH26146",
        "agency": "National Technical Research Organisation (NTRO)",
        "system": "VIGIL-CHAIN Forensic Engine"
    }

@app.get("/api/leads")
def get_leads():
    """Returns ranked, explainable investigative leads."""
    leads = run_offline_pipeline()
    return {"total": len(leads), "leads": leads}
