"""FastAPI entrypoint for local MVP backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.analysis import router as analysis_router
from apps.api.routes.jobs import router as jobs_router
from apps.api.routes.planner import router as planner_router

app = FastAPI(
    title="Softcut API",
    version="0.1.0",
    description="Local API for rating-aligned video safe-cut analysis and planning.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analysis_router)
app.include_router(planner_router)
app.include_router(jobs_router)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Simple health endpoint."""
    return {"status": "ok"}
