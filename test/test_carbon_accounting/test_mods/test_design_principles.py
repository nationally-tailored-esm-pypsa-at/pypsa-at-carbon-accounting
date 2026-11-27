# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests of the design-principle switches (mods/carbon_accounting/design_principles.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pypsa
import pytest

import mods.network.common as common
from mods.carbon_accounting import (
    apply_cross_border_extension_limits,
    fix_unpaired_gas_pipelines,
    onwind_brownfield_enabled,
)
from mods.carbon_accounting.design_principles import cross_border
from mods.network.gas import check_retrofit_pairing


@pytest.mark.parametrize("enable", [True, False])
def test_onwind_brownfield_enabled(enable):
    config = {"mods": {"carbon_accounting": {"onwind_brownfield": {"enable": enable}}}}
    assert onwind_brownfield_enabled(config) is enable


@pytest.mark.parametrize("enable", [True, False])
def test_modify_prenetwork_skips_onwind_brownfield(monkeypatch, enable):
    """The hook in modify_prenetwork calls the KLIEN brownfield only when enabled."""
    calls = []
    for name in dir(common):
        obj = getattr(common, name)
        if (
            callable(obj)
            and getattr(obj, "__module__", "").startswith("mods.")
            and name not in ("modify_prenetwork", "onwind_brownfield_enabled")
        ):
            monkeypatch.setattr(common, name, lambda *a, **k: None)
    monkeypatch.setattr(common, "apply_onwind_brownfield", lambda *a: calls.append(a))
    monkeypatch.setattr("scripts._helpers.load_costs", lambda *a, **k: None)
    snakemake = SimpleNamespace(
        config={
            "mods": {"carbon_accounting": {"onwind_brownfield": {"enable": enable}}}
        },
        input=SimpleNamespace(tech_costs=None),
        wildcards=SimpleNamespace(horizon="2030"),
    )
    common.modify_prenetwork(MagicMock(), snakemake)
    assert bool(calls) is enable


UPSTREAM_LINE, UPSTREAM_LINK = 20000.0, 30000.0


def build_branch_network() -> pypsa.Network:
    """
    Return AT, DE and CH buses with lines and links as after the brownfield.

    ``s_nom_max`` / ``p_nom_max`` follow ``prepare_network.py`` (base capacity
    plus the upstream extension); the brownfield then moved ``s_nom`` to the
    previous ``s_nom_opt`` and set the minimum capacities.
    """
    n = pypsa.Network()
    for bus, country in [("AT1", "AT"), ("AT2", "AT"), ("DE1", "DE"), ("CH1", "CH")]:
        n.add("Bus", bus, carrier="AC", country=country)
    n.add("Bus", "AT1 H2", carrier="H2", country="AT")
    n.add("Bus", "DE1 H2", carrier="H2", country="DE")
    for name, bus0, bus1, extendable in [
        ("AT-AT", "AT1", "AT2", True),
        ("AT-DE", "AT1", "DE1", True),
        ("DE-AT", "DE1", "AT2", True),
        ("DE-CH", "DE1", "CH1", True),
        ("AT-CH fixed", "AT1", "CH1", False),
    ]:
        n.add(
            "Line",
            name,
            bus0=bus0,
            bus1=bus1,
            x=0.1,
            s_nom=1500.0,  # previous s_nom_opt
            s_nom_min=1500.0,
            s_nom_max=1000.0 + UPSTREAM_LINE,  # base s_nom 1000
            s_nom_extendable=extendable,
        )
    for name, bus0, bus1, carrier in [
        ("DC AT-DE", "AT1", "DE1", "DC"),
        ("DC AT-AT", "AT1", "AT2", "DC"),
        ("DC DE-CH", "DE1", "CH1", "DC"),
        ("H2 AT-DE", "AT1 H2", "DE1 H2", "H2 pipeline"),
    ]:
        n.add(
            "Link",
            name,
            bus0=bus0,
            bus1=bus1,
            carrier=carrier,
            p_nom=500.0,
            p_nom_min=800.0,
            p_nom_max=500.0 + UPSTREAM_LINK,
            p_nom_extendable=True,
        )
    return n


def limits_snakemake(
    lines: float | None = 10000.0,
    links: float | None = 15000.0,
    enable: bool = True,
    upstream_line: float | None = UPSTREAM_LINE,
) -> SimpleNamespace:
    return SimpleNamespace(
        config={
            "mods": {
                "carbon_accounting": {
                    "cross_border_extension_limits": {
                        "enable": enable,
                        "countries": ["AT"],
                        "s_nom_max_extension": lines,
                        "p_nom_max_extension": links,
                    }
                }
            },
            "lines": {"s_nom_max_extension": upstream_line},
            "links": {"p_nom_max_extension": UPSTREAM_LINK},
        }
    )


