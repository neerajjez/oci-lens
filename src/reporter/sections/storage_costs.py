"""
src/reporter/sections/storage_costs.py
=======================================
Storage Costs section: boot volumes + block volumes tables with cost column.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from src.reporter.components.data_table import styled_table
from src.reporter.styles import BODY, CAPTION, H2, H3, NEUTRAL_200

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def build_storage_costs(result: "AnalyticsResult") -> list:
    """Returns flowables for the Storage Costs section."""
    flowables: list = []

    flowables.append(Paragraph("Storage Costs", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    volumes = getattr(result, "volumes", None) or []

    if not volumes:
        flowables.append(Paragraph(
            "No volume inventory data available for this reporting period.", BODY
        ))
        flowables.append(PageBreak())
        return flowables

    # Build storage_cost lookup: instance_id → monthly storage cost
    storage_cost_map: dict[str, float] = {}
    instance_name_map: dict[str, str] = {}
    for ic in (getattr(result, "instance_costs", None) or []):
        storage_cost_map[ic.instance_id] = ic.storage_cost
        instance_name_map[ic.instance_id] = ic.display_name

    # Split volumes by OCID prefix
    boot_volumes = [v for v in volumes if "bootvolume" in str(v.get("volume_id", "")).lower()]
    block_volumes = [v for v in volumes if "bootvolume" not in str(v.get("volume_id", "")).lower()]

    total_storage_cost = sum(ic.storage_cost for ic in (getattr(result, "instance_costs", None) or []))
    total_boot_cost = _sum_vol_costs(boot_volumes, storage_cost_map)
    total_block_cost = _sum_vol_costs(block_volumes, storage_cost_map)

    flowables.append(Paragraph(
        f"Fleet storage total: <b>${total_storage_cost:,.2f}/mo</b>  —  "
        f"boot volumes ${total_boot_cost:,.2f}  +  block volumes ${total_block_cost:,.2f}",
        BODY,
    ))
    flowables.append(Spacer(1, 0.15 * inch))

    # ── Boot Volumes ──────────────────────────────────────────────────────────
    flowables.append(Paragraph("Boot Volumes", H3))
    flowables.append(Spacer(1, 0.05 * inch))

    if boot_volumes:
        bv_headers = ["Volume Name", "State", "Size (GB)", "VPU/GB", "Attached Instance", "Storage Cost/mo*"]
        bv_col_widths = [1.6 * inch, 0.7 * inch, 0.65 * inch, 0.55 * inch, 1.8 * inch, 1.0 * inch]
        bv_rows = []
        for v in sorted(boot_volumes, key=lambda x: str(x.get("display_name", ""))):
            iid = str(v.get("attached_instance_id", ""))
            cost = storage_cost_map.get(iid, 0.0)
            iname = instance_name_map.get(iid, iid[:28] if iid else "—")
            bv_rows.append([
                str(v.get("display_name", ""))[:28],
                str(v.get("lifecycle_state", ""))[:12],
                str(v.get("size_gb", "—")),
                str(v.get("vpu_per_gb", "—")),
                iname[:28],
                f"${cost:,.2f}" if cost > 0 else "—",
            ])
        flowables.append(styled_table(bv_headers, bv_rows, col_widths=bv_col_widths, font_size=7.5))
    else:
        flowables.append(Paragraph("No boot volume data collected.", BODY))

    flowables.append(Spacer(1, 0.15 * inch))

    # ── Block Volumes ─────────────────────────────────────────────────────────
    flowables.append(Paragraph("Block (Data) Volumes", H3))
    flowables.append(Spacer(1, 0.05 * inch))

    if block_volumes:
        blk_headers = ["Volume Name", "State", "Size (GB)", "VPU/GB",
                       "Read IOPS", "Write IOPS", "Attached Instance", "Storage Cost/mo*"]
        blk_col_widths = [1.25 * inch, 0.6 * inch, 0.6 * inch, 0.5 * inch,
                          0.65 * inch, 0.65 * inch, 1.35 * inch, 0.9 * inch]
        blk_rows = []
        for v in sorted(block_volumes, key=lambda x: str(x.get("display_name", ""))):
            iid = str(v.get("attached_instance_id", ""))
            cost = storage_cost_map.get(iid, 0.0)
            iname = instance_name_map.get(iid, iid[:22] if iid else "Unattached")
            r_iops = v.get("read_iops_avg")
            w_iops = v.get("write_iops_avg")
            blk_rows.append([
                str(v.get("display_name", ""))[:24],
                str(v.get("lifecycle_state", ""))[:10],
                str(v.get("size_gb", "—")),
                str(v.get("vpu_per_gb", "—")),
                f"{r_iops:.0f}" if r_iops is not None else "—",
                f"{w_iops:.0f}" if w_iops is not None else "—",
                iname[:22],
                f"${cost:,.2f}" if cost > 0 else "—",
            ])
        flowables.append(styled_table(blk_headers, blk_rows, col_widths=blk_col_widths, font_size=7))
    else:
        flowables.append(Paragraph("No block volume data collected.", BODY))

    flowables.append(Spacer(1, 0.1 * inch))
    flowables.append(Paragraph(
        "* Storage costs are attributed at the instance level — OCI Usage API billing is per "
        "instance, not per individual volume. The figure shown is the total storage billing "
        "for all volumes attached to that instance.",
        CAPTION,
    ))
    flowables.append(PageBreak())
    return flowables


def _sum_vol_costs(volumes: list, storage_cost_map: dict[str, float]) -> float:
    seen: set[str] = set()
    total = 0.0
    for v in volumes:
        iid = str(v.get("attached_instance_id", ""))
        if iid and iid not in seen:
            total += storage_cost_map.get(iid, 0.0)
            seen.add(iid)
    return total
