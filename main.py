from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass as _dc
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from src.analytics.engine import AnalyticsEngine, AnalyticsResult
from src.analytics.utilization import UtilizationPattern
from src.collector.compute import collect_instances
from src.collector.cost import collect_costs
from src.collector.oci_client import OciClientFactory
from src.collector.storage import collect_boot_volumes, collect_object_storage, collect_volumes
from src.models.schemas import CollectionResult
from src.utils.date_utils import collection_window, timestamp_slug
from src.utils.logger import get_logger

_ENV_FILE = Path(__file__).parent / ".env"
_CONFIG_FILE = Path(__file__).parent / "config" / "config.yaml"

# ---------------------------------------------------------------------------
# Multi-tenancy config model
# ---------------------------------------------------------------------------

@_dc
class CompartmentConfig:
    id: str
    name: str
    region: str


@_dc
class TenancyConfig:
    name: str
    oci_config_path: str
    oci_profile: str
    home_region: str
    compartments: list


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "default"


def _normalize_tenancies(cfg: dict) -> list:
    """Return list[TenancyConfig] from either new `tenancies` block or legacy flat keys."""
    if "tenancies" in cfg:
        result = []
        for t in cfg["tenancies"]:
            oci_sub = t.get("oci", {})
            config_path = (
                t.get("oci_config_path")
                or oci_sub.get("config_path")
                or os.environ.get("OCI_CONFIG_PATH", "~/.oci/config")
            )
            profile = (
                t.get("oci_profile")
                or oci_sub.get("profile")
                or os.environ.get("OCI_PROFILE", "DEFAULT")
            )
            home_region = t.get("home_region", "")
            comps = []
            for c in t.get("compartments", []):
                if isinstance(c, str):
                    comps.append(CompartmentConfig(id=c, name=c[-12:], region=home_region))
                else:
                    comps.append(CompartmentConfig(
                        id=c["id"],
                        name=c.get("name", c["id"][-12:]),
                        region=c.get("region", home_region),
                    ))
            result.append(TenancyConfig(
                name=t.get("name", "default"),
                oci_config_path=config_path,
                oci_profile=profile,
                home_region=home_region,
                compartments=comps,
            ))
        return result

    # Legacy flat format → single TenancyConfig
    oci_cfg = cfg.get("oci", {})
    config_path = os.environ.get("OCI_CONFIG_PATH") or oci_cfg.get("config_path", "~/.oci/config")
    profile = os.environ.get("OCI_PROFILE") or oci_cfg.get("profile", "DEFAULT")
    regions = cfg.get("regions", [])
    home_region = regions[0] if regions else ""
    comps = [
        CompartmentConfig(id=ocid, name=_slugify(ocid[-16:]), region=home_region)
        for ocid in (cfg.get("compartments") or [])
    ]
    return [TenancyConfig(
        name="default",
        oci_config_path=config_path,
        oci_profile=profile,
        home_region=home_region,
        compartments=comps,
    )]


def _load_env() -> None:
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE)


