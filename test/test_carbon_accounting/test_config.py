# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Smoke tests for the reduced carbon accounting configuration."""

import re
from pathlib import Path

import pytest
import yaml
from snakemake.utils import update_config

from mods.clustering.constants import VALID_CONFIGURATIONS
from scripts.lib.validation.config import validate_config

CONFIG_STACK = (
    "config/config.default.yaml",
    "config/config.de.yaml",
    "config/config.at.yaml",
    "config/config.ca.yaml",
    "config/config.carbon-accounting.yaml",
)


@pytest.fixture(scope="module")
def config() -> dict:
    """Merge the config stack the way Snakemake applies ``--configfile``."""
    merged = {}
    for path in CONFIG_STACK:
        update_config(merged, yaml.safe_load(Path(path).read_text()))
    return merged


def test_config_validates(config):
    validate_config(config)


def test_custom_clustering_matches_admin_levels(config):
    clustering = config["mods"]["modify_nuts3_shapes"]
    levels = config["clustering"]["administrative"]
    assert clustering in VALID_CONFIGURATIONS
    assert levels["AT"] == (2 if clustering.startswith("AT10") else 3)
    assert levels["DE"] == (3 if clustering.endswith("DE5") else 1)


def test_solver_is_gurobi(config):
    assert config["solving"]["solver"]["name"] == "gurobi"


def test_scenarios_file_lists_run_names(config):
    scenarios = yaml.safe_load(Path(config["run"]["scenarios"]["file"]).read_text())
    assert set(config["run"]["name"]) <= set(scenarios)


def test_snakefile_loads_the_carbon_accounting_config():
    """The fenced hook loads the CA files after the PyPSA-AT ones."""
    configfiles = re.findall(
        r'^configfile: "([^"]+)"', Path("Snakefile").read_text(), re.M
    )
    assert configfiles[-2:] == ["config/config.ca.yaml", "config/plotting.ca.yaml"]


def test_carbon_accounting_defaults(config):
    """The CA defaults: feature toggle first, status quo method."""
    defaults = config["mods"]["carbon_accounting"]
    assert next(iter(defaults)) == "enable"
    assert defaults["enable"] is True
    assert defaults["method"] == "technology"


@pytest.mark.parametrize("path", ["config/config.at.yaml", "config/plotting.at.yaml"])
def test_pypsa_at_config_has_no_carbon_accounting(path):
    """CA keys stay out of the PyPSA-AT config files (#7)."""
    assert "carbon_accounting" not in Path(path).read_text()


def test_pypsa_at_plotting_has_no_carbon_accounting_colors():
    """No tech color of the CA overlay is also set in the PyPSA-AT file (#7)."""

    def tech_colors(path):
        return yaml.safe_load(Path(path).read_text())["plotting"]["tech_colors"]

    ca_colors = tech_colors("config/plotting.ca.yaml")
    at_colors = tech_colors("config/plotting.at.yaml")
    assert not ca_colors.keys() & at_colors.keys()
