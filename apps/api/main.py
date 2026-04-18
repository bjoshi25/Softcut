"""FastAPI entrypoint for local MVP backend."""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes.analysis import router as analysis_router

app = FastAPI(
    title="Softcut API",
    version="0.1.0",
    description="Local API for rating-aligned video safe-cut analysis.",
)
app.include_router(analysis_router)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Simple health endpoint."""
    return {"status": "ok"}
