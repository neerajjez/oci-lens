"""
src/notifier/teams_channel.py
==============================
Optional Microsoft Teams Adaptive Card notification via incoming webhook.
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


class TeamsChannel(NotificationChannel):
    def __init__(self, config: dict) -> None:
        self._cfg = config.get("teams") or {}
        self._webhook = os.environ.get("TEAMS_WEBHOOK_URL") or self._cfg.get("webhook_url", "")

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled", False)) and bool(self._webhook)

    @property
    def channel_name(self) -> str:
        return "teams"

    def send(self, run_result: Any) -> ChannelResult:
        if not self.enabled:
            return ChannelResult(channel="teams", success=True, message="disabled")

        kpis = run_result.fleet_kpis
        savings = float(kpis.total_potential_monthly_savings or 0)
        monthly_rate = float(kpis.total_fleet_cost_monthly_run_rate or 0)
        n_anomalies = len(run_result.anomalies or [])
        run_id = getattr(run_result, "_run_id", "?")

        facts = [
            {"title": "Monthly Run Rate", "value": f"${monthly_rate:,.0f}"},
            {"title": "Potential Savings", "value": f"${savings:,.0f}/mo"},
            {"title": "Anomalies", "value": str(n_anomalies)},
            {"title": "Run ID", "value": run_id},
        ]

        body: list[dict] = [
            {
                "type": "TextBlock",
                "text": "OCI Cloud Cost Optimization Report",
                "weight": "Bolder",
                "size": "Large",
                "color": "Accent",
            },
            {
                "type": "FactSet",
                "facts": facts,
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
            body.append({
                "type": "TextBlock",
                "text": "Top Recommendations",
                "weight": "Bolder",
                "size": "Medium",
                "spacing": "Medium",
            })
            for r in top3:
                body.append({
                    "type": "TextBlock",
                    "text": f"• {r.instance_name[:30]} → {r.recommendation_type.value} (${r.estimated_monthly_savings:,.0f}/mo)",
                    "wrap": True,
                    "size": "Small",
                })

        if n_anomalies > 0:
            body.append({
                "type": "TextBlock",
                "text": f"\u26a0 {n_anomalies} anomal{'y' if n_anomalies == 1 else 'ies'} detected",
                "color": "Attention",
                "weight": "Bolder",
                "spacing": "Medium",
            })

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                    },
                }
            ],
        }

        payload = json.dumps(card).encode("utf-8")
        try:
            req = urllib.request.Request(
                self._webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                if resp.status == 200:
                    log.info("teams_sent")
                    return ChannelResult(channel="teams", success=True, message="sent")
                body_text = resp_body.decode(errors="replace")
                log.warning("teams_non_200", status=resp.status, body=body_text)
                return ChannelResult(channel="teams", success=False, message=f"HTTP {resp.status}")
        except Exception as exc:
            log.error("teams_send_failed", error=str(exc))
            return ChannelResult(channel="teams", success=False, message=str(exc))
