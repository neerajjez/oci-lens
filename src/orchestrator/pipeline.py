"""
src/orchestrator/pipeline.py
=============================
PipelineRunner: executes ordered steps with state tracking, run log, and
graceful handling of critical vs non-critical step failures.
"""
from __future__ import annotations

import concurrent.futures
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.orchestrator.state import RunStateManager
from src.orchestrator.steps import (
    AnalyzeDataStep,
    CleanupStep,
    CollectDataStep,
    DispatchNotificationsStep,
    GenerateReportStep,
    RunContext,
    Step,
    StepResult,
    ValidateConfigStep,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

_RUN_LOG = Path("reports") / "run_log.jsonl"

_DEFAULT_STEPS: list[Step] = [
    ValidateConfigStep(),
    CollectDataStep(),
    AnalyzeDataStep(),
    GenerateReportStep(),
    DispatchNotificationsStep(),
    CleanupStep(),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunResult:
    def __init__(
        self,
        run_id: str,
        status: str,
        step_results: list[StepResult],
        report_path: Optional[Path],
        duration_s: float,
        started_at: str,
        finished_at: str,
    ) -> None:
        self.run_id = run_id
        self.status = status
        self.step_results = step_results
        self.report_path = report_path
        self.duration_s = duration_s
        self.started_at = started_at
        self.finished_at = finished_at

    @property
    def success(self) -> bool:
        return self.status == "success"


class PipelineRunner:
    def __init__(self, config: dict, steps: Optional[list[Step]] = None) -> None:
        self._config = config
        self._steps = steps if steps is not None else list(_DEFAULT_STEPS)

    def run(
        self,
        dry_run: bool = False,
        skip_notify: bool = False,
        resume_run_id: Optional[str] = None,
    ) -> RunResult:
        run_id = resume_run_id or uuid.uuid4().hex[:8]
        started_at = _now_iso()

        RunStateManager.mark_stale_orphans_failed()

        state_mgr = RunStateManager(run_id)
        state_mgr.load_or_create()

        context = RunContext(
            run_id=run_id,
            config=self._config,
            dry_run=dry_run,
            skip_notify=skip_notify,
        )

        step_results: list[StepResult] = []
        aborted = False

        for step in self._steps:
            if step.name == CleanupStep.name:
                result = step.run(context)
                step_results.append(result)
                state_mgr.complete_step(step.name, result.artifact_path)
                continue

            if aborted:
                skipped = StepResult(step_name=step.name, status="skipped")
                step_results.append(skipped)
                continue

            if resume_run_id and state_mgr.is_step_done(step.name):
                artifact = state_mgr.artifact_for(step.name)
                log.info("step_resumed", step=step.name, artifact=str(artifact))
                step_results.append(StepResult(
                    step_name=step.name,
                    status="success",
                    artifact_path=artifact,
                ))
                _restore_context(step.name, artifact, context)
                continue

            state_mgr.update_step(step.name)
            log.info("step_start", step=step.name)
            result = _run_with_timeout(step, context)
            step_results.append(result)

            if result.status in ("success", "skipped"):
                state_mgr.complete_step(step.name, result.artifact_path)
                log.info("step_done", step=step.name, duration_s=round(result.duration_s, 2))
            else:
                log.error("step_failed", step=step.name, error=result.error)
                if step.critical:
                    aborted = True

        overall = "failed" if aborted else "success"
        finished_at = _now_iso()
        state_mgr.mark_complete(overall)

        t0 = datetime.fromisoformat(started_at).timestamp()
        duration_s = datetime.fromisoformat(finished_at).timestamp() - t0

        run_result = RunResult(
            run_id=run_id,
            status=overall,
            step_results=step_results,
            report_path=context.report_path,
            duration_s=duration_s,
            started_at=started_at,
            finished_at=finished_at,
        )

        _append_run_log(run_result)
        return run_result


def _run_with_timeout(step: Step, context: RunContext) -> StepResult:
    """Run a step inside a thread so its timeout_s is actually enforced."""
    timeout = getattr(step, "timeout_s", None)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(step.run, context)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.error("step_timed_out", step=step.name, timeout_s=timeout)
            return StepResult(
                step_name=step.name,
                status="failed",
                error=f"step exceeded timeout of {timeout}s",
            )


def _restore_context(step_name: str, artifact: Optional[Path], ctx: RunContext) -> None:
    if step_name == "collect_data" and artifact:
        ctx.raw_data_path = artifact
    elif step_name == "analyze_data" and artifact:
        ctx.analytics_path = artifact
    elif step_name == "generate_report" and artifact:
        ctx.report_path = artifact


def _append_run_log(result: RunResult) -> None:
    try:
        _RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "run_id": result.run_id,
            "status": result.status,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_s": round(result.duration_s, 2),
            "report_path": str(result.report_path) if result.report_path else None,
            "step_results": [
                {
                    "step": r.step_name,
                    "status": r.status,
                    "duration_s": round(r.duration_s, 2),
                    "error": r.error,
                }
                for r in result.step_results
            ],
        }
        with _RUN_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.error("run_log_write_failed", error=str(exc))