def _load_config(path: Path) -> dict:
    try:
        with path.open() as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        print(f"Error: invalid YAML in {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: cannot read config {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def validate_config(cfg: dict, dry_run: bool = False) -> None:
    errors: list[str] = []

    if "tenancies" in cfg:
        for i, t in enumerate(cfg["tenancies"]):
            if not t.get("oci_config_path") and not t.get("oci", {}).get("config_path"):
                errors.append(f"tenancies[{i}].oci_config_path: required")
            if not t.get("home_region"):
                errors.append(f"tenancies[{i}].home_region: required")
            comps = t.get("compartments") or []
            if not comps:
                errors.append(f"tenancies[{i}].compartments: must have at least one entry")
            for j, c in enumerate(comps):
                if isinstance(c, dict):
                    if not c.get("id"):
                        errors.append(f"tenancies[{i}].compartments[{j}].id: required")
                    if not c.get("region"):
                        errors.append(f"tenancies[{i}].compartments[{j}].region: required")
    else:
        compartments = cfg.get("compartments") or []
        if not compartments:
            errors.append("compartments: list must contain at least one compartment OCID")
        regions = cfg.get("regions") or []
        if not regions:
            errors.append("regions: list must contain at least one region")
        oci_cfg = cfg.get("oci") or {}
        if not oci_cfg.get("config_path") and not os.environ.get("OCI_CONFIG_PATH"):
            errors.append("oci.config_path: required (or set OCI_CONFIG_PATH env var)")

    report_cfg = cfg.get("report") or {}
    if not report_cfg.get("output_dir"):
        errors.append("report.output_dir: required")

    if not dry_run:
        email_cfg = cfg.get("email") or {}
        auth_method = str(email_cfg.get("auth_method", "login")).lower()
        if email_cfg.get("smtp_host") and auth_method != "none" and not os.environ.get("SMTP_PASSWORD"):
            errors.append("email.smtp_host is set but SMTP_PASSWORD env var is missing")

    if errors:
        print("Configuration validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


class _DatetimeEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _to_json_serializable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_json_serializable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_json_serializable(i) for i in obj]
    return obj


def _write_raw(
    result: CollectionResult,
    output_dir: Path,
    tenancy_slug: str = "",
    comp_slug: str = "",
    ts: str = "",
) -> Path:
    raw_dir = output_dir / "raw"
    if tenancy_slug:
        raw_dir = raw_dir / tenancy_slug
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = ts or timestamp_slug()
    prefix = f"{comp_slug}_" if comp_slug else ""
    out_file = raw_dir / f"{prefix}{ts}_raw.json"
    payload = _to_json_serializable(result)
    with out_file.open("w") as fh:
        json.dump(payload, fh, indent=2, cls=_DatetimeEncoder)
    try:
        os.chmod(out_file, 0o640)
    except OSError:
        pass
    return out_file


def cmd_collect(args: argparse.Namespace) -> None:
    _load_env()
    cfg = _load_config(_CONFIG_FILE)
    validate_config(cfg, dry_run=args.dry_run)

    log = get_logger("main")
    _collect_t0 = time.monotonic()
    log.info("collection_starting", dry_run=args.dry_run)

    period_days: int = cfg.get("collection_period_days", 15)
    interval_minutes: int = cfg.get("metrics_interval_minutes", 60)
    start, end = collection_window(period_days)
    log.info("collection_window", start=start.isoformat(), end=end.isoformat(), period_days=period_days)

    report_cfg = cfg.get("report", {})
    output_dir = Path(report_cfg.get("output_dir", "./reports"))

    tenancies = _normalize_tenancies(cfg)

    # Optional filters
    _tenancy_filter = _slugify(args.tenancy) if getattr(args, "tenancy", None) else None
    _comp_filter = _slugify(args.compartment) if getattr(args, "compartment", None) else None
    if _tenancy_filter:
        tenancies = [t for t in tenancies if _slugify(t.name) == _tenancy_filter]
    if _comp_filter:
        for t in tenancies:
            t.compartments = [c for c in t.compartments if _slugify(c.name) == _comp_filter]
        tenancies = [t for t in tenancies if t.compartments]

    run_ts = timestamp_slug()  # shared timestamp across all compartments this run

    total_instances = total_volumes = total_boot = total_os = total_costs = 0
    written_files: list[Path] = []

    for tenancy in tenancies:
        t_slug = _slugify(tenancy.name)
        log.info("tenancy_start", tenancy=tenancy.name, compartments=len(tenancy.compartments))

        factory: OciClientFactory | None = None
        if not args.dry_run:
            factory = OciClientFactory(tenancy.oci_config_path, tenancy.oci_profile)

        # Collect costs once per tenancy (cost API is per-tenancy, home-region only)
        tenancy_costs: list = []
        if not args.dry_run and tenancy.compartments:
            log.info("phase_start", phase="collect_costs", tenancy=tenancy.name)
            t_cost = time.monotonic()
            tenant_id = _resolve_tenant_id(tenancy.oci_config_path, tenancy.oci_profile)
            comp_ids = [c.id for c in tenancy.compartments]
            tenancy_costs = collect_costs(
                factory, tenant_id, comp_ids, start, end,
                dry_run=False, home_region=tenancy.home_region,
            )
            log.info("phase_done", phase="collect_costs", count=len(tenancy_costs),
                     elapsed_s=round(time.monotonic() - t_cost, 1))

        for comp in tenancy.compartments:
            if _shutdown_requested:
                log.warning("shutdown_requested_stopping_collection")
                break
            c_slug = _slugify(comp.name)
            log.info("compartment_start", tenancy=tenancy.name, compartment=comp.name, region=comp.region)

            instances: list = []
            volumes: list = []
            boot_vols: list = []
            os_buckets: list = []

            if not args.dry_run:
                t0 = time.monotonic()
                instances = collect_instances(
                    factory, comp.id, comp.region, start, end, interval_minutes, dry_run=False
                )
                log.info("phase_done", phase="collect_instances", count=len(instances),
                         elapsed_s=round(time.monotonic() - t0, 1))

                t0 = time.monotonic()
                volumes = collect_volumes(
                    factory, comp.id, comp.region, start, end, interval_minutes, dry_run=False
                )
                log.info("phase_done", phase="collect_volumes", count=len(volumes),
                         elapsed_s=round(time.monotonic() - t0, 1))

                t0 = time.monotonic()
                boot_vols = collect_boot_volumes(factory, comp.id, comp.region, dry_run=False)
                log.info("phase_done", phase="collect_boot_volumes", count=len(boot_vols),
                         elapsed_s=round(time.monotonic() - t0, 1))

                t0 = time.monotonic()
                os_buckets = collect_object_storage(factory, comp.id, comp.region, dry_run=False)
                log.info("phase_done", phase="collect_object_storage", count=len(os_buckets),
                         elapsed_s=round(time.monotonic() - t0, 1))
            else:
                log.info("dry_run_skipping_api_calls", tenancy=tenancy.name, compartment=comp.name)

            # Filter tenancy-wide costs down to this compartment
            comp_costs = [c for c in tenancy_costs if c.compartment_id == comp.id]

            result = CollectionResult(
                period_start=start,
                period_end=end,
                regions=[comp.region],
                compartments=[comp.id],
                instances=instances,
                volumes=volumes,
                boot_volumes=boot_vols,
                object_storage_buckets=os_buckets,
                cost_records=comp_costs,
                dry_run=args.dry_run,
                tenancy_name=tenancy.name,
                compartment_name=comp.name,
            )

            out_file = _write_raw(result, output_dir, t_slug, c_slug, run_ts)
            written_files.append(out_file)
            total_instances += len(instances)
            total_volumes   += len(volumes)
            total_boot      += len(boot_vols)
            total_os        += len(os_buckets)
            total_costs     += len(comp_costs)
            log.info("compartment_done", tenancy=tenancy.name, compartment=comp.name,
                     instances=len(instances), file=str(out_file))

    log.info(
        "collection_complete",
        tenancies=len(tenancies),
        files_written=len(written_files),
        instances=total_instances,
        volumes=total_volumes,
        boot_volumes=total_boot,
        object_storage_buckets=total_os,
        cost_records=total_costs,
        dry_run=args.dry_run,
        total_elapsed_s=round(time.monotonic() - _collect_t0, 1),
    )
    for f in written_files:
        print(f"Raw output: {f}")


def _print_analytics_summary(result: AnalyticsResult, output_path: Path) -> None:
    """Print a formatted cost optimization summary report to stdout."""
    kpis = result.fleet_kpis
    period_start = result.period_start
    period_end = result.period_end
    collection_period_days = max(1, (period_end - period_start).days)
    generated_at = result.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    print("=== OCI Cloud Cost Optimization Report ===")
    print(
        f"Period: {period_start.date()} → {period_end.date()}"
        f"  |  {collection_period_days} days"
    )
    print(f"Generated: {generated_at}")
    print()

    print("── FINANCIAL SUMMARY ─" + "─" * 50)
    total_period = getattr(kpis, "total_fleet_cost_period", 0.0) or 0.0
    monthly_rate = getattr(kpis, "total_fleet_cost_monthly_run_rate", 0.0) or 0.0
    orphaned = getattr(kpis, "orphaned_resource_cost", 0.0) or 0.0
    pot_savings = getattr(kpis, "total_potential_monthly_savings", 0.0) or 0.0
    savings_pct = getattr(kpis, "savings_opportunity_pct", 0.0) or 0.0
    net_savings = getattr(kpis, "net_recoverable_savings", 0.0) or 0.0

    print(f"  Fleet cost (period):           ${total_period:>12,.2f}")
    print(f"  Monthly run rate:              ${monthly_rate:>12,.2f}")
    print(f"  Orphaned resource cost:        ${orphaned:>12,.2f}")
    print(f"  Potential monthly savings:     ${pot_savings:>12,.2f}  ({savings_pct:.1f}%)")
    print(f"  Net recoverable savings:       ${net_savings:>12,.2f}  (after ~$50/instance toil)")
    print()

    print("── UTILIZATION SUMMARY ─" + "─" * 48)
    cpu_util = getattr(kpis, "fleet_avg_cpu_utilization", 0.0) or 0.0
    mem_util = getattr(kpis, "fleet_avg_memory_utilization", None)
    mem_str = f"{mem_util:.1f}%" if mem_util is not None else "N/A"
    cost_eff = getattr(kpis, "cost_efficiency_index", 0.0) or 0.0
    wtd_score = getattr(kpis, "weighted_composite_score", 0.0) or 0.0

    print(f"  Fleet avg CPU (p95, cost-wtd): {cpu_util:>8.1f}%")
    print(f"  Fleet avg Memory (cost-wtd):   {mem_str:>8}")
    print(f"  Cost efficiency index:         {cost_eff:>8.3f}  (0=all waste, 1=fully utilized)")
    print(f"  Weighted composite score:      {wtd_score:>8.3f}")
    print()

    print("── FLEET DISTRIBUTION ─" + "─" * 49)
    overprov = getattr(kpis, "overprovisioned_count", 0) or 0
    rightsz = getattr(kpis, "rightsized_count", 0) or 0
    underprov = getattr(kpis, "underprovisioned_count", 0) or 0
    idle = getattr(kpis, "idle_count", 0) or 0
    insuff = getattr(kpis, "insufficient_data_count", 0) or 0

    print(f"  Over-provisioned (< 0.30):     {overprov:>4}")
    print(f"  Right-sized     (0.30–0.70):   {rightsz:>4}")
    print(f"  Under-provisioned (≥ 0.70):    {underprov:>4}")
    print(f"  Idle / zombie:                 {idle:>4}")
    print(f"  Insufficient data:             {insuff:>4}")
    print()

    print("── TOP RECOMMENDATIONS ─" + "─" * 48)
    sorted_recs = sorted(
        result.recommendations,
        key=lambda r: getattr(r, "estimated_monthly_savings", 0.0) or 0.0,
        reverse=True,
    )[:10]
    if sorted_recs:
        for i, rec in enumerate(sorted_recs):
            name = getattr(rec, "resource_name", getattr(rec, "instance_name", ""))
            rtype = getattr(rec, "recommendation_type", "")
            rtype_val = rtype.value if hasattr(rtype, "value") else str(rtype)
            savings = getattr(rec, "estimated_monthly_savings", 0.0) or 0.0
            conf = getattr(rec, "confidence", None)
            conf_label = ""
            if conf is not None:
                lbl = getattr(conf, "label", conf)
                conf_label = lbl.value if hasattr(lbl, "value") else str(lbl)
            print(
                f"  {i + 1:>2}. {name:<30} {rtype_val:<22} ${savings:>8,.2f}/mo"
                f"  {conf_label} confidence"
            )
    else:
        print("  (no recommendations)")
    print()

    print("── TOP ANOMALIES ─" + "─" * 54)
    top_anomalies = result.anomalies[:5]
    if top_anomalies:
        for i, anom in enumerate(top_anomalies):
            sev = anom.severity.value.upper() if hasattr(anom.severity, "value") else str(anom.severity).upper()
            amount = anom.estimated_recoverable_amount
            print(f"  {i + 1}. [{sev}] {anom.signal}: {anom.description}")
            print(f"       Action: {anom.suggested_action}")
            print(f"       Recoverable: ${amount:.2f}")
    else:
        print("  (no anomalies detected)")
    print()

    print("── VALIDATION ─" + "─" * 57)
    print(f"  {result.validation_report.summary()}")
    print()
    print(f"Full analytics report: {output_path}")


def _print_explain(
    result: AnalyticsResult,
    instance_id: str,
    instances_df,
    utilization_df,
) -> None:
    """Print a detailed explanation for a single instance."""
    # Find the recommendation for this instance
    rec = None
    for r in result.recommendations:
        rid = getattr(r, "instance_id", getattr(r, "resource_id", ""))
        if rid == instance_id:
            rec = r
            break

    # Find instance row
    inst_row = None
    if instances_df is not None and not instances_df.empty:
        matches = instances_df[instances_df["instance_id"] == instance_id]
        if not matches.empty:
            inst_row = matches.iloc[0]

    # Find utilization row
    util_row = None
    if utilization_df is not None and not utilization_df.empty and "instance_id" in utilization_df.columns:
        matches = utilization_df[utilization_df["instance_id"] == instance_id]
        if not matches.empty:
            util_row = matches.iloc[0]

    instance_name = instance_id
    shape = "unknown"
    region = "unknown"
    if inst_row is not None:
        instance_name = str(inst_row.get("display_name", instance_id))
        shape = str(inst_row.get("shape", "unknown"))
        region = str(inst_row.get("region", "unknown"))

    print(f"=== Recommendation Explanation: {instance_name} ===")
    print(f"Instance ID: {instance_id}")
    print(f"Shape:       {shape}")
    print(f"Region:      {region}")
    print()

    if util_row is not None:
        pattern = str(util_row.get("pattern", "UNKNOWN"))
        cpu_p25 = float(util_row.get("cpu_p25", 0.0) or 0.0)
        cpu_p50 = float(util_row.get("cpu_p50", 0.0) or 0.0)
        cpu_p75 = float(util_row.get("cpu_p75", 0.0) or 0.0)
        cpu_p95 = float(util_row.get("cpu_p95", 0.0) or 0.0)
        cpu_p99 = float(util_row.get("cpu_p99", 0.0) or 0.0)
        cpu_max = float(util_row.get("cpu_max", 0.0) or 0.0)
        mem_p25 = float(util_row.get("memory_p25", 0.0) or 0.0)
        mem_p50 = float(util_row.get("memory_p50", 0.0) or 0.0)
        mem_p95 = float(util_row.get("memory_p95", 0.0) or 0.0)
        has_memory = bool(util_row.get("has_memory_data", False))
        net_in_p95 = float(util_row.get("network_in_p95", 0.0) or 0.0)
        composite_score = float(util_row.get("composite_score", 0.0) or 0.0)
        cpu_score = float(util_row.get("cpu_score", 0.0) or 0.0)
        memory_score = float(util_row.get("memory_score", 0.0) or 0.0)
        io_score = float(util_row.get("io_score", 0.0) or 0.0)
        io_pct = float(util_row.get("io_utilization_pct", 0.0) or 0.0)
        mem_p95_val = float(util_row.get("memory_p95", 0.0) or 0.0)

        print(f"UTILIZATION PATTERN: {pattern}")
        print("  Diagnostic stats:")
        print(
            f"    CPU:    p25={cpu_p25:.1f}%  p50={cpu_p50:.1f}%  "
            f"p75={cpu_p75:.1f}%  p95={cpu_p95:.1f}%  p99={cpu_p99:.1f}%  max={cpu_max:.1f}%"
        )
        mem_avail = "available" if has_memory else "NOT available"
        print(
            f"    Memory: p25={mem_p25:.1f}%  p50={mem_p50:.1f}%  "
            f"p95={mem_p95:.1f}%  ({mem_avail})"
        )
        print(f"    Net in p95: {net_in_p95:.1f} kbps")

        # Show pattern detection rationale
        diff_p95_p25 = cpu_p95 - cpu_p25
        if pattern == "STEADY":
            print(f"    Pattern detection logic: STEADY: p95-p25={diff_p95_p25:.1f}% < 15%")
        elif pattern == "ERRATIC":
            print(f"    Pattern detection logic: ERRATIC: p95-p25={diff_p95_p25:.1f}% >= 40%")
        elif pattern == "SPIKY":
            print(
                f"    Pattern detection logic: SPIKY: p95-p25={diff_p95_p25:.1f}% (15-40% range, "
                f"p95={cpu_p95:.1f}% >= 60%)"
            )
        elif pattern == "IDLE":
            print(f"    Pattern detection logic: IDLE: cpu_p95={cpu_p95:.1f}% < 5%")
        else:
            print(f"    Pattern detection logic: {pattern}")
        print()

        print(f"COMPOSITE SCORE: {composite_score:.3f}")
        mem_note = "used" if has_memory else "skipped — no memory data"
        print(f"  cpu_score    = sigmoid({cpu_p95:.1f}%, target=70%) = {cpu_score:.3f}  [weight 0.45]")
        print(
            f"  memory_score = sigmoid({mem_p95_val:.1f}%, target=70%) = {memory_score:.3f}"
            f"  [weight 0.35]  ({mem_note})"
        )
        print(f"  io_score     = sigmoid({io_pct:.1f}%, target=60%) = {io_score:.3f}  [weight 0.20]")
        # Show composite formula
        if has_memory:
            composite_str = f"0.45*{cpu_score:.3f} + 0.35*{memory_score:.3f} + 0.20*{io_score:.3f}"
        else:
            composite_str = f"(0.45*{cpu_score:.3f} + 0.20*{io_score:.3f}) / 0.65  (memory skipped)"
        print(f"  composite    = {composite_str}  = {composite_score:.3f}")
        print()
    else:
        print("UTILIZATION PATTERN: (no utilization data available)")
        print()

    if rec is not None:
        rtype = getattr(rec, "recommendation_type", "")
        rtype_val = rtype.value if hasattr(rtype, "value") else str(rtype)
        rationale = getattr(rec, "rationale", "")
        current_shape = getattr(rec, "current_shape", shape)
        recommended_shape = getattr(rec, "recommended_shape", "")
        savings = getattr(rec, "estimated_monthly_savings", 0.0) or 0.0
        prereqs = getattr(rec, "prerequisites", []) or []
        rejected = getattr(rec, "rejected_alternatives", []) or []
        conf = getattr(rec, "confidence", None)

        print(f"RECOMMENDATION: {rtype_val}")
        print(f"  Current shape:    {current_shape}")
        if recommended_shape:
            print(f"  Recommended shape: {recommended_shape}")
        print(f"  Estimated monthly savings: ${savings:,.2f}")
        print(f"  Rationale: {rationale}")
        print()

        if rejected:
            print("  Alternatives considered:")
            for alt in rejected:
                alt_shape = getattr(alt, "shape", str(alt))
                alt_reason = getattr(alt, "reason", "")
                print(f"    - {alt_shape}: {alt_reason}")
            print()

        if conf is not None:
            lbl = getattr(conf, "label", None)
            lbl_val = lbl.value if hasattr(lbl, "value") else str(lbl)
            score = getattr(conf, "score", 0.0) or 0.0
            penalties = getattr(conf, "penalties", []) or []
            bonuses = getattr(conf, "bonuses", []) or []
            print(f"CONFIDENCE: {lbl_val} ({score:.2f})")
            for p in penalties:
                print(f"  Penalty: {p}")
            for b in bonuses:
                print(f"  Bonus:   {b}")
            print()

        if prereqs:
            print("PREREQUISITES:")
            for j, prereq in enumerate(prereqs, 1):
                print(f"  {j}. {prereq}")
    else:
        print(f"RECOMMENDATION: (no recommendation found for instance {instance_id})")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Run the analytics engine on collected raw data and print a summary report."""
    _load_env()
    cfg = _load_config(args.config if hasattr(args, "config") and args.config else _CONFIG_FILE)

    log = get_logger("main.analyze")

    # --- Determine input path ---
    raw_data_path: Path
    if args.input:
        raw_data_path = Path(args.input)
    else:
        # Auto-detect latest *_raw.json under reports/raw/
        report_cfg = cfg.get("report", {})
        output_dir = Path(report_cfg.get("output_dir", "./reports"))
        raw_dir = output_dir / "raw"
        if not raw_dir.exists():
            print(f"Error: raw data directory not found: {raw_dir}", file=sys.stderr)
            sys.exit(1)
        raw_files = sorted(raw_dir.glob("*_raw.json"))
        if not raw_files:
            print(f"Error: no *_raw.json files found in {raw_dir}", file=sys.stderr)
            sys.exit(1)
        raw_data_path = raw_files[-1]
        log.info("auto_detected_input", path=str(raw_data_path))

    if not raw_data_path.exists():
        print(f"Error: input file not found: {raw_data_path}", file=sys.stderr)
        sys.exit(1)

    # --- Build engine ---
    engine = AnalyticsEngine(config=cfg)

    # --- Validate-only mode ---
    if args.validate_only:
        from src.analytics.loader import load_raw
        _, _, _, _, _, validation_report = load_raw(raw_data_path, cfg)
        print("=== Validation Report ===")
        print(validation_report.summary())
        if validation_report.violations:
            print("\nViolations:")
            for v in validation_report.violations:
                print(f"  [{v.record_type}] {v.record_id} — {v.field}: {v.reason}")
        if validation_report.currencies_missing_rates:
            print("\nMissing FX rates for currencies:", ", ".join(validation_report.currencies_missing_rates))
        sys.exit(0 if validation_report.passed else 1)

    # --- Run full pipeline ---
    previous_run_path: Optional[Path] = None
    if hasattr(args, "previous") and args.previous:
        previous_run_path = Path(args.previous)

    result = engine.run(raw_data_path, previous_run_path=previous_run_path)

    # --- Write full JSON output ---
    report_cfg = cfg.get("report", {})
    output_dir = Path(report_cfg.get("output_dir", "./reports"))
    analytics_dir = output_dir / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)

    from src.utils.date_utils import timestamp_slug
    out_file = analytics_dir / f"{timestamp_slug()}_analytics.json"
    out_file.write_text(engine.to_json(result), encoding="utf-8")
    log.info("analytics_output_written", path=str(out_file))

    # --- Explain mode ---
    if args.explain:
        # Re-load DataFrames for explain detail (engine already ran, re-use result)
        from src.analytics.loader import load_raw
        from src.analytics.utilization import profile_utilization
        instances_df, metrics_df, _, _, _, _ = load_raw(raw_data_path, cfg)
        utilization_df = profile_utilization(instances_df, metrics_df)
        _print_explain(result, args.explain, instances_df, utilization_df)
        return

    # --- Print summary ---
    _print_analytics_summary(result, out_file)


def _resolve_tenant_id(config_path: str, profile: str) -> str:
    try:
        import oci
        cfg = oci.config.from_file(file_location=config_path, profile_name=profile)
        return cfg.get("tenancy", "")
    except Exception:
        return os.environ.get("OCI_TENANCY_ID", "")


def cmd_report(args: argparse.Namespace) -> None:
    """Generate a PDF report from an analytics JSON file."""
    _load_env()
    cfg = _load_config(args.config if hasattr(args, "config") and args.config else _CONFIG_FILE)
    log = get_logger("main.report")

    from src.reporter.builder import ReportBuilder
    from src.utils.date_utils import timestamp_slug

    # Determine input analytics file
    if args.analytics:
        analytics_path = Path(args.analytics)
    else:
        report_cfg = cfg.get("report", {})
        output_dir = Path(report_cfg.get("output_dir", "./reports"))
        analytics_dir = output_dir / "analytics"
        if not analytics_dir.exists():
            print(f"Error: analytics directory not found: {analytics_dir}", file=sys.stderr)
            sys.exit(1)
        analytics_files = sorted(analytics_dir.glob("*_analytics.json"))
        if not analytics_files:
            print(f"Error: no *_analytics.json files found in {analytics_dir}", file=sys.stderr)
            sys.exit(1)
        analytics_path = analytics_files[-1]
        log.info("auto_detected_analytics", path=str(analytics_path))

    if not analytics_path.exists():
        print(f"Error: analytics file not found: {analytics_path}", file=sys.stderr)
        sys.exit(1)

    # Load analytics result
    import json
    from dataclasses import asdict
    from src.analytics.engine import AnalyticsEngine

    engine = AnalyticsEngine(config=cfg)

    # Re-run analysis to get the typed AnalyticsResult
    # Or load from the JSON file if raw_input_path is stored in it
    analytics_data = json.loads(analytics_path.read_text(encoding="utf-8"))
    raw_input_path = analytics_data.get("raw_input_path")
    if raw_input_path and Path(raw_input_path).exists():
        result = engine.run(Path(raw_input_path))
    else:
        # Try to find the raw file automatically
        report_cfg = cfg.get("report", {})
        output_dir = Path(report_cfg.get("output_dir", "./reports"))
        raw_dir = output_dir / "raw"
        raw_files = sorted(raw_dir.glob("*_raw.json")) if raw_dir.exists() else []
        if raw_files:
            result = engine.run(raw_files[-1])
        else:
            print("Error: cannot find raw data file to re-run analytics", file=sys.stderr)
            sys.exit(1)

    # Determine output path — mirrors resource report: reports/cost/{tenancy}/{compartment}_{ts}.pdf
    report_cfg = cfg.get("report", {})
    output_dir = Path(report_cfg.get("output_dir", "./reports"))
    gen_ts = timestamp_slug()
    if args.output:
        out_path = Path(args.output)
    else:
        t_slug = _slugify(result.tenancy_name)    if result.tenancy_name    else "oci"
        c_slug = _slugify(result.compartment_name) if result.compartment_name else "all"
        sub = output_dir / "cost" / t_slug
        sub.mkdir(parents=True, exist_ok=True)
        out_path = sub / f"{c_slug}_cost_report_{gen_ts}.pdf"
        # Remove stale PDFs for this compartment (keep only the current run)
        for old_pdf in sub.glob(f"{c_slug}_cost_report_*.pdf"):
            if old_pdf != out_path:
                old_pdf.unlink(missing_ok=True)

    page_size = getattr(args, "page_size", "A4") or "A4"

    builder = ReportBuilder()
    meta = builder.build(result, out_path, page_size=page_size, config=cfg)

    size_kb = meta.file_size_bytes / 1024
    label = (
        f"{result.tenancy_name} / {result.compartment_name}"
        if result.tenancy_name else str(out_path.name)
    )
    print(f"[{label}]  {meta.path}  ({size_kb:.0f} KB, {meta.page_count} pages)")

    if not getattr(args, "skip_notify", False):
        # Find latest resource report PDF for the same compartment (if any) to attach both
        resource_pdf: Path | None = None
        if result.tenancy_name and result.compartment_name:
            t_slug2 = _slugify(result.tenancy_name)
            c_slug2 = _slugify(result.compartment_name)
            res_dir = output_dir / "resource" / t_slug2
            candidates = sorted(res_dir.glob(f"{c_slug2}_resource_report_*.pdf")) if res_dir.exists() else []
            if candidates:
                resource_pdf = candidates[-1]
        _send_cost_report_email(result, meta, cfg, resource_report_pdf=resource_pdf)


def _send_cost_report_email(result, meta, cfg: dict, resource_report_pdf=None) -> None:
    """Send the cost report PDF (+ optional resource report PDF) via SMTP."""
    import smtplib
    import ssl
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from datetime import datetime, timezone

    email_cfg = cfg.get("email") or {}
    if not email_cfg.get("enabled") or not email_cfg.get("smtp_host"):
        return

    _8MB = 8 * 1024 * 1024
    log = get_logger("main.email")

    tenancy    = result.tenancy_name    or "OCI"
    compartment = result.compartment_name or "All"
    try:
        d1 = result.period_start.strftime("%d %b %Y") if result.period_start else ""
        d2 = result.period_end.strftime("%d %b %Y")   if result.period_end   else ""
        date_range = f"{d1} \u2013 {d2}"
        days = max(1, (result.period_end - result.period_start).days) if result.period_start and result.period_end else 30
    except Exception:
        date_range = "—"
        days = 30

    subject = f"OCI Cost Reports | {tenancy} | {compartment} | {date_range}"

    kpis = result.fleet_kpis
    n_instances = (
        (kpis.overprovisioned_count or 0) + (kpis.rightsized_count or 0)
        + (kpis.underprovisioned_count or 0) + (kpis.idle_count or 0)
        + (kpis.insufficient_data_count or 0)
    )

    volumes = result.volumes or []
    boot_count  = sum(1 for v in volumes if "bootvolume" in str(v.get("volume_id") or v.get("ocid") or "").lower())
    block_count = len(volumes) - boot_count
    bucket_count = len(result.buckets or [])

    attachments_note = "the attached Cost Report PDF"
    if resource_report_pdf and resource_report_pdf.exists():
        attachments_note = "the attached Cost Report and Resource Utilisation Report PDFs"

    text_body = (
        f"Hi Team,\n\n"
        f"Please find attached the OCI Cost Report for the following:\n\n"
        f"  Tenancy            : {tenancy}\n"
        f"  Compartment        : {compartment}\n"
        f"  Reporting Period   : {date_range} ({days}-day window)\n"
        f"  Instances Analysed : {n_instances}\n"
        f"  Boot Volumes       : {boot_count}\n"
        f"  Block Volumes      : {block_count}\n"
        f"  Object Storage     : {bucket_count} bucket(s)\n\n"
        f"PFA {attachments_note} for full cost breakdown, storage costs, and right-sizing recommendations.\n\n"
        f"Regards,\n"
        f"OCI Reporting System\n"
        f"(Auto-generated \u2014 please do not reply)"
    )

    html_body = f"""<html>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#1A1A1A;max-width:600px;">
<p>Hi Team,</p>
<p>Please find attached the OCI Cost Report for the following:</p>
<table style="border-collapse:collapse;margin:10px 0 18px 0;">
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Tenancy</td><td style="padding:4px 0;">{tenancy}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Compartment</td><td style="padding:4px 0;">{compartment}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Reporting Period</td><td style="padding:4px 0;">{date_range} &nbsp;({days}-day window)</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Instances Analysed</td><td style="padding:4px 0;">{n_instances}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Boot Volumes</td><td style="padding:4px 0;">{boot_count}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Block Volumes</td><td style="padding:4px 0;">{block_count}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Object Storage</td><td style="padding:4px 0;">{bucket_count} bucket(s)</td></tr>
</table>
<p>PFA {attachments_note} for full cost breakdown, storage costs, and right-sizing recommendations.</p>
<hr style="border:none;border-top:1px solid #E5E5E5;margin:20px 0 12px 0;">
<p style="color:#9A9A9A;font-size:11px;">
  OCI Reporting System &mdash; Auto-generated, please do not reply.
</p>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"OCI Reports <{email_cfg.get('from_address', '')}>"
    msg["To"]      = ", ".join(email_cfg.get("to_addresses") or [])
    msg["Date"]    = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    def _attach_pdf(path: Path, label: str) -> None:
        if not path or not path.exists():
            return
        pdf_size = path.stat().st_size
        if pdf_size <= _8MB:
            part = MIMEApplication(path.read_bytes(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)
        else:
            log.warning("pdf_exceeds_limit", label=label, size_mb=round(pdf_size / 1_048_576, 1))
            print(f"  Warning: {label} PDF {pdf_size/1_048_576:.1f} MB — skipped.", file=sys.stderr)

    _attach_pdf(meta.path, "Cost Report")
    if resource_report_pdf:
        _attach_pdf(resource_report_pdf, "Resource Report")

    recipients = list(email_cfg.get("to_addresses") or [])
    cc = list(email_cfg.get("cc_addresses") or [])
    if cc:
        msg["Cc"] = ", ".join(cc)
        recipients += cc

    if not recipients:
        log.warning("no_recipients_configured")
        return

    smtp_host   = email_cfg.get("smtp_host", "")
    smtp_port   = int(email_cfg.get("smtp_port", 587))
    encryption  = email_cfg.get("encryption", "none").lower()
    auth_method = email_cfg.get("auth_method", "none").lower()
    smtp_user   = os.environ.get("SMTP_USER") or email_cfg.get("smtp_user", "")
    smtp_pass   = os.environ.get("SMTP_PASSWORD", "")

    try:
        if encryption == "ssl":
            ctx = ssl.create_default_context()
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60, context=ctx)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=60)
        with server:
            server.ehlo()
            if encryption == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if auth_method != "none" and smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log.info("cost_report_email_sent", tenancy=tenancy, compartment=compartment,
                 with_resource=resource_report_pdf is not None)
        print(f"  Emailed: {subject}")
    except Exception as exc:
        log.error("cost_report_email_failed", error=str(exc))
        print(f"  Email failed ({compartment}): {exc}", file=sys.stderr)


