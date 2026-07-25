"""
FastAPI app. Owner: Track A. Endpoints per docs/CONTRACTS.md Contract 1 HTTP surface.

The /query pipeline (intent_parser -> planner -> executor -> narrator) is not yet
implemented (see those modules' docstrings, WORKPLAN.md Track A schedule). Until
then this returns 501 rather than crashing, so the server boots and /health works
for Track B / integration testing from hour 0.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.schemas import AgentResponse

app = FastAPI(title="AML Suspicious Activity Detection Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# plan_id -> AgentResponse, populated once /query is implemented (WORKPLAN.md H16-H24)
_RUN_CACHE: dict[str, AgentResponse] = {}


class QueryRequest(BaseModel):
    query: str
    dataset: str | None = None


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_available": bool(settings.gemini_api_key or settings.openai_api_key),
        "mocks": settings.aml_use_mocks,
    }


@app.get("/dataset/summary")
def dataset_summary() -> dict:
    raise HTTPException(status_code=501, detail="Not implemented yet — see backend/tools/data_loader.py (Track B)")


@app.post("/query", response_model=AgentResponse)
def query(request: QueryRequest) -> AgentResponse:
    raise HTTPException(
        status_code=501,
        detail="Not implemented yet — see backend/agent/{intent_parser,planner,executor,narrator}.py (Track A)",
    )


@app.get("/plan/{plan_id}", response_model=AgentResponse)
def get_plan(plan_id: str) -> AgentResponse:
    if plan_id not in _RUN_CACHE:
        raise HTTPException(status_code=404, detail=f"no cached run for plan_id={plan_id}")
    return _RUN_CACHE[plan_id]
