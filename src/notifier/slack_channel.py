"""
src/notifier/slack_channel.py
==============================
Optional Slack Block Kit notification via incoming webhook.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from src.notifier.base import ChannelResult, NotificationChannel
from src.utils.logger import get_logger

log = get_logger(__name__)


class SlackChannel(NotificationChannel):
    def __init__(self, config: dict) -> None:
        self._cfg = config.get("slack") or {}
        self._webhook = os.environ.get("SLACK_WEBHOOK_URL") or self._cfg.get("webhook_url", "")

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled", False)) and bool(self._webhook)

    @property
    def channel_name(self) -> str:
        return "slack"

    def send(self, run_result: Any) -> ChannelResult:
        if not self.enabled:
            return ChannelResult(channel="slack", success=True, message="disabled")

        kpis = run_result.fleet_kpis
        savings = float(kpis.total_potential_monthly_savings or 0)
        monthly_rate = float(kpis.total_fleet_cost_monthly_run_rate or 0)
        n_anomalies = len(run_result.anomalies or [])
        run_id = getattr(run_result, "_run_id", "?")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "OCI Cloud Cost Optimization Report"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Monthly Run Rate*\n${monthly_rate:,.0f}"},
                    {"type": "mrkdwn", "text": f"*Potential Savings*\n${savings:,.0f}/mo"},
                    {"type": "mrkdwn", "text": f"*Anomalies*\n{n_anomalies}"},
                    {"type": "mrkdwn", "text": f"*Run ID*\n{run_id}"},
                ],
            },
        ]

        recs = run_result.recommendations or []
        from src.analytics.right_sizer import RecommendationType
        top3 = sorted(
            [r for r in recs if r.recommendation_type in (RecommendationType.DOWNSIZE, RecommendationType.TERMINATE)],
            key=lambda r: r.estimated_monthly_savings,
            reverse=True,
        )[:3]
        if top3:
            rec_lines = "\n".join(
                f"• {r.instance_name[:25]} → {r.recommendation_type.value} (${r.estimated_monthly_savings:,.0f}/mo)"
                for r in top3
            )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top Recommendations*\n{rec_lines}"},
            })

        payload = json.dumps({"blocks": blocks}).encode("utf-8")
        try:
            req = urllib.request.Request(
                self._webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    log.info("slack_sent")
                    return ChannelResult(channel="slack", success=True, message="sent")
                body = resp.read().decode()
                log.warning("slack_non_200", status=resp.status, body=body)
                return ChannelResult(channel="slack", success=False, message=f"HTTP {resp.status}")
        except Exception as exc:
            log.error("slack_send_failed", error=str(exc))
            return ChannelResult(channel="slack", success=False, message=str(exc))