class TestCrossBorderExtensionLimits:
    @pytest.fixture
    def limited(self) -> tuple[pypsa.Network, pypsa.Network]:
        before = build_branch_network()
        after = build_branch_network()
        apply_cross_border_extension_limits(after, limits_snakemake())
        return before, after

    def test_at_cross_border_lines_on_the_upstream_basis(self, limited):
        _, n = limited
        # base s_nom (1000) plus the new extension, not s_nom (previous s_nom_opt)
        assert n.lines.s_nom_max["AT-DE"] == 11000.0
        assert n.lines.s_nom_max["DE-AT"] == 11000.0

    def test_at_cross_border_dc_links(self, limited):
        _, n = limited
        assert n.links.p_nom_max["DC AT-DE"] == 15500.0

    @pytest.mark.parametrize(
        "component, name",
        [
            ("lines", "AT-AT"),
            ("lines", "DE-CH"),
            ("lines", "AT-CH fixed"),
            ("links", "DC AT-AT"),
            ("links", "DC DE-CH"),
            ("links", "H2 AT-DE"),
        ],
    )
    def test_other_branches_keep_their_bounds(self, limited, component, name):
        before, after = limited
        attr = "s_nom_max" if component == "lines" else "p_nom_max"
        assert (
            getattr(after, component).at[name, attr]
            == getattr(before, component).at[name, attr]
        )

    @pytest.mark.parametrize(
        "snakemake",
        [limits_snakemake(None, None), limits_snakemake(enable=False)],
        ids=["null", "disabled"],
    )
    def test_no_change(self, snakemake):
        n = build_branch_network()
        apply_cross_border_extension_limits(n, snakemake)
        reference = build_branch_network()
        assert n.lines.compare(reference.lines).empty
        assert n.links.compare(reference.links).empty

    def test_only_lines(self):
        n = build_branch_network()
        apply_cross_border_extension_limits(n, limits_snakemake(links=None))
        assert n.lines.s_nom_max["AT-DE"] == 11000.0
        assert n.links.p_nom_max["DC AT-DE"] == 500.0 + UPSTREAM_LINK

    def test_bound_below_minimum_raises(self):
        n = build_branch_network()
        with pytest.raises(ValueError, match="below s_nom_min of AT-DE, DE-AT"):
            apply_cross_border_extension_limits(n, limits_snakemake(lines=100.0))

    def test_rounding_below_minimum_is_clipped(self):
        n = build_branch_network()
        # base 1000 + 499.9999 lies 1e-4 MW below s_nom_min (1500)
        apply_cross_border_extension_limits(n, limits_snakemake(lines=499.9999))
        assert n.lines.s_nom_max["AT-DE"] == 1500.0

    def test_missing_upstream_limit_raises(self):
        n = build_branch_network()
        with pytest.raises(ValueError, match="upstream s_nom_max_extension"):
            apply_cross_border_extension_limits(n, limits_snakemake(upstream_line=None))


def test_cross_border():
    n = build_branch_network()
    lines = n.lines
    result = cross_border(n, lines.bus0, lines.bus1, ["AT"])
    assert result[result].index.tolist() == ["AT-DE", "DE-AT", "AT-CH fixed"]


def test_modify_prenetwork_calls_cross_border_limits(monkeypatch):
    """The hook in modify_prenetwork calls the S4 limits."""
    calls = []
    for name in dir(common):
        obj = getattr(common, name)
        if (
            callable(obj)
            and getattr(obj, "__module__", "").startswith("mods.")
            and name not in ("modify_prenetwork", "onwind_brownfield_enabled")
        ):
            monkeypatch.setattr(common, name, lambda *a, **k: None)
    monkeypatch.setattr(
        common, "apply_cross_border_extension_limits", lambda *a: calls.append(a)
    )
    monkeypatch.setattr("scripts._helpers.load_costs", lambda *a, **k: None)
    snakemake = SimpleNamespace(
        config={"mods": {"carbon_accounting": {"onwind_brownfield": {"enable": True}}}},
        input=SimpleNamespace(tech_costs=None),
        wildcards=SimpleNamespace(horizon="2030"),
    )
    common.modify_prenetwork(MagicMock(), snakemake)
    assert len(calls) == 1


def test_bound_set_by_another_step_is_kept():
    """A DC project that cannot be built yet (p_nom_max = 0) keeps its bound."""
    n = build_branch_network()
    n.links.loc["DC AT-DE", ["p_nom_min", "p_nom_max"]] = 0.0
    apply_cross_border_extension_limits(n, limits_snakemake())
    assert n.links.p_nom_max["DC AT-DE"] == 0.0
    assert n.lines.s_nom_max["AT-DE"] == 11000.0


