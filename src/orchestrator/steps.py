"""
src/orchestrator/steps.py
==========================
Abstract Step base, StepResult, RunContext, and all concrete pipeline steps.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class StepResult:
    step_name: str
    status: str           # success | failed | skipped | timeout
    artifact_path: Optional[Path] = None
    error: Optional[str] = None
    duration_s: float = 0.0


@dataclass
class RunContext:
    run_id: str
    config: dict
    dry_run: bool = False
    skip_notify: bool = False
    raw_data_path: Optional[Path] = None
    analytics_path: Optional[Path] = None
    report_path: Optional[Path] = None
    run_result: Any = None


class Step(ABC):
    name: str = "base"
    retryable: bool = False
    timeout_s: int = 3600
    critical: bool = True

    def run(self, context: RunContext) -> StepResult:
        t0 = time.monotonic()
        try:
            result = self.execute(context)
            result.duration_s = time.monotonic() - t0
            return result
        except Exception as exc:
            duration = time.monotonic() - t0
            log.error("step_exception", step=self.name, error=str(exc))
            return StepResult(
                step_name=self.name,
                status="failed",
                error=str(exc),
                duration_s=duration,
            )

    @abstractmethod
    def execute(self, context: RunContext) -> StepResult: ...


class ValidateConfigStep(Step):
    name = "validate_config"
    retryable = False
    critical = True

    def execute(self, context: RunContext) -> StepResult:
        from src.config.loader import validate_config
        issues = validate_config(context.config)
        if issues:
            return StepResult(
                step_name=self.name,
                status="failed",
                error=f"Config validation failed: {'; '.join(issues)}",
            )
        log.info("config_valid")
        return StepResult(step_name=self.name, status="success")


class CollectDataStep(Step):
    name = "collect_data"
    retryable = True
    critical = True

    def execute(self, context: RunContext) -> StepResult:
        if context.dry_run:
            log.info("collect_skipped_dry_run")
            return StepResult(step_name=self.name, status="skipped")

        from src.collector.runner import CollectorRunner
        reports_dir = Path("reports") / "raw"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"{context.run_id}_raw.json"

        if output_path.exists():
            log.info("collect_reusing_artifact", path=str(output_path))
            context.raw_data_path = output_path
            return StepResult(step_name=self.name, status="success", artifact_path=output_path)

        runner = CollectorRunner(context.config)
        runner.run(output_path=output_path)
        context.raw_data_path = output_path
        log.info("collect_done", path=str(output_path))
        return StepResult(step_name=self.name, status="success", artifact_path=output_path)


class AnalyzeDataStep(Step):
    name = "analyze_data"
    retryable = True
    critical = True

    def execute(self, context: RunContext) -> StepResult:
        if context.dry_run:
            log.info("analyze_skipped_dry_run")
            return StepResult(step_name=self.name, status="skipped")

        from src.analytics.engine import AnalyticsEngine
        reports_dir = Path("reports") / "analytics"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"{context.run_id}_analytics.json"

        if output_path.exists():
            log.info("analyze_reusing_artifact", path=str(output_path))
            context.analytics_path = output_path
            engine = AnalyticsEngine(context.config)
            context.run_result = engine.load(output_path)
            return StepResult(step_name=self.name, status="success", artifact_path=output_path)

        engine = AnalyticsEngine(context.config)
        result = engine.run(input_path=context.raw_data_path, output_path=output_path)
        context.analytics_path = output_path
        context.run_result = result
        log.info("analyze_done", path=str(output_path))
        return StepResult(step_name=self.name, status="success", artifact_path=output_path)


class GenerateReportStep(Step):
    name = "generate_report"
    retryable = False
    critical = False

    def execute(self, context: RunContext) -> StepResult:
        if context.dry_run:
            log.info("report_skipped_dry_run")
            return StepResult(step_name=self.name, status="skipped")

        from src.reporter import ReportBuilder
        reports_dir = Path("reports") / "pdf"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"{context.run_id}_report.pdf"

        if output_path.exists():
            log.info("report_reusing_artifact", path=str(output_path))
            context.report_path = output_path
            if context.run_result:
                context.run_result._pdf_path = output_path
                context.run_result._pdf_filename = output_path.name
            return StepResult(step_name=self.name, status="success", artifact_path=output_path)

        builder = ReportBuilder()
        meta = builder.build(
            result=context.run_result,
            output_path=output_path,
            config=context.config,
            run_id=context.run_id,
        )
        context.report_path = meta.path
        if context.run_result:
            context.run_result._pdf_path = meta.path
            context.run_result._pdf_filename = meta.path.name
            context.run_result._run_id = context.run_id
        log.info("report_done", path=str(meta.path), pages=meta.page_count)
        return StepResult(step_name=self.name, status="success", artifact_path=meta.path)


class DispatchNotificationsStep(Step):
    name = "dispatch_notifications"
    retryable = False
    critical = False

    def execute(self, context: RunContext) -> StepResult:
        if context.skip_notify or context.dry_run:
            reason = "flag" if context.skip_notify else "dry_run"
            log.info("notify_skipped", reason=reason)
            return StepResult(step_name=self.name, status="skipped")

        from src.notifier import (
            NotificationDispatcher, SMTPEmailChannel, SlackChannel, TeamsChannel
        )
        channels = [
            SMTPEmailChannel(context.config),
            SlackChannel(context.config),
            TeamsChannel(context.config),
        ]
        dispatcher = NotificationDispatcher(channels)
        dispatch_result = dispatcher.send(context.run_result)

        if dispatch_result.all_failed:
            return StepResult(
                step_name=self.name,
                status="failed",
                error="all notification channels failed",
            )

        log.info("notify_done", success=dispatch_result.success, partial=dispatch_result.partial)
        return StepResult(step_name=self.name, status="success")


class CleanupStep(Step):
    name = "cleanup"
    retryable = False
    critical = False

    def execute(self, context: RunContext) -> StepResult:
        keep_days = context.config.get("cleanup", {}).get("keep_raw_days", 7)
        if keep_days <= 0:
            return StepResult(step_name=self.name, status="skipped")

        cutoff = time.time() - (keep_days * 86400)
        removed = 0
        reports_root = Path("reports")
        for d in [
            reports_root / "raw",
            reports_root / "analytics",
            reports_root / "resource",
            reports_root / "email_drafts",
        ]:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        removed += 1
                except Exception:
                    pass

        # Cap run log at 500 entries to prevent unbounded growth
        run_log = reports_root / "run_log.jsonl"
        if run_log.exists():
            try:
                lines = run_log.read_text(encoding="utf-8").splitlines()
                if len(lines) > 500:
                    run_log.write_text("\n".join(lines[-500:]) + "\n", encoding="utf-8")
            except Exception:
                pass

        log.info("cleanup_done", removed=removed)
        return StepResult(step_name=self.name, status="success")
