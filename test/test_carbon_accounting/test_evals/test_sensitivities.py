# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for evals/carbon_accounting/sensitivities.py on toy networks."""

import numpy as np
import pandas as pd
import pypsa
import pytest

from evals.carbon_accounting import sensitivities as sens


def build_border_network(at_de_max: float = 3000.0) -> pypsa.Network:
    """
    Return a solvable AT/DE/CH network with AC lines and DC links.

    AT1 and AT2 have a load, DE1 cheap onwind; AT1 has ror. Lines AT1-AT2
    (domestic), AT1-DE1 (cross-border) and DE1-CH1 (abroad), and a DC link
    AT2-DE1 (cross-border).
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    for bus in ("AT1", "AT2", "DE1", "CH1"):
        n.add("Bus", bus, carrier="AC", location=bus, country=bus[:2])
    n.add("Carrier", ["AC", "DC", "onwind", "ror"])
    n.add("Load", ["AT1 load", "AT2 load"], bus=["AT1", "AT2"], p_set=100.0)
    n.add("Load", "CH1 load", bus="CH1", p_set=50.0)
    n.add(
        "Generator",
        "DE1 onwind",
        bus="DE1",
        carrier="onwind",
        p_nom=1000.0,
        marginal_cost=1.0,
    )
    n.add(
        "Generator",
        "AT1 ror",
        bus="AT1",
        carrier="ror",
        p_nom=20.0,
        marginal_cost=0.0,
    )
    for name, bus0, bus1, s_max in [
        ("AT-AT", "AT1", "AT2", 3000.0),
        ("AT-DE", "AT1", "DE1", at_de_max),
        ("DE-CH", "DE1", "CH1", 3000.0),
    ]:
        n.add(
            "Line",
            name,
            bus0=bus0,
            bus1=bus1,
            x=0.1,
            r=0.01,
            s_nom=10.0,
            s_nom_max=s_max,
            s_nom_extendable=True,
            capital_cost=1.0,
        )
    n.add(
        "Link",
        "DC AT-DE",
        bus0="AT2",
        bus1="DE1",
        carrier="DC",
        p_min_pu=-1.0,
        p_nom=0.0,
        p_nom_max=at_de_max,
        p_nom_extendable=True,
        capital_cost=1.0,
    )
    status, condition = n.optimize(solver_name="highs")
    assert status == "ok", condition
    energy_totals = pd.DataFrame(
        {
            "total domestic aviation": {"AT": 1.0},
            "total international aviation": {"AT": 1.0},
        }
    )
    n.meta = {"resources": {"energy_totals": energy_totals.to_dict(orient="tight")}}
    return n


@pytest.fixture(scope="module")
def border() -> pypsa.Network:
    return build_border_network()


class TestSolveStatus:
    HORIZONS = ["2025", "2030", "2040"]

    def table(self, causes=None):
        files = {"A": {"2025": "a", "2030": "a", "2040": "a"}, "B": {"2025": "b"}}
        return sens.solve_status(files, ["A", "B", "C"], self.HORIZONS, causes)

    def test_solved(self):
        assert (self.table().loc["A"] == "solved").all()

    def test_later_horizons_not_reached(self):
        assert self.table().loc["B"].tolist() == [
            "solved",
            "not solved",
            "not reached",
        ]

    def test_missing_run(self):
        assert self.table().loc["C"].tolist() == [
            "not solved",
            "not reached",
            "not reached",
        ]

    def test_documented_cause(self):
        table = self.table({("B", "2030"): "infeasible: EU cap 0 in 2040"})
        assert table.at["B", "2030"] == "not solved: infeasible: EU cap 0 in 2040"


def test_every_sensitivity_has_a_reference():
    assert set(sens.SENSITIVITY_REFERENCES) == set(sens.SENSITIVITY_DIFFERENCES)


def test_points_use_known_runs():
    known = {*sens.SENSITIVITY_DIFFERENCES, *sens.SENSITIVITY_REFERENCES.values()}
    known |= {sens.DP1}
    for p in sens.POINTS:
        assert {p.run, p.reference} <= known
        assert p.family in sens.FAMILIES
    assert set(sens.SENSITIVITY_DIFFERENCES) <= set(sens.runs())


def _headlines(values: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Return a headline table with one metric: scenario -> horizon -> value."""
    rows = {
        (scenario, horizon, "cost", "total"): value
        for scenario, horizons in values.items()
        for horizon, value in horizons.items()
    }
    table = pd.Series(rows).to_frame("value")
    table.index.names = ["scenario", "horizon", "group", "metric"]
    return table


