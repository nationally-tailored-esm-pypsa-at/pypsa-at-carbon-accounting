# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests of the national CO2 budget of the carbon accounting (mods/carbon_accounting/budget.py)."""

from types import SimpleNamespace

import pandas as pd
import pypsa
import pytest

from mods.carbon_accounting.budget import (
    carbon_accounting_enabled,
    constraint_national_co2_budgets_ca,
    national_budgets,
)
from mods.carbon_accounting.network import apply_carbon_accounting
from mods.constraints.co2_budget import constraint_national_co2_budgets
from test.test_carbon_accounting.conftest import (
    EF,
    build_carbon_network,
    carbon_accounting_costs,
    carbon_accounting_snakemake,
)

BUDGET = "GlobalConstraint-co2_limit-AT"


def _coefficient(n: pypsa.Network, constraint: str, link: str) -> float:
    """Return the summed LHS coefficient of a link's flow in a constraint."""
    labels = n.model["Link-p"].loc[:, link].labels.values
    lhs = n.model.constraints[constraint].lhs
    coeffs, variables = lhs.coeffs.values.ravel(), lhs.vars.values.ravel()
    return coeffs[pd.Series(variables).isin(labels).to_numpy()].sum()


def _budget_network(method: str) -> pypsa.Network:
    """Return the synthetic network with one AT node under the given method."""
    n = build_carbon_network(("AT1",))
    apply_carbon_accounting(
        n, carbon_accounting_snakemake(method), carbon_accounting_costs()
    )
    n.links["marginal_cost"] = 1.0  # the model needs an objective
    n.meta = {
        "sector": {
            "transport": True,
            "heating": False,
            "industry": False,
            "agriculture": False,
        }
    }
    return n


@pytest.fixture
def budget_snakemake(tmp_path) -> SimpleNamespace:
    """Return the inputs of a 50 % national budget for AT, 25 % domestic aviation."""
    co2_totals = tmp_path / "co2_totals.csv"
    pd.DataFrame(
        {"electricity": [1.0], "rail non-elec": [1.0], "road non-elec": [1.0]},
        index=pd.Index(["AT"], name="country"),
    ).to_csv(co2_totals)
    energy_totals = tmp_path / "energy_totals.csv"
    pd.DataFrame(
        {"total domestic aviation": [1.0], "total international aviation": [3.0]},
        index=pd.MultiIndex.from_tuples([("AT", 2019)], names=["country", "year"]),
    ).to_csv(energy_totals)
    return SimpleNamespace(
        params=SimpleNamespace(
            solving={"constraints": {"co2_budget_national": {"AT": {2050: 0.5}}}},
            energy_totals_year=2019,
        ),
        input=SimpleNamespace(
            co2_totals_name=str(co2_totals), energy_totals=str(energy_totals)
        ),
    )


def test_aviation_claims_scaled_in_national_budget(budget_snakemake):
    """U10: kerosene and its green claim are scaled by the domestic share."""
    n = _budget_network("carrier")
    n.optimize.create_model()
    constraint_national_co2_budgets_ca(n, budget_snakemake, 2050)

    snapshots = len(n.snapshots)
    alpha = 0.25
    claim = _coefficient(n, BUDGET, "AT renewable oil claim aviation")
    kerosene = _coefficient(n, BUDGET, "AT1 kerosene for aviation")
    shipping = _coefficient(n, BUDGET, "AT1 shipping oil")
    assert claim == pytest.approx(-EF["oil"] * alpha * snapshots)
    assert kerosene == pytest.approx(EF["oil"] * alpha * snapshots)
    assert shipping == pytest.approx(EF["oil"] * snapshots)


def _budget_terms(n: pypsa.Network) -> tuple[pd.Series, float, str]:
    """Return the LHS coefficient per variable, the RHS and the sign."""
    con = n.model.constraints[BUDGET]
    lhs = pd.Series(con.lhs.coeffs.values.ravel(), index=con.lhs.vars.values.ravel())
    lhs = lhs[lhs.index >= 0].groupby(level=0).sum()
    return lhs[lhs != 0].sort_index(), float(con.rhs.item()), str(con.sign.item())


class TestDriftAgainstPyPSAAT:
    """
    The CA budget equals the PyPSA-AT budget under the method ``technology``.

    Fails when PyPSA-AT changes ``constraint_national_co2_budgets``; port the
    change to ``constraint_national_co2_budgets_ca`` at the next upstream sync.
    """

    @pytest.fixture
    def terms(self, budget_snakemake) -> dict[str, tuple[pd.Series, float, str]]:
        terms = {}
        for name, constraint in {
            "at": constraint_national_co2_budgets,
            "ca": constraint_national_co2_budgets_ca,
        }.items():
            n = _budget_network("technology")
            n.optimize.create_model()
            constraint(n, budget_snakemake, 2050)
            terms[name] = _budget_terms(n)
        return terms

    def test_lhs(self, terms):
        at, ca = terms["at"][0], terms["ca"][0]
        assert not at.empty
        pd.testing.assert_series_equal(ca, at)

    def test_rhs_and_sign(self, terms):
        assert terms["ca"][1:] == terms["at"][1:]


@pytest.mark.parametrize("enable", [True, False])
def test_carbon_accounting_enabled(enable):
    config = {"mods": {"carbon_accounting": {"enable": enable}}}
    assert carbon_accounting_enabled(config) is enable


class TestNullBudget:
    """A ``null`` budget removes the country's constraint (run DP3)."""

    def test_national_budgets_drops_null(self):
        budgets = {"AT": None, "DE": {2050: 0.1}}
        assert national_budgets(budgets) == {"DE": {2050: 0.1}}

    @pytest.mark.parametrize("budgets", [None, {}])
    def test_national_budgets_without_budgets(self, budgets):
        assert national_budgets(budgets) == {}

    def test_no_constraint_for_null_budget(self, budget_snakemake):
        budget_snakemake.params.solving["constraints"]["co2_budget_national"] = {
            "AT": None
        }
        n = _budget_network("technology")
        n.optimize.create_model()
        constraint_national_co2_budgets_ca(n, budget_snakemake, 2050)
        assert BUDGET not in n.model.constraints
        assert "co2_limit-AT" not in n.global_constraints.index
