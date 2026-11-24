# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for evals/carbon_accounting/design_principles.py on toy networks."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pypsa
import pytest

from evals.carbon_accounting import design_principles as dp
from mods.constraints.eag import constraint_net_zero_electricity
from mods.constraints.production import constraint_production_targets

YEAR = 2030


def _pypsa_de_additional_functionality():
    """Import ``scripts/pypsa-de/additional_functionality.py`` (hyphenated directory)."""
    path = Path("scripts/pypsa-de/additional_functionality.py")
    spec = importlib.util.spec_from_file_location("pypsa_de_af", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _meta(net_zero: bool = True) -> dict:
    return {
        "countries": ["AT", "DE"],
        "renewable": {
            "onwind": {},
            "solar": {},
            "solar-hsat": {},
            "hydro": {"carriers": ["ror", "PHS", "hydro"]},
        },
        "mods": {
            "net_zero_electricity": {
                "enable": net_zero,
                "fuels": ["gas", "H2", "solid biomass", "methanol"],
                "h2_sources": ["AC", "low voltage", "solid biomass"],
                "AT": str(YEAR),
            }
        },
        "solving": {"options": {"transmission_losses": 0}},
        "clustering": {"administrative": {"AT": 3}},
    }


def build_policy_network() -> pypsa.Network:
    """
    Build a solvable AT/DE network with every element of the AT policy constraints.

    AT1 has renewables, a hydro store with turbine, biogas to gas, gas power,
    electrolysis, H2 power, a distribution grid and a heat pump; DE1 supplies
    gas and electricity.
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=3, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    for name, carrier, country in [
        ("AT1", "AC", "AT"),
        ("AT1 low voltage", "low voltage", "AT"),
        ("AT1 gas", "gas", "AT"),
        ("AT1 biogas", "biogas", "AT"),
        ("AT1 H2", "H2", "AT"),
        ("AT1 hydro", "hydro", "AT"),
        ("AT1 urban central heat", "urban central heat", "AT"),
        ("DE1", "AC", "DE"),
        ("DE1 gas", "gas", "DE"),
    ]:
        n.add("Bus", name, carrier=carrier, location=name.split()[0], country=country)

    solar = pd.Series([0.1, 0.6, 0.3], index=n.snapshots)
    n.add(
        "Generator",
        "AT1 solar",
        bus="AT1",
        carrier="solar",
        p_nom_extendable=True,
        p_nom_max=1000,
        p_max_pu=solar,
        capital_cost=1.0,
    )
    n.add(
        "Generator", "AT1 onwind", bus="AT1", carrier="onwind", p_nom=10, p_max_pu=0.4
    )
    n.add(
        "Generator",
        "AT1 ror",
        bus="AT1",
        carrier="ror",
        p_nom=5,
        p_max_pu=0.5,
        p_min_pu=0.5,
    )
    n.add(
        "Generator",
        "AT1 hydro inflow",
        bus="AT1 hydro",
        carrier="hydro inflow",
        p_nom=6,
        p_min_pu=1.0,
    )
    n.add("Store", "AT1 hydro store", bus="AT1 hydro", carrier="hydro", e_nom=100)
    n.add(
        "Link",
        "AT1 hydro discharger",
        bus0="AT1 hydro",
        bus1="AT1",
        carrier="hydro discharger",
        efficiency=0.9,
        p_nom=20,
    )
    n.add(
        "Generator",
        "AT1 biogas",
        bus="AT1 biogas",
        carrier="biogas",
        p_nom=20,
        marginal_cost=30,
    )
    n.add(
        "Link",
        "AT1 biogas to gas",
        bus0="AT1 biogas",
        bus1="AT1 gas",
        carrier="biogas to gas",
        p_nom=20,
    )
    n.add(
        "Generator",
        "DE1 gas",
        bus="DE1 gas",
        carrier="gas",
        p_nom=500,
        marginal_cost=20,
    )
    n.add(
        "Generator", "DE1 gen", bus="DE1", carrier="CCGT", p_nom=500, marginal_cost=60
    )
    n.add(
        "Link",
        "DE1 gas pipeline",
        bus0="DE1 gas",
        bus1="AT1 gas",
        carrier="gas pipeline",
        p_nom=100,
        p_min_pu=-1,
    )
    n.add(
        "Link",
        "AT1 OCGT",
        bus0="AT1 gas",
        bus1="AT1",
        carrier="OCGT",
        efficiency=0.4,
        p_nom=50,
    )
    n.add(
        "Link",
        "AT1 H2 Electrolysis",
        bus0="AT1",
        bus1="AT1 H2",
        carrier="H2 Electrolysis",
        efficiency=0.7,
        p_nom_extendable=True,
        capital_cost=1.0,
    )
    n.add(
        "Link",
        "AT1 H2 OCGT",
        bus0="AT1 H2",
        bus1="AT1",
        carrier="H2 OCGT",
        efficiency=0.4,
        p_nom=5,
        marginal_cost=-1.0,  # runs whenever possible
    )
    n.add(
        "Link",
        "AT1 electricity distribution grid",
        bus0="AT1",
        bus1="AT1 low voltage",
        carrier="electricity distribution grid",
        efficiency=0.97,
        p_nom=100,
        p_min_pu=-1,
    )
    n.add(
        "Link",
        "AT1 urban central air heat pump",
        bus0="AT1 urban central heat",
        bus1="AT1 low voltage",
        carrier="urban central air heat pump",
        efficiency=pd.Series([0.3, 0.35, 0.4], index=n.snapshots),
        p_nom=50,
        p_max_pu=0,
        p_min_pu=-1,
    )
    n.add(
        "Line", "AT1-DE1", bus0="AT1", bus1="DE1", s_nom=30, x=0.1, r=0.01, length=100
    )
    n.add("Load", "AT1 load", bus="AT1", p_set=30)
    n.add("Load", "AT1 low voltage load", bus="AT1 low voltage", p_set=10)
    n.add("Load", "AT1 H2 load", bus="AT1 H2", p_set=5)
    n.add("Load", "AT1 heat load", bus="AT1 urban central heat", p_set=10)
    n.add("Load", "DE1 load", bus="DE1", p_set=20)
    # unused ports, as in every PyPSA-Eur network
    for port in (2, 3, 4):
        n.links[f"bus{port}"] = ""
        n.links[f"efficiency{port}"] = 1.0
    n.meta = _meta()
    return n


@pytest.fixture(scope="module")
def solved_policy() -> pypsa.Network:
    """The policy toy network solved with the AT policy constraints of ``mods``."""
    n = build_policy_network()
    af = _pypsa_de_additional_functionality()
    snakemake = SimpleNamespace(
        config={
            "mods": {"net_zero_electricity": n.meta["mods"]["net_zero_electricity"]}
        },
        params=SimpleNamespace(
            solving={
                "constraints": {
                    "limits_volume_min": {
                        source: {"AT": {YEAR: 1e-6}}
                        for source in ("solar", "wind", "hydro", "biomass")
                    }
                }
            }
        ),
    )

    def extra(n, snapshots):
        constraint_production_targets(n, snakemake, YEAR)
        constraint_net_zero_electricity(n, snakemake, YEAR)
        af.add_capacity_limits(
            n, YEAR, {"Link": {"H2 Electrolysis": {"AT": {YEAR: 0.001}}}}, "minimum"
        )

    status, condition = n.optimize(solver_name="highs", extra_functionality=extra)
    assert status == "ok", condition
    return n


def _solver_value(n: pypsa.Network, name: str) -> float:
    """Return the left-hand side of a solved model constraint."""
    return float(n.model.constraints[f"GlobalConstraint-{name}"].lhs.solution.sum())


class TestPolicyMirror:
    """The re-evaluated constraint values equal the solver's (drift against mods)."""

    @pytest.mark.parametrize("source", ["solar", "wind", "hydro", "biomass"])
    def test_production(self, solved_policy, source):
        name = f"production_limit_lower-{source}-AT"
        assert dp.production(solved_policy, source, "AT") == pytest.approx(
            _solver_value(solved_policy, name), rel=1e-6, abs=1e-6
        )

    def test_hydro_inflow_weighted_by_turbine(self, solved_policy):
        # ror 5 MW * 0.5 + inflow 6 MW * 0.9, 3 snapshots of weight 2
        assert dp.production(solved_policy, "hydro", "AT") == pytest.approx(
            (2.5 + 5.4) * 6
        )

    def test_biomass_with_gas_only_under_net_zero(self, solved_policy):
        with_gas = dp.production(solved_policy, "biomass", "AT", eag=True)
        without = dp.production(solved_policy, "biomass", "AT", eag=False)
        assert without == 0.0  # no biomass-to-power link in the toy
        assert with_gas > 0

    def test_net_zero_electricity(self, solved_policy):
        value, fixed = dp.net_zero_electricity(solved_policy, "AT")
        name = "net-zero-electricity-production-AT"
        assert value == pytest.approx(_solver_value(solved_policy, name), rel=1e-6)
        assert fixed == pytest.approx(solved_policy.global_constraints.constant[name])

    def test_green_gas(self, solved_policy):
        assert dp.green_gas(solved_policy, "AT") == pytest.approx(
            _solver_value(solved_policy, "green-gas-production-AT"), rel=1e-6, abs=1e-6
        )

    def test_green_h2(self, solved_policy):
        assert dp.green_h2(solved_policy, "AT") == pytest.approx(
            _solver_value(solved_policy, "green-h2-production-AT"), rel=1e-6, abs=1e-6
        )

    def test_electrolysis(self, solved_policy):
        name = "capacity_minimum-AT-Link-H2-Electrolysis"
        assert dp.electrolysis_capacity(solved_policy, "AT") == pytest.approx(
            _solver_value(solved_policy, name), rel=1e-6
        )


# --- (1) checks ----------------------------------------------------------------


class TestConfigDiff:
    def test_ignored_keys(self):
        a = {"run": {"name": "a"}, "resources": {"x": 1}, "mods": {"a": 1}}
        b = {"run": {"name": "b"}, "resources": {"x": 2}, "mods": {"a": 1}}
        assert dp.config_diff(a, b) == set()

    def test_nan_equals_nan(self):
        assert dp.config_diff({"a": np.nan}, {"a": np.nan}) == set()

    def test_null_key_collapses_to_expected(self):
        run = {"budget": {"AT": None, "DE": 1}}
        ref = {"budget": {"AT": {"2030": 0.5, "2040": 0.0}, "DE": 1}}
        assert dp.config_diff(run, ref, {"budget.AT"}) == {"budget.AT"}

    def test_reports_unexpected(self):
        assert dp.config_diff({"a": 1, "b": 2}, {"a": 1, "b": 3}, {"c"}) == {"b"}


@pytest.mark.parametrize(
    "name, group",
    [
        ("co2_limit-AT", "national policy"),
        ("capacity_minimum-AT-Link-H2-Electrolysis", "national policy"),
        ("CO2Limit-upper", "EU / DE"),
        ("co2_limit-DE", "EU / DE"),
        ("capacity_maximum-DE-Generator-onwind", "EU / DE"),
        ("tyndp-combined-solar-upper", "TYNDP & trajectories"),
        ("co2_sequestration_limit", "EU / DE"),
        ("H2_export_ban-DEX", "other"),
    ],
)
def test_constraint_group(name, group):
    assert dp.constraint_group(name, "AT") == group


def test_global_constraints_sums_tyndp():
    n = pypsa.Network()
    n.add("GlobalConstraint", "tyndp-x[AT solar]", constant=1.0, mu=2.0)
    n.add("GlobalConstraint", "tyndp-x[DE solar]", constant=1.0, mu=0.0)
    n.add("GlobalConstraint", "co2_limit-AT", constant=5.0, mu=-3.0)
    table = dp.global_constraints({"s": {"2030": n}}, "AT")
    row = table.loc[("s", "2030", "tyndp-x")]
    assert (row["count"], row.binding, row.mu) == (2, 1, 2.0)
    assert table.loc[("s", "2030", "co2_limit-AT"), "group"] == "national policy"


def test_add_deltas():
    index = pd.MultiIndex.from_product([["a", "b"], ["2030", "2040"]])
    index.names = ["scenario", "horizon"]
    table = pd.DataFrame({"x": [1.0, 2.0, 4.0, 7.0]}, index=index)
    out = dp.add_deltas(table, "a")
    assert out["Δ x"].tolist() == [0.0, 0.0, 3.0, 5.0]


# --- (A) potentials ------------------------------------------------------------


def build_potential_network() -> pypsa.Network:
    """Two AT locations with existing and extendable wind and ground PV."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    for node in ("AT11", "AT12", "DE1"):
        n.add("Bus", node, carrier="AC", location=node)
    rows = [
        # name, bus, carrier, extendable, p_nom, p_nom_min, p_nom_max, p_nom_opt
        ("AT11 onwind-2020", "AT11", "onwind", False, 4, 0, np.inf, 4),
        ("AT11 onwind-2030", "AT11", "onwind", True, 0, 0, 6, 6),  # at cap
        ("AT12 onwind-2030", "AT12", "onwind", True, 0, 5, 5, 5),  # forced
        ("AT11 solar-2030", "AT11", "solar", True, 0, 0, 10, 3),
        ("AT11 solar-hsat-2030", "AT11", "solar-hsat", True, 0, 0, 10, 7),  # shared
        ("DE1 onwind-2030", "DE1", "onwind", True, 0, 0, 100, 1),
    ]
    for name, bus, carrier, ext, p_nom, p_min, p_max, opt in rows:
        n.add(
            "Generator",
            name,
            bus=bus,
            carrier=carrier,
            p_nom_extendable=ext,
            p_nom=p_nom,
            p_nom_min=p_min,
            p_nom_max=p_max,
            p_max_pu=0.5,
        )
        n.generators.loc[name, "p_nom_opt"] = opt
    n.generators_t.p = pd.DataFrame(
        {g: [n.generators.p_nom_opt[g] * 0.4] * 2 for g in n.generators.index},
        index=n.snapshots,
    )
    return n


class TestPotentials:
    @pytest.fixture
    def table(self):
        return dp.potentials(build_potential_network(), "AT")

    def test_potential_is_headroom_plus_existing(self, table):
        assert table.potential[("AT11", "onwind")] == 10
        assert table.capacity[("AT11", "onwind")] == 10

    def test_ground_pv_shares_the_solar_potential(self, table):
        assert table.potential[("AT11", "ground PV")] == 10
        assert table.capacity[("AT11", "ground PV")] == 10
        assert table.binding[("AT11", "ground PV")]

    def test_binding_and_forced(self, table):
        assert table.binding[("AT11", "onwind")]
        assert table.forced[("AT12", "onwind")]
        assert not table.binding[("AT12", "onwind")]

    def test_other_countries_left_out(self, table):
        assert "DE1" not in table.index.get_level_values("location")

    def test_production_and_available(self, table):
        assert table.production[("AT11", "onwind")] == pytest.approx(10 * 0.4 * 2)
        assert table.available[("AT11", "onwind")] == pytest.approx(10 * 0.5 * 2)

    def test_summary(self):
        summary = dp.potential_summary({"s": {"2030": build_potential_network()}}, "AT")
        onwind = summary.loc[("s", "2030", "onwind")]
        assert onwind["binding buses"] == 1
        assert onwind["forced buses"] == 1
        assert onwind.potential == pytest.approx(15 / dp.GW)
        assert onwind.utilisation == pytest.approx(1.0)


# --- (B) regions ---------------------------------------------------------------


def _regional_network(nodes: dict[str, float]) -> pypsa.Network:
    n = pypsa.Network()
    for node, capacity in nodes.items():
        n.add("Bus", node, carrier="AC", location=node)
        n.add("Generator", f"{node} onwind", bus=node, carrier="onwind")
        n.generators.loc[f"{node} onwind", "p_nom_opt"] = capacity
    return n


class TestRegions:
    def test_region(self):
        locations = pd.Series(["AT111", "AT333", "AT11", "DE1"])
        assert dp.region(locations).tolist() == ["AT11", "AT33", "AT11", "DE1"]

    def test_fine_run_summed_to_nuts2(self):
        fine = _regional_network({"AT111": 1000, "AT112": 2000, "AT121": 500})
        coarse = _regional_network({"AT11": 2500, "AT12": 500, "AT13": 100})
        networks = {"fine": {"2030": fine}, "coarse": {"2030": coarse}}
        out = dp.regional_comparison(networks, "AT", "fine", "coarse")
        onwind = out.xs(("2030", "onwind"), level=["horizon", "technology"])
        assert onwind.reference.to_dict() == {"AT11": 3.0, "AT12": 0.5, "AT13": 0.0}
        assert onwind["Δ"].to_dict() == {"AT11": -0.5, "AT12": 0.0, "AT13": 0.1}

        shift = dp.regional_shift(out).loc[("2030", "onwind")]
        assert shift["Δ total"] == pytest.approx(-0.4)
        assert shift["shift"] == pytest.approx(0.6 / 3.5)


# --- (B ii) transmission -------------------------------------------------------


def build_transmission_network() -> pypsa.Network:
    """Three AT buses in two NUTS 2 regions and one DE bus."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = 3.0
    for node in ("AT111", "AT112", "AT121", "DE1"):
        n.add("Bus", node, carrier="AC", location=node)
    n.add("Line", "inside", bus0="AT111", bus1="AT112", s_nom=10, length=10)
    n.add("Line", "cross", bus0="AT112", bus1="AT121", s_nom=10, length=50)
    n.add("Line", "abroad", bus0="AT121", bus1="DE1", s_nom=10, length=100)
    n.lines["s_nom_opt"] = [10.0, 12.0, 10.0]
    # opposite flows: net zero, gross not
    n.lines_t.p0 = pd.DataFrame(
        {"inside": [5.0, -5.0], "cross": [12.0, 6.0], "abroad": [10.0, 10.0]},
        index=n.snapshots,
    )
    return n


class TestTransmission:
    @pytest.fixture
    def table(self):
        return dp.transmission(build_transmission_network(), "AT")

    def test_gross_not_net(self, table):
        assert table.energy[("AC", "all")] == pytest.approx((10 + 18) * 3 / dp.TWH)

    def test_transport_work(self, table):
        work = (10 * 3 * 10 + 18 * 3 * 50) / dp.TWH
        assert table["transport work"][("AC", "all")] == pytest.approx(work)

    def test_cross_region_view(self, table):
        assert table.branches[("AC", "cross-region")] == 1
        assert table.added[("AC", "cross-region")] == pytest.approx(2 / dp.GW)

    def test_time_at_limit(self, table):
        assert table["time at limit"][("AC", "cross-region")] == pytest.approx(0.5)

    def test_foreign_branches_left_out(self, table):
        assert table.branches[("AC", "all")] == 2


# --- (C) policy elements -------------------------------------------------------


def test_net_imports(solved_policy):
    imports = dp.net_imports(solved_policy, "AT")
    weights = solved_policy.snapshot_weightings.generators
    line = -(solved_policy.lines_t.p0["AT1-DE1"] * weights).sum() / dp.TWH
    gas = (solved_policy.links_t.p0["DE1 gas pipeline"] * weights).sum() / dp.TWH
    assert imports["AC"] == pytest.approx(line)
    assert imports["gas"] == pytest.approx(gas)


def test_electrolysis_total(solved_policy):
    assert dp.electrolysis_total(solved_policy, "AT") == pytest.approx(
        solved_policy.links.p_nom_opt["AT1 H2 Electrolysis"]
    )


def build_supply_network() -> pypsa.Network:
    """
    Build an AT/DE network with a fixed dispatch (2 snapshots, weight 1).

    AT1 produces solar power, power from a gas CHP that emits to the EU
    ``co2 atmosphere``, H2 from electrolysis and Fischer-Tropsch fuel onto the
    EU oil copper plate; it imports power and gas from DE, an ``import H2``
    generator and land transport oil from the EU plate; it charges a battery.
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    for name, carrier, location in [
        ("AT1", "AC", "AT1"),
        ("AT1 gas", "gas", "AT1"),
        ("AT1 H2", "H2", "AT1"),
        ("AT1 battery", "battery", "AT1"),
        ("AT1 land transport oil", "land transport oil", "AT1"),
        ("DE1", "AC", "DE1"),
        ("DE1 gas", "gas", "DE1"),
        ("EU oil", "oil", "EU"),
        ("co2 atmosphere", "co2", "EU"),
    ]:
        n.add("Bus", name, carrier=carrier, location=location)
    n.add("Generator", "AT1 solar", bus="AT1", carrier="solar")
    n.add("Generator", "AT1 import H2", bus="AT1 H2", carrier="import H2")
    n.add("Line", "AT1-DE1", bus0="AT1", bus1="DE1", x=0.1, s_nom=10)
    n.add("Store", "AT1 battery", bus="AT1 battery", carrier="battery")
    links = {  # name: (bus0, bus1, bus2, carrier, p0, p1, p2)
        "DE1 gas pipeline": ("DE1 gas", "AT1 gas", "", "gas pipeline", 5, -5, 0),
        "AT1 CHP": ("AT1 gas", "AT1", "co2 atmosphere", "CHP", 4, -2, -0.8),
        "AT1 H2 Electrolysis": ("AT1", "AT1 H2", "", "H2 Electrolysis", 2, -1.4, 0),
        "AT1 land transport oil": (
            "EU oil",
            "AT1 land transport oil",
            "co2 atmosphere",
            "land transport oil",
            3,
            -3,
            -0.8,
        ),
        "AT1 Fischer-Tropsch": ("AT1 H2", "EU oil", "", "Fischer-Tropsch", 1, -0.7, 0),
        "AT1 battery charger": (
            "AT1",
            "AT1 battery",
            "",
            "battery charger",
            1,
            -0.9,
            0,
        ),
    }
    for name, (bus0, bus1, bus2, carrier, *_) in links.items():
        n.add("Link", name, bus0=bus0, bus1=bus1, bus2=bus2, carrier=carrier)
    for port in range(3):
        n.links_t[f"p{port}"] = pd.DataFrame(
            {name: v[4 + port] for name, v in links.items()}, index=n.snapshots
        )
    n.generators_t.p = pd.DataFrame(
        {"AT1 solar": 10.0, "AT1 import H2": 1.0}, index=n.snapshots
    )
    n.lines_t.p0 = pd.DataFrame({"AT1-DE1": -3.0}, index=n.snapshots)
    n.lines_t.p1 = pd.DataFrame({"AT1-DE1": 3.0}, index=n.snapshots)
    return n


class TestEnergySupply:
    @pytest.fixture
    def supply(self):
        return dp.energy_supply(build_supply_network(), "AT") * dp.TWH  # MWh

    def test_electricity(self, supply):
        # solar 2 * 10 + CHP 2 * 2; battery charging is a transfer
        assert supply.loc["electricity", "produced"] == pytest.approx(24)
        assert supply.loc["electricity", "net import"] == pytest.approx(6)

    def test_gas_burnt_with_co2_to_eu_is_no_export(self, supply):
        assert supply.loc["methane", "produced"] == pytest.approx(0)
        assert supply.loc["methane", "net import"] == pytest.approx(10)

    def test_import_generator_is_import(self, supply):
        assert supply.loc["hydrogen", "produced"] == pytest.approx(2.8)
        assert supply.loc["hydrogen", "net import"] == pytest.approx(2)

    def test_eu_copper_plate(self, supply):
        # 6 from the EU plate into AT, minus 1.4 Fischer-Tropsch put onto it
        assert supply.loc["liquid fuels", "produced"] == pytest.approx(1.4)
        assert supply.loc["liquid fuels", "net import"] == pytest.approx(4.6)


def test_net_imports_skip_conversion_links_abroad():
    imports = dp.net_imports(build_supply_network(), "AT") * dp.TWH
    assert imports["AC"] == pytest.approx(6)
    assert imports["gas"] == pytest.approx(10)
    assert "H2" not in imports


def test_policy_attainment_units():
    index = pd.MultiIndex.from_tuples(
        [
            ("DP_base", "2030", "co2_limit-AT"),
            ("DP_base", "2030", "capacity_minimum-AT-Link-H2-Electrolysis"),
            ("DP_base", "2030", "production_limit_lower-wind-AT"),
            ("DP_base", "2030", "co2_limit-DE"),
        ],
        names=["scenario", "horizon", "constraint"],
    )
    status = pd.DataFrame(
        {
            "value": [2e6, 1e3, 3e7, 1.0],
            "target": [3e6, 1e3, 2e7, 1.0],
            "slack": [1e6, 0.0, 1e7, 0.0],
            "mu": [0.0, 5.0, 0.0, 0.0],
            "binding": [False, True, False, False],
        },
        index=index,
    )
    out = dp.policy_attainment(status, "AT").set_index("label")
    assert list(out.index) == ["CO2 budget", "EAG wind", "Electrolysis"]
    assert out.loc["CO2 budget", ["value", "unit"]].tolist() == [2.0, "Mt CO2"]
    assert out.loc["EAG wind", ["value", "slack", "unit"]].tolist() == [30, 10, "TWh"]
    assert out.loc["Electrolysis", ["value", "unit"]].tolist() == [1.0, "GW"]