def _send_resource_report_email(fleet, meta, cfg: dict) -> None:
    """Send one compartment resource-report PDF via SMTP with a professional body."""
    import smtplib
    import ssl
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from datetime import date, datetime, timezone

    email_cfg = cfg.get("email") or {}
    if not email_cfg.get("enabled") or not email_cfg.get("smtp_host"):
        return

    _8MB = 8 * 1024 * 1024
    log = get_logger("main.email")

    tenancy     = fleet.tenancy_name    or "OCI"
    compartment = fleet.compartment_name or "All"
    try:
        d1 = date.fromisoformat(fleet.period_start)
        d2 = date.fromisoformat(fleet.period_end)
        date_range = f"{d1.strftime('%d %b %Y')} \u2013 {d2.strftime('%d %b %Y')}"
    except Exception:
        date_range = f"{fleet.period_start} \u2013 {fleet.period_end}"

    subject = f"OCI Resource Reports | {tenancy} | {compartment} | {date_range}"

    n_inst    = len(fleet.instances)
    n_run     = len(fleet.running)
    n_stop    = len(fleet.stopped)
    n_boot    = len(fleet.boot_volumes)
    n_block   = len(fleet.block_volumes)
    n_os      = len(fleet.object_storage)
    days      = fleet.collection_days

    text_body = (
        f"Hi Team,\n\n"
        f"Please find attached the OCI Resource Utilisation Report for the following:\n\n"
        f"  Tenancy            : {tenancy}\n"
        f"  Compartment        : {compartment}\n"
        f"  Reporting Period   : {date_range} ({days}-day window)\n"
        f"  Instances          : {n_inst}  ({n_run} running, {n_stop} stopped)\n"
        f"  Boot Volumes       : {n_boot}\n"
        f"  Block Volumes      : {n_block}\n"
        f"  Object Storage     : {n_os} bucket(s)\n\n"
        f"The report covers per-instance CPU, memory, network, and disk utilisation "
        f"with sizing labels and recommendations.\n\n"
        f"PFA the attached PDF for full details.\n\n"
        f"Regards,\n"
        f"OCI Resource Reporting System\n"
        f"(Auto-generated \u2014 please do not reply)"
    )

    html_body = f"""<html>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#1A1A1A;max-width:600px;">
<p>Hi Team,</p>
<p>Please find attached the OCI Resource Utilisation Report for the following:</p>
<table style="border-collapse:collapse;margin:10px 0 18px 0;">
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Tenancy</td><td style="padding:4px 0;">{tenancy}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Compartment</td><td style="padding:4px 0;">{compartment}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Reporting Period</td><td style="padding:4px 0;">{date_range} &nbsp;({days}-day window)</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Instances</td><td style="padding:4px 0;">{n_inst} &nbsp;<span style="color:#9A9A9A;">({n_run} running, {n_stop} stopped)</span></td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Boot Volumes</td><td style="padding:4px 0;">{n_boot}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Block Volumes</td><td style="padding:4px 0;">{n_block}</td></tr>
  <tr><td style="padding:4px 20px 4px 0;color:#555;font-weight:bold;">Object Storage</td><td style="padding:4px 0;">{n_os} bucket(s)</td></tr>
</table>
<p>The report covers per-instance CPU, memory, network, and disk utilisation with
sizing labels and recommendations.</p>
<p><strong>PFA</strong> the attached PDF for full details.</p>
<hr style="border:none;border-top:1px solid #E5E5E5;margin:20px 0 12px 0;">
<p style="color:#9A9A9A;font-size:11px;">
  OCI Resource Reporting System &mdash; Auto-generated, please do not reply.
</p>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"OCI Reports <{email_cfg.get('from_address', '')}>"
    msg["To"]      = ", ".join(email_cfg.get("to_addresses") or [])
    msg["Date"]    = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # Attach PDF — enforce 8 MB limit
    pdf_path = meta.path
    if pdf_path.exists():
        pdf_size = pdf_path.stat().st_size
        if pdf_size <= _8MB:
            part = MIMEApplication(pdf_path.read_bytes(), Name=pdf_path.name)
            part["Content-Disposition"] = f'attachment; filename="{pdf_path.name}"'
            msg.attach(part)
        else:
            log.warning("pdf_exceeds_limit", size_mb=round(pdf_size / 1_048_576, 1),
                        path=str(pdf_path))
            print(f"  Warning: PDF {pdf_size/1_048_576:.1f} MB exceeds 8 MB limit — "
                  f"sending without attachment.", file=sys.stderr)

    recipients = list(email_cfg.get("to_addresses") or [])
    cc = list(email_cfg.get("cc_addresses") or [])
    if cc:
        msg["Cc"] = ", ".join(cc)
        recipients += cc

    if not recipients:
        log.warning("no_recipients_configured")
        return

    smtp_host   = email_cfg.get("smtp_host", "")
    smtp_port   = int(email_cfg.get("smtp_port", 587))
    encryption  = email_cfg.get("encryption", "none").lower()
    auth_method = email_cfg.get("auth_method", "none").lower()
    smtp_user   = os.environ.get("SMTP_USER") or email_cfg.get("smtp_user", "")
    smtp_pass   = os.environ.get("SMTP_PASSWORD", "")

    try:
        if encryption == "ssl":
            ctx = ssl.create_default_context()
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60, context=ctx)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=60)
        with server:
            server.ehlo()
            if encryption == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if auth_method != "none" and smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log.info("resource_report_email_sent", tenancy=tenancy, compartment=compartment)
        print(f"  Emailed: {subject}")
    except Exception as exc:
        log.error("resource_report_email_failed", error=str(exc))
        print(f"  Email failed ({compartment}): {exc}", file=sys.stderr)


def cmd_resource_report(args: argparse.Namespace) -> None:
    """Generate per-compartment resource-utilisation PDFs (no cost data)."""
    from src.reporter.resource_report.data import load_raw_for_resource_report
    from src.reporter.resource_report.builder import build_resource_report
    from src.utils.date_utils import timestamp_slug

    _load_env()
    cfg = _load_config(_CONFIG_FILE)
    report_cfg = cfg.get("report", {})
    output_dir = Path(report_cfg.get("output_dir", "./reports"))
    pdf_dir = output_dir / "resource"

    # --- Resolve which raw files to process ---
    if args.input:
        raw_paths = [Path(args.input)]
    else:
        raw_dir = output_dir / "raw"
        if not raw_dir.exists():
            print(f"Error: raw data directory not found: {raw_dir}", file=sys.stderr)
            sys.exit(1)
        # Collect flat + one-level-nested raw files
        all_raw = sorted(raw_dir.glob("*_raw.json")) + sorted(raw_dir.glob("*/*_raw.json"))
        if not all_raw:
            print(f"Error: no *_raw.json files found under {raw_dir}", file=sys.stderr)
            sys.exit(1)

        # When tenancies are configured, skip stale legacy/default directories
        tenancies = _normalize_tenancies(cfg)
        if tenancies:
            valid_slugs = {_slugify(t.name) for t in tenancies}
            all_raw = [
                p for p in all_raw
                if p.parent == raw_dir or _slugify(p.parent.name) in valid_slugs
            ]

        # Optional tenancy filter
        tenancy_filter = getattr(args, "tenancy", None)
        if tenancy_filter:
            slug = _slugify(tenancy_filter)
            all_raw = [p for p in all_raw if _slugify(p.parent.name) == slug]

        # Optional compartment filter (matches against the filename prefix before the timestamp)
        comp_filter = getattr(args, "compartment", None)
        if comp_filter:
            c_slug = _slugify(comp_filter)
            _CRE = re.compile(r"^(.*?)(\d{8}_\d{6})_raw\.json$")
            all_raw = [p for p in all_raw if (m := _CRE.match(p.name)) and _slugify(m.group(1).rstrip("_")) == c_slug]

        # Per (parent_dir, compartment_prefix) keep only the latest file
        # File names: [<comp_slug>_]<YYYYMMDD>_<HHMMSS>_raw.json
        _DATE_RE = re.compile(r"^(.*?)(\d{8}_\d{6})_raw\.json$")
        by_key: dict[str, list[Path]] = {}
        for p in all_raw:
            m = _DATE_RE.match(p.name)
            key = f"{p.parent}/{m.group(1) if m else p.stem}"
            by_key.setdefault(key, []).append(p)
        raw_paths = [sorted(files)[-1] for files in by_key.values()]

    if not raw_paths:
        print("Error: no raw files to process", file=sys.stderr)
        sys.exit(1)

    gen_ts = timestamp_slug()
    generated: list = []

    for raw_path in sorted(raw_paths):
        if not raw_path.exists():
            print(f"Warning: not found, skipping: {raw_path}", file=sys.stderr)
            continue

        fleet = load_raw_for_resource_report(raw_path)

        if args.output and len(raw_paths) == 1:
            out_path = Path(args.output)
        elif fleet.tenancy_name:
            t_slug = _slugify(fleet.tenancy_name)
            c_slug = _slugify(fleet.compartment_name) if fleet.compartment_name else "all"
            sub = pdf_dir / t_slug
            sub.mkdir(parents=True, exist_ok=True)
            out_path = sub / f"{c_slug}_resource_report_{gen_ts}.pdf"
            # Remove older PDFs for this compartment (keep only the one we're about to write)
            for old_pdf in sub.glob(f"{c_slug}_resource_report_*.pdf"):
                if old_pdf != out_path:
                    old_pdf.unlink(missing_ok=True)
        else:
            pdf_dir.mkdir(parents=True, exist_ok=True)
            out_path = pdf_dir / f"OCI_Resource_Report_{gen_ts}.pdf"

        meta = build_resource_report(fleet, out_path)
        size_kb = meta.file_size_bytes / 1024
        label = (
            f"{fleet.tenancy_name} / {fleet.compartment_name}"
            if fleet.tenancy_name else raw_path.name
        )
        print(
            f"[{label}]  {meta.path}"
            f"  ({size_kb:.0f} KB, {meta.page_count} pages, {len(fleet.instances)} instances)"
        )
        generated.append((fleet, meta))

        if not getattr(args, "skip_email", False):
            _send_resource_report_email(fleet, meta, cfg)

    print(f"\nGenerated {len(generated)} report(s).")


def cmd_run(args: argparse.Namespace) -> None:
    _load_env()
    cfg = _load_config(args.config if hasattr(args, "config") and args.config else _CONFIG_FILE)
    from src.orchestrator import PipelineRunner
    runner = PipelineRunner(cfg)
    result = runner.run(
        dry_run=args.dry_run,
        skip_notify=args.skip_notify,
        resume_run_id=args.resume or None,
    )
    print(f"Run {result.run_id}: {result.status.upper()} ({result.duration_s:.1f}s)")
    for sr in result.step_results:
        icon = "+" if sr.status == "success" else ("-" if sr.status == "skipped" else "!")
        err = f" -- {sr.error}" if sr.error else ""
        print(f"  [{icon}] {sr.step_name} [{sr.status}]{err}")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if not result.success:
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    run_log = Path("reports") / "run_log.jsonl"
    if not run_log.exists():
        print("No runs found.")
        return
    n = getattr(args, "last", 5) or 5
    lines = run_log.read_text().splitlines()
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    recent = entries[-n:]
    print(f"{'RUN ID':<12} {'STATUS':<10} {'STARTED':<22} {'DURATION':>10}  REPORT")
    print("-" * 80)
    for e in reversed(recent):
        started = e.get("started_at", "")[:19].replace("T", " ")
        duration = f"{e.get('duration_s', 0):.1f}s"
        report = e.get("report_path") or "-"
        print(f"{e.get('run_id','?'):<12} {e.get('status','?'):<10} {started:<22} {duration:>10}  {report}")


def cmd_validate_config(args: argparse.Namespace) -> None:
    _load_env()
    cfg = _load_config(args.config if hasattr(args, "config") and args.config else _CONFIG_FILE)
    validate_config(cfg, dry_run=True)
    print("Configuration is valid.")


def cmd_logs(args: argparse.Namespace) -> None:
    import glob as _glob
    log_dir = Path("logs")
    if not log_dir.exists():
        print("No log directory found.")
        return
    log_files = sorted(_glob.glob(str(log_dir / "*.log")))
    if not log_files:
        print("No log files found.")
        return
    log_file = log_files[-1]
    tail_n = getattr(args, "tail", 50) or 50
    lines = Path(log_file).read_text(errors="replace").splitlines()
    for line in lines[-tail_n:]:
        print(line)
    if getattr(args, "follow", False):
        import time
        print(f"\n[following {log_file} -- Ctrl+C to stop]")
        with open(log_file) as f:
            f.seek(0, 2)
            try:
                while True:
                    line = f.readline()
                    if line:
                        print(line, end="")
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass


def cmd_health(args: argparse.Namespace) -> None:
    from src.utils.health import overall_exit_code, run_health_checks

    _load_env()
    work_dir = Path(__file__).resolve().parent
    try:
        cfg = _load_config(_CONFIG_FILE)
        smtp_host = cfg.get("smtp", {}).get("host", "")
        smtp_port = int(cfg.get("smtp", {}).get("port", 587))
    except Exception:
        smtp_host, smtp_port = "", 587

    results = run_health_checks(work_dir, smtp_host=smtp_host, smtp_port=smtp_port)

    use_json = getattr(args, "json", False)
    verbose = getattr(args, "verbose", False)

    if use_json:
        import json
        print(json.dumps([
            {"name": r.name, "status": r.status, "latency_ms": round(r.latency_ms, 1), "details": r.details}
            for r in results
        ], indent=2))
    else:
        icons = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}
        for r in results:
            line = f"{icons.get(r.status, '?')} {r.name}"
            if verbose:
                line += f"  ({r.latency_ms:.0f}ms)  {r.details}"
            print(line)

    sys.exit(overall_exit_code(results))


_shutdown_requested = False


def _handle_shutdown(signum: int, frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print("\nShutdown requested — finishing current compartment then exiting cleanly.", file=sys.stderr)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    parser = argparse.ArgumentParser(
        prog="oci-cost-optimizer",
        description="OCI Cloud Cost Optimization data collector",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Collect OCI resource and cost data")
    collect_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and auth without making metric/cost API calls",
    )
    collect_parser.add_argument(
        "--config",
        type=Path,
        default=_CONFIG_FILE,
        help="Path to config.yaml (default: config/config.yaml)",
    )
    collect_parser.add_argument(
        "--tenancy",
        metavar="NAME",
        help="Collect only for this tenancy (case-insensitive name match)",
    )
    collect_parser.add_argument(
        "--compartment",
        metavar="NAME",
        help="Collect only for this compartment (case-insensitive name match)",
    )

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Run analytics engine on collected raw data and print a cost optimization report",
    )
    analyze_parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to a *_raw.json collector output file (default: auto-detect latest)",
    )
    analyze_parser.add_argument(
        "--config",
        type=Path,
        default=_CONFIG_FILE,
        help="Path to config.yaml (default: config/config.yaml)",
    )
    analyze_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Print validation report and exit without running the full analytics pipeline",
    )
    analyze_parser.add_argument(
        "--explain",
        metavar="INSTANCE_ID",
        default=None,
        help="Print a detailed recommendation explanation for a single instance OCID",
    )
    analyze_parser.add_argument(
        "--previous",
        type=Path,
        default=None,
        help="Path to a previous analytics JSON output for period-over-period comparison",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Generate a PDF report from an analytics JSON output",
    )
    report_parser.add_argument(
        "--analytics",
        type=Path,
        default=None,
        help="Path to a *_analytics.json file (default: auto-detect latest)",
    )
    report_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: reports/pdf/OCI_Cost_Report_<ts>.pdf)",
    )
    report_parser.add_argument(
        "--config",
        type=Path,
        default=_CONFIG_FILE,
        help="Path to config.yaml (default: config/config.yaml)",
    )
    report_parser.add_argument(
        "--page-size",
        choices=["A4", "Letter"],
        default="A4",
        help="PDF page size (default: A4)",
    )
    report_parser.add_argument(
        "--skip-notify",
        action="store_true",
        help="Generate PDF only, do not send notifications",
    )

    # ── run ───────────────────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="Run the full pipeline: collect→analyze→report→notify")
    run_parser.add_argument("--dry-run", action="store_true", help="Skip API calls and email; write .eml instead")
    run_parser.add_argument("--skip-notify", action="store_true", help="Run pipeline but skip notification dispatch")
    run_parser.add_argument("--resume", metavar="RUN_ID", default=None, help="Resume a previous run by ID")
    run_parser.add_argument("--config", type=Path, default=_CONFIG_FILE)

    # ── status ────────────────────────────────────────────────────────────────
    status_parser = subparsers.add_parser("status", help="Show recent pipeline runs")
    status_parser.add_argument("--last", type=int, default=5, metavar="N", help="Number of runs to show (default: 5)")

    # ── validate-config ───────────────────────────────────────────────────────
    vc_parser = subparsers.add_parser("validate-config", help="Validate config.yaml and exit 0/1")
    vc_parser.add_argument("--config", type=Path, default=_CONFIG_FILE)

    # ── logs ──────────────────────────────────────────────────────────────────
    logs_parser = subparsers.add_parser("logs", help="Tail the most recent log file")
    logs_parser.add_argument("--tail", type=int, default=50, metavar="N", help="Lines to show (default: 50)")
    logs_parser.add_argument("--follow", action="store_true", help="Follow log output (Ctrl+C to stop)")

    # ── health ────────────────────────────────────────────────────────────────
    health_parser = subparsers.add_parser("health", help="Run health checks and exit 0/1/2")
    health_parser.add_argument("--verbose", action="store_true", help="Show latency and details")
    health_parser.add_argument("--json", action="store_true", help="Output JSON")

    rr_parser = subparsers.add_parser(
        "resource-report",
        help="Generate resource-utilisation PDF (no cost data — use before tagging is set up)",
    )
    rr_parser.add_argument(
        "--input", type=Path, default=None,
        help="Path to *_raw.json (default: auto-detect latest in reports/raw/)",
    )
    rr_parser.add_argument(
        "--output", type=Path, default=None,
        help="Output PDF path — only valid when processing a single file",
    )
    rr_parser.add_argument(
        "--tenancy", type=str, default=None, metavar="NAME",
        help="Generate reports only for this tenancy name (substring match on slug)",
    )
    rr_parser.add_argument(
        "--compartment", type=str, default=None, metavar="NAME",
        help="Generate report only for this compartment name",
    )
    rr_parser.add_argument(
        "--skip-email", action="store_true",
        help="Generate PDFs only, do not send emails",
    )

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "validate-config":
        cmd_validate_config(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "health":
        cmd_health(args)
    elif args.command == "resource-report":
        cmd_resource_report(args)


if __name__ == "__main__":
    main()
