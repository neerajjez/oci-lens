"""
src/notifier/email_channel.py
==============================
SMTP email delivery channel with STARTTLS/SSL, retries, test mode, and
per-recipient failure handling.
"""
from __future__ import annotations

import csv
import io
import os
import smtplib
import socket
import time
import uuid
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.notifier.base import ChannelResult, NotificationChannel
from src.utils.logger import get_logger

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_MAX_RETRIES = 3
_RETRY_DELAY_S = 30
_CONNECT_TIMEOUT = 60
_SEND_TIMEOUT = 120
_MAX_PDF_ATTACH_BYTES = 180_000   # base64 +33% → ~240 KB encoded; keeps total message under ~256 KB

_SENSITIVE_KEYS = {"smtp_password", "smtp_pass", "password", "token", "secret"}


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


class SMTPEmailChannel(NotificationChannel):
    def __init__(self, config: dict) -> None:
        self._cfg = config.get("email") or {}
        self._jinja = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled", False)) and bool(self._cfg.get("smtp_host"))

    @property
    def channel_name(self) -> str:
        return "email"

    def send(self, run_result: Any) -> ChannelResult:
        if not self.enabled:
            return ChannelResult(channel="email", success=True, message="disabled")

        try:
            msg, to_list = self._build_message(run_result)
        except Exception as exc:
            log.error("email_build_failed", error=str(exc))
            return ChannelResult(channel="email", success=False, message=f"build failed: {exc}")

        test_mode = (
            self._cfg.get("test_mode", False)
            or os.environ.get("EMAIL_TEST_MODE", "").lower() in ("1", "true", "yes")
        )
        if test_mode:
            return self._write_eml(msg, run_result)

        return self._smtp_send(msg, to_list)

    # ── message construction ────────────────────────────────────────────────

    def _build_message(self, run_result: Any) -> tuple[MIMEMultipart, list[str]]:
        kpis = run_result.fleet_kpis
        recs = run_result.recommendations or []
        anomalies = run_result.anomalies or []

        from src.analytics.right_sizer import RecommendationType
        actionable = [
            r for r in recs
            if r.recommendation_type in (RecommendationType.DOWNSIZE, RecommendationType.TERMINATE)
        ]
        actionable.sort(key=lambda r: r.estimated_monthly_savings, reverse=True)
        top_recs = actionable[:5]
        top_anoms = anomalies[:3]

        period_start = run_result.period_start.strftime("%b %d, %Y") if run_result.period_start else "?"
        period_end = run_result.period_end.strftime("%b %d, %Y") if run_result.period_end else "?"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        savings = float(kpis.total_potential_monthly_savings or 0)
        monthly_rate = float(kpis.total_fleet_cost_monthly_run_rate or 0)
        n_anomalies = len(anomalies)
        n_instances = sum(filter(None, [
            kpis.overprovisioned_count, kpis.rightsized_count,
            kpis.underprovisioned_count, kpis.idle_count, kpis.insufficient_data_count,
        ]))

        run_id = getattr(run_result, "_run_id", str(uuid.uuid4())[:8])
        pdf_filename = getattr(run_result, "_pdf_filename", "OCI_Cost_Report.pdf")
        csv_filename = getattr(run_result, "_csv_filename", None)

        ctx = {
            "period_start": period_start,
            "period_end": period_end,
            "generated_at": generated_at,
            "run_id": run_id,
            "total_cost": _fmt(monthly_rate),
            "savings": _fmt(savings),
            "composite_score": f"{float(kpis.weighted_composite_score or 0):.2f}",
            "anomaly_count": n_anomalies,
            "pdf_filename": pdf_filename,
            "pdf_attached": self._cfg.get("attach_pdf", True),
            "csv_filename": csv_filename,
            "top_recommendations": [
                {
                    "name": r.instance_name[:30],
                    "action": r.recommendation_type.value,
                    "savings": _fmt(r.estimated_monthly_savings),
                    "confidence": r.confidence_label.value,
                }
                for r in top_recs
            ],
            "top_anomalies": [
                {
                    "severity": a.severity.value,
                    "signal": a.signal,
                    "description": a.description[:80],
                    "action": a.suggested_action[:80],
                    "recoverable": _fmt(a.estimated_recoverable_amount),
                }
                for a in top_anoms
            ],
        }

        subject = self._build_subject(savings, n_instances, n_anomalies, period_start, period_end)

        html_body = self._jinja.get_template("email_html.j2").render(**ctx)
        text_body = self._jinja.get_template("email_text.j2").render(**ctx)

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{self._cfg.get('from_name', 'OCI Cost Optimizer')} <{self._cfg.get('from_address', '')}>"
        msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        msg["Message-ID"] = f"<oci-cost-{run_id}@optimizer>"
        msg["X-Mailer"] = "OCI-Cost-Optimizer/1.0"
        msg["X-OCI-Run-ID"] = run_id
        msg["Auto-Submitted"] = "auto-generated"

        to_list = list(self._cfg.get("to_addresses") or [])
        cc_list = list(self._cfg.get("cc_addresses") or [])
        bcc_list = list(self._cfg.get("bcc_addresses") or [])
        if to_list:
            msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        if self._cfg.get("reply_to"):
            msg["Reply-To"] = self._cfg["reply_to"]

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt)

        # Attachments
        pdf_path = getattr(run_result, "_pdf_path", None)
        pdf_attached = self._attach_pdf(msg, pdf_path, pdf_filename)
        if not pdf_attached and pdf_path and Path(pdf_path).exists():
            pdf_size_kb = Path(pdf_path).stat().st_size // 1024
            note = (
                f"\n\nNote: The PDF report ({pdf_size_kb} KB) exceeds the mail server attachment "
                f"limit and was not attached. Full report saved to: {pdf_path}"
            )
            # Rebuild alt with the note appended
            html_note = (
                f"<p style='color:#666;font-size:12px;'><strong>Note:</strong> The PDF report "
                f"({pdf_size_kb}&nbsp;KB) exceeds the mail server attachment limit and was not "
                f"attached. Full report saved to: <code>{pdf_path}</code></p>"
            )
            text_body += note
            html_body = html_body.replace("</body>", html_note + "</body>") if "</body>" in html_body else html_body + html_note
            # Replace alt part with updated bodies
            new_alt = MIMEMultipart("alternative")
            new_alt.attach(MIMEText(text_body, "plain", "utf-8"))
            new_alt.attach(MIMEText(html_body, "html", "utf-8"))
            # Remove old alt and reattach
            msg._payload = [p for p in msg._payload if not isinstance(p, MIMEMultipart)]
            msg.attach(new_alt)
        if self._cfg.get("attach_csv", True):
            self._attach_csv(msg, recs, run_id)

        all_recipients = to_list + cc_list + bcc_list
        return msg, all_recipients

    def _build_subject(self, savings: float, n: int, n_anoms: int,
                       start: str, end: str) -> str:
        period = f"{start}–{end}"
        if n_anoms > 0:
            return f"[OCI Cost] WARN {n_anoms} anomalies | ${savings:,.0f}/mo recoverable"
        if savings > 0:
            return f"[OCI Cost] {period}: ${savings:,.0f}/mo recoverable across {n} instances"
        return f"[OCI Cost] {period}: Fleet healthy, {n} instances analyzed"

    def _attach_pdf(self, msg: MIMEMultipart, pdf_path: Optional[Path], filename: str) -> bool:
        """Attach the PDF. Returns True if attached, False if skipped (too large or disabled)."""
        if not self._cfg.get("attach_pdf", True):
            return False
        if not pdf_path or not Path(pdf_path).exists():
            return False
        try:
            with open(pdf_path, "rb") as f:
                data = f.read()
            if len(data) > _MAX_PDF_ATTACH_BYTES:
                log.warning(
                    "pdf_too_large_to_attach",
                    size_kb=len(data) // 1024,
                    limit_kb=_MAX_PDF_ATTACH_BYTES // 1024,
                    path=str(pdf_path),
                )
                return False
            part = MIMEBase("application", "pdf")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
            return True
        except Exception as exc:
            log.warning("pdf_attach_failed", error=str(exc))
            return False

    def _attach_csv(self, msg: MIMEMultipart, recs: list, run_id: str) -> None:
        if not recs:
            return
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "instance_id", "instance_name", "recommendation_type",
                "current_shape", "recommended_shape",
                "current_monthly_cost", "estimated_monthly_savings",
                "savings_pct", "confidence", "risk_level", "rationale",
            ])
            for r in recs:
                writer.writerow([
                    r.instance_id, r.instance_name, r.recommendation_type.value,
                    r.current_shape, r.recommended_shape or "",
                    f"{r.current_monthly_cost:.2f}", f"{r.estimated_monthly_savings:.2f}",
                    f"{r.savings_pct:.1f}", r.confidence_label.value,
                    r.risk_level.value, r.rationale,
                ])
            csv_bytes = buf.getvalue().encode("utf-8")
            part = MIMEBase("text", "csv")
            part.set_payload(csv_bytes)
            encoders.encode_base64(part)
            filename = f"recommendations_{run_id}.csv"
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
        except Exception as exc:
            log.warning("csv_attach_failed", error=str(exc))

    # ── SMTP sending ────────────────────────────────────────────────────────

    def _smtp_send(self, msg: MIMEMultipart, recipients: list[str]) -> ChannelResult:
        smtp_host = self._cfg.get("smtp_host", "")
        smtp_port = int(self._cfg.get("smtp_port", 587))
        encryption = self._cfg.get("encryption", "starttls").lower()
        auth_method = self._cfg.get("auth_method", "login").lower()
        smtp_user = os.environ.get("SMTP_USER") or self._cfg.get("smtp_user", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        verify_tls = self._cfg.get("verify_tls", True)

        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return self._attempt_send(
                    msg, recipients, smtp_host, smtp_port,
                    encryption, auth_method, smtp_user, smtp_password, verify_tls,
                )
            except smtplib.SMTPAuthenticationError as exc:
                log.error("smtp_auth_failed", host=smtp_host)
                return ChannelResult(channel="email", success=False,
                                     message=f"authentication failed: {exc.smtp_error}")
            except (smtplib.SMTPServerDisconnected, socket.timeout, OSError) as exc:
                last_exc = exc
                log.warning("smtp_retry", attempt=attempt, error=str(exc))
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY_S * attempt)
            except Exception as exc:
                last_exc = exc
                log.warning("smtp_retry", attempt=attempt, error=str(exc))
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY_S * attempt)

        log.error("smtp_all_retries_failed", error=str(last_exc))
        return ChannelResult(channel="email", success=False,
                             message=f"all retries failed: {last_exc}")

    def _attempt_send(self, msg, recipients, host, port, encryption,
                      auth_method, user, password, verify_tls) -> ChannelResult:
        import ssl

        ctx = ssl.create_default_context()
        if not verify_tls:
            log.warning("tls_verification_disabled", host=host)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        if encryption == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=_CONNECT_TIMEOUT, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=_CONNECT_TIMEOUT)

        with server:
            server.ehlo()
            if encryption == "starttls":
                server.starttls(context=ctx)
                server.ehlo()
            if auth_method != "none" and user:
                server.login(user, password)

            failed: dict[str, tuple] = {}
            try:
                failed = server.sendmail(
                    self._cfg.get("from_address", ""),
                    recipients,
                    msg.as_bytes(),
                )
            except smtplib.SMTPRecipientsRefused as exc:
                failed = exc.recipients

            server.quit()

        if failed:
            failed_list = list(failed.keys())
            succeeded = [r for r in recipients if r not in failed_list]
            log.warning("smtp_partial_success", failed=failed_list, succeeded=len(succeeded))
            return ChannelResult(
                channel="email",
                success=bool(succeeded),
                partial=True,
                message=f"{len(succeeded)}/{len(recipients)} recipients succeeded",
                failed_recipients=failed_list,
            )

        log.info("smtp_sent", recipients=len(recipients), host=host)
        return ChannelResult(channel="email", success=True,
                             message=f"sent to {len(recipients)} recipients")

    # ── test mode ───────────────────────────────────────────────────────────

    def _write_eml(self, msg: MIMEMultipart, run_result: Any) -> ChannelResult:
        run_id = getattr(run_result, "_run_id", "unknown")
        drafts_dir = Path("reports") / "email_drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        eml_path = drafts_dir / f"{run_id}.eml"
        eml_path.write_bytes(msg.as_bytes())
        log.info("email_test_mode_eml_written", path=str(eml_path))
        return ChannelResult(channel="email", success=True,
                             message=f"test mode: wrote {eml_path}")
