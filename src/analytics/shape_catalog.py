from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Shape:
    shape_name: str
    family: str
    processor: str
    processor_type: str        # x86_64 | arm64
    min_ocpu: int
    max_ocpu: int
    min_ram_gb: int
    max_ram_gb: int
    is_flex: bool
    vcpu_per_ocpu: int         # 2 for x86, 1 for A1/ARM
    hourly_cost_per_ocpu: float
    hourly_cost_per_gb_ram: float
    fixed_hourly_cost: float   # non-zero for fixed shapes (BM, GPU)
    network_gbps: int
    max_block_volume_iops: int
    gpu_count: int
    gpu_model: str
    notes: str

    # ------------------------------------------------------------------ #
    # Cost helpers
    # ------------------------------------------------------------------ #

    def hourly_cost(self, ocpu: int, ram_gb: int) -> float:
        """Compute hourly cost for given OCPU and RAM configuration."""
        if not self.is_flex:
            return self.fixed_hourly_cost
        return self.hourly_cost_per_ocpu * ocpu + self.hourly_cost_per_gb_ram * ram_gb

    def monthly_cost(self, ocpu: int, ram_gb: int) -> float:
        """730 hours per month (industry standard)."""
        return self.hourly_cost(ocpu, ram_gb) * 730

    # ------------------------------------------------------------------ #
    # Config validation / optimisation
    # ------------------------------------------------------------------ #

    def is_valid_config(self, ocpu: int, ram_gb: int) -> bool:
        """Check if the given ocpu/ram_gb combo is within spec."""
        if ocpu < self.min_ocpu or ocpu > self.max_ocpu:
            return False
        if ram_gb < self.min_ram_gb or ram_gb > self.max_ram_gb:
            return False
        # Flex constraint: ram must be 1–64 GB per OCPU
        if self.is_flex:
            if ram_gb < ocpu:       # at least 1 GB per OCPU
                return False
            if ram_gb > ocpu * 64:
                return False
        return True

    def optimal_flex_config(self, required_ocpu: int, required_ram_gb: int) -> tuple[int, int]:
        """
        Compute the smallest valid flex configuration that meets requirements.
        Returns (ocpu, ram_gb).
        """
        ocpu = max(self.min_ocpu, min(required_ocpu, self.max_ocpu))
        # ram must be >= required, >= 1*ocpu, <= 64*ocpu, within [min_ram, max_ram]
        ram_min = max(self.min_ram_gb, ocpu)
        ram_max = min(self.max_ram_gb, ocpu * 64)
        ram_gb = max(ram_min, min(required_ram_gb, ram_max))
        return ocpu, ram_gb


class ShapeCatalog:
    """
    Loads shapes from a JSON catalog and provides lookup / pricing helpers.

    JSON format expected::

        {
            "shapes": [
                {
                    "shape_name": "VM.Standard.E4.Flex",
                    "family": "standard",
                    ...
                },
                ...
            ]
        }

    An optional *pricing_override_path* JSON file may be supplied to override
    per-shape hourly costs without modifying the main catalog.  Format::

        {
            "VM.Standard.E4.Flex": {
                "hourly_cost_per_ocpu": 0.025,
                "hourly_cost_per_gb_ram": 0.0015
            }
        }
    """

    def __init__(
        self,
        catalog_path: Path,
        pricing_override_path: Optional[Path] = None,
    ) -> None:
        with catalog_path.open() as f:
            data = json.load(f)

        self._shapes: dict[str, Shape] = {}
        for s in data["shapes"]:
            shape = Shape(**{k: s[k] for k in Shape.__dataclass_fields__})
            self._shapes[shape.shape_name] = shape

        # Apply optional pricing overrides
        if pricing_override_path and pricing_override_path.exists():
            with pricing_override_path.open() as f:
                overrides = json.load(f)
            for shape_name, prices in overrides.items():
                if shape_name in self._shapes:
                    s = self._shapes[shape_name]
                    if "hourly_cost_per_ocpu" in prices:
                        setattr(s, "hourly_cost_per_ocpu", prices["hourly_cost_per_ocpu"])
                    if "hourly_cost_per_gb_ram" in prices:
                        setattr(s, "hourly_cost_per_gb_ram", prices["hourly_cost_per_gb_ram"])
                    if "fixed_hourly_cost" in prices:
                        setattr(s, "fixed_hourly_cost", prices["fixed_hourly_cost"])

    # ------------------------------------------------------------------ #
    # Basic accessors
    # ------------------------------------------------------------------ #

    def get(self, shape_name: str) -> Optional[Shape]:
        """Return the Shape for *shape_name*, or None if not found."""
        return self._shapes.get(shape_name)

    def all_shapes(self) -> list[Shape]:
        """Return all loaded shapes as a list."""
        return list(self._shapes.values())

    # ------------------------------------------------------------------ #
    # Candidate search
    # ------------------------------------------------------------------ #

    def candidates_for(
        self,
        required_ocpu: int,
        required_ram_gb: int,
        same_family: Optional[str] = None,
        same_processor_type: Optional[str] = None,
        include_families: Optional[list[str]] = None,
    ) -> list[Shape]:
        """
        Return shapes that can satisfy *required_ocpu* and *required_ram_gb*,
        sorted by monthly cost ascending.

        Filtering rules
        ---------------
        - GPU and DenseIO shapes are **excluded** unless their family is
          explicitly listed in *include_families*.
        - If *same_family* is set, only shapes from that family are returned.
        - If *same_processor_type* is set, only shapes with that processor
          type (``"x86_64"`` or ``"arm64"``) are returned.
        - If *include_families* is set, only shapes from those families are
          returned (this filter compounds with the others).
        """
        results: list[Shape] = []

        for shape in self._shapes.values():
            # GPU and DenseIO are excluded by default
            if shape.family in ("gpu", "denseio"):
                if include_families is None or shape.family not in include_families:
                    continue

            if same_family and shape.family != same_family:
                continue
            if same_processor_type and shape.processor_type != same_processor_type:
                continue
            if include_families and shape.family not in include_families:
                continue

            # Capacity check
            if shape.is_flex:
                ocpu, ram = shape.optimal_flex_config(required_ocpu, required_ram_gb)
                if ocpu >= required_ocpu and ram >= required_ram_gb:
                    results.append(shape)
            else:
                # Fixed shape: must have enough headroom
                if shape.max_ocpu >= required_ocpu and shape.max_ram_gb >= required_ram_gb:
                    results.append(shape)

        # Sort by monthly cost; for flex shapes use the required config cost
        def _cost(s: Shape) -> float:
            if s.is_flex:
                oc, rm = s.optimal_flex_config(required_ocpu, required_ram_gb)
                return s.monthly_cost(oc, rm)
            return s.monthly_cost(s.min_ocpu, s.min_ram_gb)

        results.sort(key=_cost)
        return results
