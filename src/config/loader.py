"""Configuration validation helpers."""
from __future__ import annotations

import re


_OCID_RE = re.compile(r"^ocid1\.[a-z]+\.[a-z0-9.-]+\.")


def validate_config(cfg: dict) -> list[str]:
    issues: list[str] = []
    compartments = cfg.get("compartments", [])
    if not compartments:
        issues.append("compartments list is empty or missing")
    for ocid in compartments:
        if not _OCID_RE.match(str(ocid)):
            issues.append(f"invalid compartment OCID: {ocid}")
    regions = cfg.get("regions", [])
    if not regions:
        issues.append("regions list is empty or missing")
    return issues