def build_gas_network(de_candidates_extendable: bool = False) -> pypsa.Network:
    """
    Return gas pipelines AT-DE and DE-DE with their H2 retrofit candidates in 2030.

    As in PyPSA-DE up to 2030, the DE-internal candidate is not extendable
    (Kernnetz assumption) unless ``de_candidates_extendable``.
    """
    n = pypsa.Network()
    for bus in ("AT1", "DE1", "DE2"):
        n.add("Bus", f"{bus} gas", carrier="gas")
        n.add("Bus", f"{bus} H2", carrier="H2")
    for a, b, extendable in [
        ("AT1", "DE1", True),
        ("DE1", "DE2", de_candidates_extendable),
    ]:
        n.add(
            "Link",
            f"gas pipeline {a} -> {b}",
            bus0=f"{a} gas",
            bus1=f"{b} gas",
            carrier="gas pipeline",
            p_nom=1000.0,
            p_nom_extendable=True,
        )
        n.add(
            "Link",
            f"H2 pipeline retrofitted {a} -> {b}-2030",
            bus0=f"{a} H2",
            bus1=f"{b} H2",
            carrier="H2 pipeline retrofitted",
            p_nom_extendable=extendable,
        )
    return n


def gas_snakemake(threshold: int = 2020, horizon: str = "2030", enable: bool = True):
    return SimpleNamespace(
        config={
            "mods": {
                "modify_brownfield_gas_network_AT": enable,
                "threshold_year_for_gas_grid_expansion": threshold,
            }
        },
        wildcards=SimpleNamespace(horizon=horizon),
    )


class TestFixUnpairedGasPipelines:
    def test_unpaired_pipeline_fixed_after_threshold(self):
        n = build_gas_network()
        fix_unpaired_gas_pipelines(n, gas_snakemake())
        extendable = n.links.p_nom_extendable
        assert not extendable["gas pipeline DE1 -> DE2"]
        assert extendable["gas pipeline AT1 -> DE1"]
        assert n.links.p_nom["gas pipeline DE1 -> DE2"] == 1000.0

    def test_pairing_check_passes_afterwards(self):
        n = build_gas_network()
        with pytest.raises(ValueError, match="not paired"):
            check_retrofit_pairing(n)
        fix_unpaired_gas_pipelines(n, gas_snakemake())
        check_retrofit_pairing(n)

    @pytest.mark.parametrize(
        "snakemake",
        [
            gas_snakemake(threshold=2030),
            gas_snakemake(threshold=2040),
            gas_snakemake(enable=False),
        ],
        ids=["at-threshold", "before-threshold", "disabled"],
    )
    def test_no_change(self, snakemake):
        """Up to the threshold year fix_gas_grid_capacity does this itself."""
        n = build_gas_network()
        fix_unpaired_gas_pipelines(n, snakemake)
        assert n.links.compare(build_gas_network().links).empty

    def test_all_paired_no_change(self):
        n = build_gas_network(de_candidates_extendable=True)
        fix_unpaired_gas_pipelines(n, gas_snakemake(horizon="2050"))
        assert n.links.p_nom_extendable.all()

    def test_no_candidates_no_change(self):
        """Before the retrofit start year there are no candidates to pair."""
        n = build_gas_network()
        n.links.loc[
            n.links.carrier == "H2 pipeline retrofitted", "p_nom_extendable"
        ] = False
        fix_unpaired_gas_pipelines(n, gas_snakemake())
        assert n.links.p_nom_extendable[n.links.carrier == "gas pipeline"].all()


def test_modify_prenetwork_fixes_unpaired_before_the_check(monkeypatch):
    """The hook runs after the AT gas modifications and before the pairing check."""
    calls = []
    for name in dir(common):
        obj = getattr(common, name)
        if (
            callable(obj)
            and getattr(obj, "__module__", "").startswith("mods.")
            and name not in ("modify_prenetwork", "onwind_brownfield_enabled")
        ):
            monkeypatch.setattr(common, name, lambda *a, **k: None)
    for name in (
        "deduct_retrofitted_gas_capacity",
        "fix_unpaired_gas_pipelines",
        "check_retrofit_pairing",
    ):
        monkeypatch.setattr(common, name, lambda *a, name=name: calls.append(name))
    monkeypatch.setattr("scripts._helpers.load_costs", lambda *a, **k: None)
    snakemake = SimpleNamespace(
        config={"mods": {"carbon_accounting": {"onwind_brownfield": {"enable": True}}}},
        input=SimpleNamespace(tech_costs=None),
        wildcards=SimpleNamespace(horizon="2030"),
    )
    common.modify_prenetwork(MagicMock(), snakemake)
    assert calls == [
        "deduct_retrofitted_gas_capacity",
        "fix_unpaired_gas_pipelines",
        "check_retrofit_pairing",
    ]
