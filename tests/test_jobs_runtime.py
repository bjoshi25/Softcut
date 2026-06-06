"""Unit tests for filesystem-backed job manifest runtime."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.jobs_runtime import JobStore, safe_job_id


class JobsRuntimeTests(unittest.TestCase):
    def test_safe_job_id_normalizes_invalid_chars(self) -> None:
        self.assertEqual(safe_job_id("job id/01"), "job_id_01")
        self.assertEqual(safe_job_id(""), "")

    def test_store_create_patch_read(self) -> None:
        with tempfile.TemporaryDirectory(prefix="softcut_jobs_runtime_") as temp_dir:
            store = JobStore(artifacts_root=Path(temp_dir) / "artifacts")
            created = store.create_or_replace(
                job_id="job_001",
                pipeline_mode="pipeline",
                artifacts={"analysis_timeline": "a.json"},
            )
            self.assertEqual(created["status"], "queued")
            patched = store.patch("job_001", status="running", stage="analysis", message="Working")
            self.assertEqual(patched["status"], "running")
            self.assertEqual(patched["stage"], "analysis")
            self.assertIsNotNone(patched["started_at_utc"])

            done = store.patch("job_001", status="completed", stage="done", message="Done")
            self.assertEqual(done["status"], "completed")
            self.assertIsNotNone(done["completed_at_utc"])

            loaded = store.read("job_001")
            assert loaded is not None
            self.assertEqual(loaded["job_id"], "job_001")


if __name__ == "__main__":
    unittest.main()
