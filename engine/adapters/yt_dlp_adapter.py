"""Source URL download adapter backed by yt-dlp."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from engine.schemas.timeline import AdapterState, AdapterStatus

ProgressCallback = Callable[[str], None]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _yt_dlp_version_text(module: object) -> str | None:
    version_namespace = getattr(module, "version", None)
    version_text = getattr(version_namespace, "__version__", None)
    if isinstance(version_text, str) and version_text:
        return version_text
    return None


def _find_latest_download(*, output_dir: Path, prefix: str) -> Path | None:
    candidates = [
        path
        for path in output_dir.glob(f"{prefix}*")
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _download_with_python(
    *,
    source_url: str,
    output_dir: Path,
    job_id: str,
    progress: ProgressCallback | None,
) -> tuple[Path, AdapterStatus]:
    import yt_dlp

    outtmpl = str(output_dir / f"{job_id}_%(title).120s_%(id)s.%(ext)s")
    progress_state = {"next_report_pct": 5}

    def progress_hook(data: dict[str, object]) -> None:
        status = str(data.get("status", ""))
        if status == "downloading":
            downloaded = float(data.get("downloaded_bytes") or 0.0)
            total = float(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0.0
            )
            if total <= 0:
                return
            pct = int((downloaded / total) * 100)
            if pct >= progress_state["next_report_pct"]:
                _emit(progress, f"Download progress: {pct}%")
                progress_state["next_report_pct"] = min(100, pct + 5)
        elif status == "finished":
            _emit(progress, "Download complete. Finalizing media container...")

    ydl_opts = {
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=True)
        requested = info.get("requested_downloads") if isinstance(info, dict) else None
        if isinstance(requested, list):
            for item in requested:
                if not isinstance(item, dict):
                    continue
                filepath = item.get("filepath") or item.get("_filename")
                if isinstance(filepath, str) and Path(filepath).exists():
                    return Path(filepath), AdapterStatus(
                        state=AdapterState.available,
                        version=_yt_dlp_version_text(yt_dlp),
                        config={"format": ydl_opts["format"], "mode": "python_api"},
                    )

    latest = _find_latest_download(output_dir=output_dir, prefix=f"{job_id}_")
    if latest is None:
        raise RuntimeError("yt-dlp finished but no downloaded file was found.")
    return latest, AdapterStatus(
        state=AdapterState.available,
        version=_yt_dlp_version_text(yt_dlp),
        config={"format": ydl_opts["format"], "mode": "python_api"},
    )


def _download_with_subprocess(
    *,
    source_url: str,
    output_dir: Path,
    job_id: str,
    progress: ProgressCallback | None,
) -> tuple[Path, AdapterStatus]:
    outtmpl = str(output_dir / f"{job_id}_%(title).120s_%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--newline",
        "--restrict-filenames",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        outtmpl,
        source_url,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout is not None:
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            if (
                stripped.startswith("[download]")
                or stripped.startswith("[Merger]")
                or stripped.startswith("[ExtractAudio]")
            ):
                _emit(progress, stripped)

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"yt-dlp failed with exit code {return_code}.")

    latest = _find_latest_download(output_dir=output_dir, prefix=f"{job_id}_")
    if latest is None:
        raise RuntimeError("yt-dlp finished but no downloaded file was found.")
    return latest, AdapterStatus(
        state=AdapterState.available,
        config={"format": "bv*+ba/b", "mode": "subprocess"},
    )


def download_video_from_url(
    *,
    source_url: str,
    output_dir: str | Path,
    job_id: str,
    progress: ProgressCallback | None = None,
) -> tuple[Path, AdapterStatus]:
    """Download source video from URL to local storage."""
    if not source_url.startswith(("http://", "https://")):
        raise ValueError("source_url must start with http:// or https://")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        return _download_with_python(
            source_url=source_url,
            output_dir=output_path,
            job_id=job_id,
            progress=progress,
        )
    except ModuleNotFoundError:
        _emit(progress, "yt_dlp Python module unavailable; falling back to yt-dlp CLI.")
        return _download_with_subprocess(
            source_url=source_url,
            output_dir=output_path,
            job_id=job_id,
            progress=progress,
        )
    except Exception as exc:
        _emit(progress, f"yt_dlp Python API failed ({exc}); falling back to yt-dlp CLI.")
        return _download_with_subprocess(
            source_url=source_url,
            output_dir=output_path,
            job_id=job_id,
            progress=progress,
        )
