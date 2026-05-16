"""Tests for src/analytics/shape_catalog.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analytics.shape_catalog import Shape, ShapeCatalog

_CATALOG_PATH = Path(__file__).parents[2] / "config" / "shapes.json"


def _catalog() -> ShapeCatalog:
    return ShapeCatalog(_CATALOG_PATH)


# ── catalog loading ───────────────────────────────────────────────────────────

def test_catalog_loads_shapes():
    assert len(_catalog().all_shapes()) > 0


def test_catalog_contains_e4_flex():
    shape = _catalog().get("VM.Standard.E4.Flex")
    assert shape is not None
    assert shape.shape_name == "VM.Standard.E4.Flex"


def test_catalog_get_unknown_returns_none():
    assert _catalog().get("VM.Nonexistent.Shape") is None


# ── Shape cost helpers ────────────────────────────────────────────────────────

def test_flex_monthly_cost_positive():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip("VM.Standard.E4.Flex not in catalog")
    assert shape.monthly_cost(4, 32) > 0.0


def test_flex_hourly_cost_scales_with_ocpu():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None or not shape.is_flex:
        pytest.skip()
    assert shape.hourly_cost(4, 32) > shape.hourly_cost(2, 16)


def test_monthly_is_730_times_hourly():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip()
    assert shape.monthly_cost(4, 32) == pytest.approx(shape.hourly_cost(4, 32) * 730)


# ── is_valid_config ───────────────────────────────────────────────────────────

def test_valid_flex_config():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip()
    assert shape.is_valid_config(4, 32)


def test_invalid_ocpu_zero():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip()
    assert not shape.is_valid_config(0, 32)


def test_invalid_ram_zero():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip()
    assert not shape.is_valid_config(4, 0)


# ── optimal_flex_config ───────────────────────────────────────────────────────

def test_optimal_flex_meets_requirements():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None or not shape.is_flex:
        pytest.skip()
    ocpu, ram = shape.optimal_flex_config(2, 16)
    assert ocpu >= 2
    assert ram >= 16


def test_optimal_flex_is_valid():
    shape = _catalog().get("VM.Standard.E4.Flex")
    if shape is None or not shape.is_flex:
        pytest.skip()
    ocpu, ram = shape.optimal_flex_config(2, 16)
    assert shape.is_valid_config(ocpu, ram)


# ── pricing override ──────────────────────────────────────────────────────────

def test_pricing_override_applied(tmp_path):
    override = {"VM.Standard.E4.Flex": {"hourly_cost_per_ocpu": 0.001}}
    override_path = tmp_path / "override.json"
    override_path.write_text(json.dumps(override))
    cat = ShapeCatalog(_CATALOG_PATH, override_path)
    shape = cat.get("VM.Standard.E4.Flex")
    if shape is None:
        pytest.skip()
    assert shape.hourly_cost_per_ocpu == pytest.approx(0.001)


def test_pricing_override_missing_file_ignored():
    cat = ShapeCatalog(_CATALOG_PATH, Path("/nonexistent/override.json"))
    assert cat.get("VM.Standard.E4.Flex") is not None


# ── candidates ────────────────────────────────────────────────────────────────

def test_candidates_returns_list():
    cat = _catalog()
    result = cat.candidates_for(required_ocpu=2, required_ram_gb=16)
    assert isinstance(result, list)


def test_all_shapes_iterable():
    shapes = list(_catalog().all_shapes())
    assert len(shapes) > 0
    assert all(isinstance(s, Shape) for s in shapes)
