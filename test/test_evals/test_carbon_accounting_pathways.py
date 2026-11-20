# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for evals/carbon_accounting_pathways.py on toy networks."""

import pandas as pd
import pypsa
import pytest

from evals import carbon_accounting as ca
from evals import carbon_accounting_pathways as cp
from test.test_evals.test_carbon_accounting import ALPHA, add_budget, oil_toy, solve
from test.test_mods.conftest import EF, build_oil_toy

COUNTRIES = ("AT", "DE")


@pytest.fixture(scope="module")
def technology_run() -> pypsa.Network:
    return solve(oil_toy(), "technology")


@pytest.fixture(scope="module")
def carrier_run() -> pypsa.Network:
    # DE claims all green oil, so the optimised claims differ from the EU average
    return solve(oil_toy(), "carrier", rewards={"DE renewable oil claim": 1.0})


@pytest.fixture(scope="module")
def networks(technology_run, carrier_run) -> dict:
    return {"base": {"2050": technology_run}, "carrier": {"2050": carrier_run}}


@pytest.fixture(scope="module")
def frame(networks) -> pd.DataFrame:
    return cp.emissions(networks)


def national(n: pypsa.Network, evaluator: str, country: str) -> float:
    values = cp.evaluate(n, evaluator)
    return values[values.country == country].emissions.sum()


def test_emission_factors(technology_run):
    assert cp.emission_factors(technology_run) == pytest.approx(EF)


def test_emission_factors_need_imports():
    with pytest.raises(ValueError, match="emission factor"):
        cp.emission_factors(build_oil_toy())


class TestTechnologyEvaluator:
    def test_reproduces_technology_run(self, technology_run):
        table = cp.link_table(technology_run)
        values = cp.technology_emissions(table, EF)
        assert values.to_numpy() == pytest.approx(table.native.to_numpy())

    def test_inverts_carrier_run(self, technology_run, carrier_run):
        # the dispatch of the toy is fixed, so both runs have the same physical flows
        for ct in COUNTRIES:
            assert national(carrier_run, cp.TECHNOLOGY, ct) == pytest.approx(
                national(technology_run, cp.TECHNOLOGY, ct)
            )

    def test_values(self, technology_run):
        # AT: biofuel credit, DAC capture, shipping oil
        at = national(technology_run, cp.TECHNOLOGY, "AT")
        assert at == pytest.approx(-20 * EF["gas"] - 20 * EF["oil"] + 20 * EF["oil"])


class TestCarrierEvaluator:
    def test_reproduces_carrier_run(self, carrier_run):
        table = cp.link_table(carrier_run)
        values = cp.carrier_emissions(table, EF)
        assert values.to_numpy() == pytest.approx(table.native.to_numpy())

    def test_matches_booked_emissions(self, carrier_run):
        table = cp.link_table(carrier_run)
        for ct in COUNTRIES:
            booked = table.native[table.country == ct].sum()
            assert national(carrier_run, cp.CARRIER, ct) == pytest.approx(booked)

    @pytest.mark.parametrize("country", COUNTRIES)
    def test_technology_run_has_no_claims(self, technology_run, country):
        balance = cp.evaluated_categories(technology_run, country, cp.CARRIER)
        claims = list(ca.CLAIM_CATEGORIES.values())
        assert balance[claims].abs().sum() == pytest.approx(0.0)

    def test_technology_run_values(self, technology_run):
        # AT: captured CO2 used + capture credit net to 0, shipping oil unclaimed
        at = national(technology_run, cp.CARRIER, "AT")
        assert at == pytest.approx(20 * EF["oil"])

    @pytest.mark.parametrize("run", ["technology_run", "carrier_run"])
    def test_physical_categories_as_technology(self, request, run):
        n = request.getfixturevalue(run)
        physical = list(ca.PHYSICAL_CATEGORIES)
        for ct in COUNTRIES:
            carrier = cp.evaluated_categories(n, ct, cp.CARRIER)[physical]
            technology = cp.evaluated_categories(n, ct, cp.TECHNOLOGY)[physical]
            assert carrier.to_numpy() == pytest.approx(technology.to_numpy())

    def test_unknown_evaluator(self, carrier_run):
        with pytest.raises(ValueError, match="evaluator"):
            cp.evaluate(carrier_run, "mass balance")


def test_aviation_scaled():
    n = oil_toy()
    n.links.loc["AT1 shipping oil", "carrier"] = "kerosene for aviation"
    n = solve(n, "technology")
    values = cp.evaluate(n, cp.TECHNOLOGY).set_index("link").emissions
    unscaled = cp.evaluate(n, cp.TECHNOLOGY, scaled=False).set_index("link").emissions
    link = "AT1 shipping oil"
    assert values[link] == pytest.approx(ALPHA * unscaled[link])


