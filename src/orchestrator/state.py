"""
src/orchestrator/state.py
==========================
Run state persistence, orphan detection, and idempotency helpers.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)

_STATE_DIR = Path("reports") / "state"
_ORPHAN_THRESHOLD_S = 7200   # 2 hours


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStateManager:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._path = _STATE_DIR / f"{run_id}.json"
        self._state: dict = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def load_or_create(self) -> dict:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                self._state = json.loads(self._path.read_text())
                log.info("state_loaded", run_id=self._run_id)
                return self._state
            except Exception as exc:
                log.warning("state_load_failed", run_id=self._run_id, error=str(exc))

        self._state = {
            "run_id": self._run_id,
            "started_at": _now_iso(),
            "status": "running",
            "current_step": None,
            "completed_steps": [],
            "artifacts": {},
        }
        self._write()
        return self._state

    def update_step(self, step_name: str, artifact_path: Optional[Path] = None) -> None:
        self._state["current_step"] = step_name
        if artifact_path:
            self._state["artifacts"][step_name] = str(artifact_path)
        self._write()

    def complete_step(self, step_name: str, artifact_path: Optional[Path] = None) -> None:
        if step_name not in self._state.get("completed_steps", []):
            self._state.setdefault("completed_steps", []).append(step_name)
        self._state["current_step"] = None
        if artifact_path:
            self._state["artifacts"][step_name] = str(artifact_path)
        self._write()

    def mark_complete(self, status: str = "success") -> None:
        self._state["status"] = status
        self._state["finished_at"] = _now_iso()
        self._write()

    def is_step_done(self, step_name: str) -> bool:
        return step_name in self._state.get("completed_steps", [])

    def artifact_for(self, step_name: str) -> Optional[Path]:
        p = self._state.get("artifacts", {}).get(step_name)
        return Path(p) if p else None

    # ── orphan detection ──────────────────────────────────────────────────────

    @classmethod
    def scan_orphans(cls) -> list[dict]:
        if not _STATE_DIR.exists():
            return []

        now = time.time()
        orphans = []
        for p in _STATE_DIR.glob("*.json"):
            try:
                state = json.loads(p.read_text())
                if state.get("status") != "running":
                    continue
                age_s = now - p.stat().st_mtime
                orphans.append({
                    "run_id": state.get("run_id", p.stem),
                    "age_s": age_s,
                    "path": str(p),
                    "stale": age_s >= _ORPHAN_THRESHOLD_S,
                })
            except Exception:
                pass

        return orphans

    @classmethod
    def mark_stale_orphans_failed(cls) -> int:
        marked = 0
        for orphan in cls.scan_orphans():
            if orphan["stale"]:
                p = Path(orphan["path"])
                try:
                    state = json.loads(p.read_text())
                    state["status"] = "failed"
                    state["error"] = "orphaned: marked failed on next startup"
                    p.write_text(json.dumps(state, indent=2))
                    log.warning("orphan_marked_failed", run_id=orphan["run_id"])
                    marked += 1
                except Exception as exc:
                    log.error("orphan_mark_failed_error", run_id=orphan["run_id"], error=str(exc))
            else:
                log.warning("orphan_may_be_running", run_id=orphan["run_id"], age_s=orphan["age_s"])
        return marked

    # ── internal ─────────────────────────────────────────────────────────────

    def _write(self) -> None:
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._state, indent=2))
        except Exception as exc:
            log.error("state_write_failed", run_id=self._run_id, error=str(exc))