class TestEffects:
    def test_run_minus_reference(self):
        table = _headlines({"A": {"2030": 5.0}, "B": {"2030": 2.0}})
        effect = sens.effects(table, [sens.Point("S9", "p", "A", "B")])
        row = effect.loc[("S9", "p", "2030", "cost", "total")]
        assert row.tolist() == [5.0, 2.0, 3.0]

    def test_only_common_horizons(self):
        table = _headlines(
            {"A": {"2030": 5.0, "2040": 1.0}, "B": {"2030": 2.0, "2050": 0.0}}
        )
        effect = sens.effects(table, [sens.Point("S9", "p", "A", "B")])
        assert effect.index.unique("horizon").tolist() == ["2030"]

    def test_missing_run_is_skipped(self):
        table = _headlines({"A": {"2030": 5.0}})
        effect = sens.effects(table, [sens.Point("S9", "p", "A", "B")])
        assert effect.empty

    def test_missing_metric_stays_nan(self):
        table = _headlines({"A": {"2030": 5.0}, "B": {"2030": 2.0}})
        extra = pd.DataFrame(
            {"value": [1.0]},
            index=pd.MultiIndex.from_tuples(
                [("A", "2030", "CO2", "budget")], names=table.index.names
            ),
        )
        effect = sens.effects(
            pd.concat([table, extra]), [sens.Point("S9", "p", "A", "B")]
        )
        assert np.isnan(effect.loc[("S9", "p", "2030", "CO2", "budget"), "effect"])


def test_interaction():
    table = _headlines(
        {
            sens.DP3_WITH: {"2030": 10.0},
            "DP3S_targets_only": {"2030": 12.0},
            "DP3S_embedding_only": {"2030": 13.0},
            sens.DP3_NO: {"2030": 16.0},
        }
    )
    split = sens.interaction(sens.effects(table))
    row = split.loc[("2030", "cost", "total")]
    assert row.to_dict() == {
        "targets": 2.0,
        "embedding": 3.0,
        "full": 6.0,
        "interaction": 1.0,
    }


def test_interaction_without_s2():
    split = sens.interaction(sens.effects(_headlines({"A": {"2030": 1.0}})))
    assert split.empty
    assert split.index.names == ["horizon", "group", "metric"]


def test_effect_matrix_keeps_the_point_order():
    table = _headlines(
        {
            sens.DP3_WITH: {"2030": 0.0},
            "DP3S_extension_double": {"2030": 3.0},
            "DP3S_extension_half": {"2030": 1.0},
            sens.DP3_NO: {"2030": 2.0},
        }
    )
    matrix = sens.effect_matrix(sens.effects(table), "S4", "cost")
    assert matrix.columns.get_level_values("point").tolist() == [
        "half",
        "upstream",
        "double",
    ]
    assert matrix.loc["total"].tolist() == [1.0, 2.0, 3.0]


class TestCrossBorder:
    def test_capacity(self, border):
        capacity = sens.cross_border_capacity(border, "AT")
        expected_ac = border.lines.s_nom_opt["AT-DE"] / 1e3
        expected_dc = border.links.p_nom_opt["DC AT-DE"] / 1e3
        assert capacity["AC"] == pytest.approx(expected_ac)
        assert capacity["DC"] == pytest.approx(expected_dc)

    def test_bounds_of_cross_border_branches_changed(self, border):
        check = sens.bound_changes(build_border_network(1500.0), border, "AT")
        assert check.status == "ok", check.message
        assert set(check.details.index.get_level_values("name")) == {
            "AT-DE",
            "DC AT-DE",
        }

    def test_other_branch_changed_fails(self, border):
        n = build_border_network()
        n.lines.loc["DE-CH", "s_nom_max"] = 10.0
        n.lines.loc["AT-DE", "s_nom_max"] = 10.0
        n.links.loc["DC AT-DE", "p_nom_max"] = 10.0
        check = sens.bound_changes(n, border, "AT")
        assert check.status == "fail"
        assert "outside" in check.message

    def test_unchanged_cross_border_fails(self, border):
        check = sens.bound_changes(border, border, "AT")
        assert check.status == "fail"
        assert "kept" in check.message


class TestHeadline:
    @pytest.fixture(scope="class")
    def values(self, border) -> pd.Series:
        return sens.headline(border, "AT")

    def test_groups(self, values):
        assert set(values.index.unique("group")) == set(sens.UNITS)

    def test_no_budget(self, values):
        assert np.isnan(values[("CO2", "budget")])

    def test_ror_capacity(self, values):
        assert values[("capacity", "ror")] == pytest.approx(0.02)

    def test_net_electricity_import(self, values, border):
        # AT imports its load minus the ror production
        imported = (200.0 - 20.0) * 2 / 1e6
        assert values[("net import", "electricity")] == pytest.approx(imported)

    def test_headlines_stack(self, border):
        table = sens.headlines({"A": {"2030": border}}, "AT")
        assert table.index.names == ["scenario", "horizon", "group", "metric"]
        assert sens.headlines({}, "AT").empty