class TestCategories:
    """The evaluators split emissions into the categories of the balance bridge."""

    @pytest.mark.parametrize("country", COUNTRIES)
    def test_technology_scenario_as_booked(self, technology_run, country):
        booked = ca.national_co2_categories(technology_run, country)
        evaluated = cp.evaluated_categories(technology_run, country, cp.TECHNOLOGY)
        assert evaluated.to_numpy() == pytest.approx(booked.to_numpy())

    @pytest.mark.parametrize("country", COUNTRIES)
    def test_carrier_scenario_as_booked(self, carrier_run, country):
        booked = ca.national_co2_categories(carrier_run, country)
        evaluated = cp.evaluated_categories(carrier_run, country, cp.CARRIER)
        assert evaluated.to_numpy() == pytest.approx(booked.to_numpy())

    @pytest.mark.parametrize("evaluator", cp.EVALUATORS)
    def test_categories_add_up(self, carrier_run, evaluator):
        balance = cp.evaluated_categories(carrier_run, "AT", evaluator)
        assert list(balance.index) == list(ca.CATEGORIES)
        assert balance.sum() == pytest.approx(national(carrier_run, evaluator, "AT"))

    def test_technology_has_no_claims(self, carrier_run):
        balance = cp.evaluated_categories(carrier_run, "DE", cp.TECHNOLOGY)
        claims = list(ca.CLAIM_CATEGORIES.values())
        assert balance[claims].abs().sum() == pytest.approx(0.0)


class TestFrames:
    def test_emissions_index(self, frame):
        assert frame.index.names == [
            "scenario",
            "horizon",
            "evaluator",
            "country",
            "category",
        ]
        evaluators = frame.xs("base", level="scenario").index.unique("evaluator")
        assert list(evaluators) == list(cp.EVALUATORS)

    def test_national_totals(self, frame):
        totals = cp.national_totals(frame, "DE")
        assert list(totals.columns) == list(cp.EVALUATORS)
        assert totals.notna().all().all()

    def test_against_budget(self, frame):
        totals = cp.national_totals(frame, "DE")
        budget = pd.Series(
            1.0,
            index=pd.MultiIndex.from_tuples(
                [("base", "2050"), ("carrier", "2050")], names=["scenario", "horizon"]
            ),
        )
        gaps = cp.against_budget(totals, budget)
        assert (gaps + 1.0).to_numpy() == pytest.approx(totals.to_numpy(), nan_ok=True)

    def test_method_gap(self, frame):
        totals = cp.national_totals(frame, "DE")
        gaps = cp.method_gap(totals)
        assert gaps.at[("base", "technology", "2050"), cp.TECHNOLOGY] == 0.0
        assert gaps.at[("carrier", "carrier", "2050"), cp.CARRIER] == 0.0
        row = totals.loc[("base", "technology", "2050")]
        assert gaps.at[("base", "technology", "2050"), cp.CARRIER] == pytest.approx(
            row[cp.CARRIER] - row[cp.TECHNOLOGY]
        )

    def test_budgets(self):
        n = solve(oil_toy(), "technology")
        add_budget(n, "AT", mu=0.0, constant=2e6)
        budgets = cp.budgets({"a": {"2050": n}}, ["AT"])
        assert budgets.at[("a", "2050"), "AT"] == pytest.approx(2.0)

    def test_category_pathway(self, frame):
        pathway = cp.category_pathway(frame, "AT", "base", cp.TECHNOLOGY)
        assert list(pathway.index) == ["2050"]
        assert ca.BIOFUEL_CREDIT in pathway.columns
        order = [c for c in ca.CATEGORIES if c in pathway.columns]
        assert list(pathway.columns) == order
        carrier = cp.category_pathway(frame, "AT", "base", cp.CARRIER)
        assert ca.BIOFUEL_CREDIT not in carrier.columns


def test_evaluated_bridge(networks):
    bridge = ca.balance_bridge(networks, "AT")
    technology = cp.evaluated_bridge(networks, "AT", cp.TECHNOLOGY)
    assert list(technology.columns) == list(bridge.columns)
    assert technology.loc[("base", "2050")].to_numpy() == pytest.approx(
        bridge.loc[("base", "2050")].to_numpy(), nan_ok=True
    )


def test_checks_pass(networks):
    checks = cp.checks(networks)
    assert [c.status for c in checks] == ["ok"] * 3


def test_merge_checks_keeps_checked_scenarios():
    details = pd.DataFrame({"deviation": [0.5]}, index=[("carrier", "2050")])
    skipped = cp.Check("c", "ok", "Nothing to check: no carrier runs.")
    checked = cp.Check("c", "fail", "Largest deviation: 5.0e-01.", details)
    merged = cp.merge_checks([skipped, checked])
    assert merged.failed
    assert merged.details.compare(details).empty


def test_merge_checks_nothing_checked():
    skipped = cp.Check("c", "ok", "Nothing to check: no carrier runs.")
    assert cp.merge_checks([skipped, skipped]) is skipped
