"""Async runtime + storage for pipeline jobs.

Primary persistence:
- Supabase Postgres via PostgREST (when configured)

Fallback persistence:
- filesystem manifests in artifacts/_jobs/<job_id>.json
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="softcut-jobs")


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def safe_job_id(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "").strip())
    cleaned = cleaned.strip("-_")
    return cleaned[:128]


def submit_background(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    _EXECUTOR.submit(fn, *args, **kwargs)


class JobStore:
    """Dual-write store (Supabase first, filesystem fallback)."""

    def __init__(self, artifacts_root: Path) -> None:
        self.artifacts_root = artifacts_root
        self.jobs_root = artifacts_root / "_jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)

        self.supabase_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self.supabase_service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self._supabase_enabled = bool(self.supabase_url and self.supabase_service_role_key)

    def _manifest_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.json"

    def _read_file(self, job_id: str) -> dict[str, Any] | None:
        path = self._manifest_path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_file(self, job_id: str, payload: dict[str, Any]) -> None:
        path = self._manifest_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _supabase_headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.supabase_service_role_key,
            "Authorization": f"Bearer {self.supabase_service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _supabase_request_json(
        self,
        *,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> Any:
        if not self._supabase_enabled:
            raise RuntimeError("supabase not configured")

        base = f"{self.supabase_url}/rest/v1/{path.lstrip('/')}"
        if query:
            base = f"{base}?{parse.urlencode(query)}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            base,
            data=data,
            method=method.upper(),
            headers=self._supabase_headers(prefer=prefer),
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else None
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"supabase request failed ({exc.code}): {body}") from exc
        except Exception as exc:  # pragma: no cover - network/runtime boundary
            raise RuntimeError(f"supabase request failed: {exc}") from exc

    def _read_supabase(self, job_id: str) -> dict[str, Any] | None:
        rows = self._supabase_request_json(
            method="GET",
            path="jobs",
            query={"job_id": f"eq.{job_id}", "select": "*", "limit": "1"},
        )
        if not rows:
            return None
        row = rows[0]
        if isinstance(row.get("artifacts"), str):
            try:
                row["artifacts"] = json.loads(row["artifacts"])
            except Exception:
                row["artifacts"] = {}
        return row

    def _upsert_supabase(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._supabase_request_json(
            method="POST",
            path="jobs",
            query={"on_conflict": "job_id"},
            payload=[payload],
            prefer="resolution=merge-duplicates,return=representation",
        )
        if rows and isinstance(rows, list):
            row = rows[0]
            if isinstance(row.get("artifacts"), str):
                try:
                    row["artifacts"] = json.loads(row["artifacts"])
                except Exception:
                    row["artifacts"] = {}
            return row
        return payload

    def create_or_replace(
        self,
        *,
        job_id: str,
        pipeline_mode: str,
        artifacts: dict[str, str],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        payload: dict[str, Any] = {
            "job_id": job_id,
            "pipeline_mode": pipeline_mode,
            "status": "queued",
            "stage": "queued",
            "message": "Job queued.",
            "created_at_utc": now,
            "started_at_utc": None,
            "updated_at_utc": now,
            "completed_at_utc": None,
            "artifacts": artifacts,
            "error": None,
        }

        row = payload
        if self._supabase_enabled:
            try:
                row = self._upsert_supabase(payload)
            except Exception:
                # Keep local flow alive if DB is temporarily unavailable.
                row = payload
        self._write_file(job_id, row)
        return row

    def read(self, job_id: str) -> dict[str, Any] | None:
        if self._supabase_enabled:
            try:
                row = self._read_supabase(job_id)
                if row is not None:
                    self._write_file(job_id, row)
                    return row
            except Exception:
                pass
        return self._read_file(job_id)

    def patch(self, job_id: str, **changes: Any) -> dict[str, Any]:
        current = self.read(job_id)
        if current is None:
            raise FileNotFoundError(f"job not found: {job_id}")

        now = utc_now_iso()
        merged = {**current, **changes}
        merged["job_id"] = job_id
        merged["updated_at_utc"] = now

        if merged.get("status") == "running" and not merged.get("started_at_utc"):
            merged["started_at_utc"] = now
        if merged.get("status") in {"completed", "failed"} and not merged.get("completed_at_utc"):
            merged["completed_at_utc"] = now

        row = merged
        if self._supabase_enabled:
            try:
                row = self._upsert_supabase(merged)
            except Exception:
                row = merged
        self._write_file(job_id, row)
        return row
