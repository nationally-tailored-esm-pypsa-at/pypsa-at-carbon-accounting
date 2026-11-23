# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Smoke tests for the carbon accounting and design-principle configurations."""

import re
from copy import deepcopy
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
)
OVERLAYS = (
    "config/config.carbon-accounting.yaml",
    "config/config.design-principles.yaml",
)


def merge_config(overlay: str) -> dict:
    """Merge the config stack the way Snakemake applies ``--configfile``."""
    merged = {}
    for path in (*CONFIG_STACK, overlay):
        update_config(merged, yaml.safe_load(Path(path).read_text()))
    return merged


@pytest.fixture(scope="module", params=OVERLAYS)
def config(request) -> dict:
    """Return the merged config of every ``--configfile`` overlay."""
    return merge_config(request.param)


@pytest.fixture(scope="module")
def dp_config() -> dict:
    """Return the merged config of the design-principle overlay."""
    return merge_config("config/config.design-principles.yaml")


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


# keys in which each design-principle run differs from DP_base, see
# docs-ca/explanations/design-principle-effects-spec.md
DP_DIFFERENCES = {
    "DP1_no_national_data": {
        "mods.klien_potential_limits.technologies",
        "mods.carbon_accounting.onwind_brownfield.enable",
    },
    "DP2_at10": {"mods.modify_nuts3_shapes", "clustering.administrative.AT"},
    "DP3_no_national_policy": {
        "solving.constraints.co2_budget_national.AT",
        "solving.constraints.limits_volume_min.solar.AT.2030",
        "solving.constraints.limits_volume_min.wind.AT.2030",
        "solving.constraints.limits_volume_min.hydro.AT.2030",
        "solving.constraints.limits_volume_min.biomass.AT.2030",
        "solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT.2030",
        "solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT.2040",
        "solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT.2050",
        "mods.net_zero_electricity.enable",
        "mods.tyndp_cross_border_flow_limits.enable",
        "mods.tyndp_lower_bounds.enable",
        "mods.tyndp_lower_bounds.years",
        "mods.block_russian_gas_imports.enable",
        "mods.override_gas_storage_capacities.enable",
        "mods.threshold_year_for_gas_grid_expansion",
        "mods.trajectories.apply_trajectories",
    },
}


def _flatten(d: dict, prefix: str = "") -> dict:
    """Return the leaves of a nested dict, keyed by their dotted path."""
    flat = {}
    for key, value in d.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat |= _flatten(value, f"{path}.")
        else:
            flat[path] = value
    return flat


@pytest.fixture(scope="module")
def dp_configs(dp_config) -> dict[str, dict]:
    """Return the flattened, resolved config of every DP scenario."""
    scenarios = yaml.safe_load(Path(dp_config["run"]["scenarios"]["file"]).read_text())
    resolved = {}
    for name in ("DP_base", *DP_DIFFERENCES):
        merged = deepcopy(dp_config)
        update_config(merged, scenarios[name])
        merged.pop("run")
        merged.pop("description", None)
        resolved[name] = _flatten(merged)
    return resolved


def test_dp_runs_are_listed(dp_config):
    assert set(dp_config["run"]["name"]) == {"DP_base", *DP_DIFFERENCES}


@pytest.mark.parametrize("scenario", DP_DIFFERENCES)
def test_dp_run_differs_from_base_in_one_principle(dp_configs, scenario):
    base, run = dp_configs["DP_base"], dp_configs[scenario]
    expected = DP_DIFFERENCES[scenario]
    differ = {k for k in base.keys() | run.keys() if base.get(k) != run.get(k)}
    # a key set to null drops all leaves below it
    differ = {next((e for e in expected if k.startswith(f"{e}.")), k) for k in differ}
    assert differ == expected


def test_dp_base_at_nuts3(dp_configs):
    assert dp_configs["DP_base"]["mods.modify_nuts3_shapes"] == "AT35DE5"
    assert dp_configs["DP_base"]["clustering.administrative.AT"] == 3
    assert dp_configs["DP_base"]["mods.carbon_accounting.method"] == "technology"


def test_dp3_removes_at_budget_only(dp_configs):
    dp3 = dp_configs["DP3_no_national_policy"]
    assert dp3["solving.constraints.co2_budget_national.AT"] is None
    assert dp3["solving.constraints.co2_budget_national.DE.2030"] is not None


def test_dp3_freezes_no_gas_grid_horizon(dp_configs):
    threshold = dp_configs["DP3_no_national_policy"][
        "mods.threshold_year_for_gas_grid_expansion"
    ]
    assert threshold < min(dp_configs["DP_base"]["planning_horizons"])


def test_dp3_keeps_h2_import_scenario(dp_configs):
    """No neutral TYNDP H2 import scenario exists, so DP3 keeps the default."""
    key = "mods.tyndp_h2_import_scenario"
    assert dp_configs["DP3_no_national_policy"][key] == dp_configs["DP_base"][key]


def test_onwind_brownfield_default(config):
    toggle = config["mods"]["carbon_accounting"]["onwind_brownfield"]
    assert next(iter(toggle)) == "enable"
    assert toggle["enable"] is True
