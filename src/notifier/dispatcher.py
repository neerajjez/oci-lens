"""
src/notifier/dispatcher.py
===========================
Parallel notification dispatcher with per-channel timeout and escalation.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.notifier.base import ChannelResult, DispatchResult, NotificationChannel
from src.utils.logger import get_logger

log = get_logger(__name__)

_CHANNEL_TIMEOUT_S = 180
_REPORTS_DIR = Path("reports")


class NotificationDispatcher:
    def __init__(
        self,
        channels: list[NotificationChannel],
        channel_timeout_s: int = _CHANNEL_TIMEOUT_S,
    ) -> None:
        self._channels = channels
        self._timeout = channel_timeout_s

    def send(self, run_result: Any) -> DispatchResult:
        active = [ch for ch in self._channels if ch.enabled]
        if not active:
            log.info("dispatcher_no_active_channels")
            return DispatchResult(success=True, partial=False, channel_results=[])

        results: list[ChannelResult] = []

        with ThreadPoolExecutor(max_workers=len(active), thread_name_prefix="notifier") as pool:
            future_to_channel = {
                pool.submit(ch.send, run_result): ch for ch in active
            }
            for future in as_completed(future_to_channel, timeout=self._timeout * len(active)):
                ch = future_to_channel[future]
                try:
                    result = future.result(timeout=self._timeout)
                    results.append(result)
                    log.info(
                        "channel_dispatched",
                        channel=ch.channel_name,
                        success=result.success,
                        partial=result.partial,
                    )
                except FuturesTimeoutError:
                    log.error("channel_timeout", channel=ch.channel_name)
                    results.append(ChannelResult(
                        channel=ch.channel_name,
                        success=False,
                        message="timeout",
                    ))
                except Exception as exc:
                    log.error("channel_exception", channel=ch.channel_name, error=str(exc))
                    results.append(ChannelResult(
                        channel=ch.channel_name,
                        success=False,
                        message=str(exc),
                    ))

        any_success = any(r.success or r.partial for r in results)
        any_partial = any(r.partial for r in results)

        dispatch = DispatchResult(
            success=any_success,
            partial=any_partial,
            channel_results=results,
        )

        if dispatch.all_failed:
            self._escalate(run_result, results)

        return dispatch

    def _escalate(self, run_result: Any, results: list[ChannelResult]) -> None:
        run_id = getattr(run_result, "_run_id", "unknown")
        log.error("all_channels_failed", run_id=run_id)

        failure_path = _REPORTS_DIR / f"CRITICAL_DELIVERY_FAILURE_{run_id}.json"
        try:
            _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "channel_results": [
                    {
                        "channel": r.channel,
                        "success": r.success,
                        "partial": r.partial,
                        "message": r.message,
                        "failed_recipients": r.failed_recipients,
                    }
                    for r in results
                ],
            }
            failure_path.write_text(json.dumps(payload, indent=2))
            log.error("critical_failure_written", path=str(failure_path))
        except Exception as exc:
            log.error("critical_failure_write_error", error=str(exc))

        self._attempt_fallback(run_result, results)

    def _attempt_fallback(self, run_result: Any, results: list[ChannelResult]) -> None:
        """Best-effort minimal email to fallback_address when all channels have failed."""
        fallback_addr: Optional[str] = None
        for ch in self._channels:
            cfg = getattr(ch, "_cfg", {})
            fallback_addr = cfg.get("fallback_address")
            if fallback_addr:
                break

        if not fallback_addr:
            return

        from src.notifier.email_channel import SMTPEmailChannel

        for ch in self._channels:
            if isinstance(ch, SMTPEmailChannel) and ch._cfg.get("smtp_host"):
                fallback_cfg = dict(ch._cfg)
                fallback_cfg["to_addresses"] = [fallback_addr]
                fallback_cfg["cc_addresses"] = []
                fallback_cfg["bcc_addresses"] = []
                try:
                    fallback_ch = SMTPEmailChannel({"email": fallback_cfg})
                    result = fallback_ch.send(run_result)
                    log.info("fallback_send_result", success=result.success, message=result.message)
                except Exception as exc:
                    log.error("fallback_send_failed", error=str(exc))
                return
