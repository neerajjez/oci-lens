"""Tests for src/config/loader.py."""
from __future__ import annotations

from src.config.loader import validate_config


def test_valid_config_no_issues():
    cfg = {
        "compartments": ["ocid1.compartment.oc1..aaa"],
        "regions": ["us-ashburn-1"],
    }
    assert validate_config(cfg) == []


def test_empty_compartments_returns_issue():
    cfg = {"compartments": [], "regions": ["us-ashburn-1"]}
    issues = validate_config(cfg)
    assert any("compartment" in i for i in issues)


def test_missing_compartments_key_returns_issue():
    cfg = {"regions": ["us-ashburn-1"]}
    issues = validate_config(cfg)
    assert any("compartment" in i for i in issues)


def test_invalid_ocid_returns_issue():
    cfg = {
        "compartments": ["not-an-ocid"],
        "regions": ["us-ashburn-1"],
    }
    issues = validate_config(cfg)
    assert any("OCID" in i or "ocid" in i.lower() for i in issues)


def test_empty_regions_returns_issue():
    cfg = {"compartments": ["ocid1.compartment.oc1..aaa"], "regions": []}
    issues = validate_config(cfg)
    assert any("region" in i for i in issues)


def test_missing_regions_key_returns_issue():
    cfg = {"compartments": ["ocid1.compartment.oc1..aaa"]}
    issues = validate_config(cfg)
    assert any("region" in i for i in issues)


def test_multiple_valid_compartments():
    cfg = {
        "compartments": [
            "ocid1.compartment.oc1..aaa",
            "ocid1.compartment.oc1..bbb",
        ],
        "regions": ["us-ashburn-1"],
    }
    assert validate_config(cfg) == []


def test_empty_config_returns_multiple_issues():
    issues = validate_config({})
    assert len(issues) >= 2
