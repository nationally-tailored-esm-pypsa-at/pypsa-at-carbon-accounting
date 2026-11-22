# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests of the carbon accounting eval helpers in ``evals.carbon_accounting.utils``."""

import pandas as pd
import pytest

from evals.carbon_accounting.utils import (
    carbon_accounting_claims,
    scale_domestic_aviation,
)
from evals.constants import DataModel
from mods.carbon_accounting.constraints import constraint_carbon_accounting
from mods.carbon_accounting.network import apply_carbon_accounting
from test.test_carbon_accounting.conftest import (
    build_gas_toy,
    build_oil_toy,
    carbon_accounting_costs,
    carbon_accounting_snakemake,
)


def test_scale_domestic_aviation():
    """U10: kerosene and green kerosene claims scale with the domestic share."""
    index = pd.MultiIndex.from_tuples(
        [
            ("AT11", "kerosene for aviation"),
            ("AT", "renewable oil claim aviation"),
            ("AT", "renewable oil claim"),
            ("DE1", "kerosene for aviation"),
        ],
        names=[DataModel.LOCATION, DataModel.CARRIER],
    )
    balance = pd.DataFrame({"2050": [4.0, -2.0, -1.0, 8.0]}, index=index)
    shares = pd.Series({"AT": 0.25, "DE": 0.5})
    scaled = scale_domestic_aviation(balance, shares)
    assert scaled["2050"].tolist() == [1.0, -0.5, -1.0, 4.0]


class TestCarbonAccountingClaims:
    """D14: claimed credits next to the EU-average share."""

    @pytest.fixture(scope="class")
    def credits(self) -> pd.Series:
        n = build_oil_toy()
        snakemake = carbon_accounting_snakemake()
        apply_carbon_accounting(n, snakemake, carbon_accounting_costs())
        # all green oil is claimed in DE
        n.links.loc["DE renewable oil claim", "marginal_cost"] = -1.0
        n.optimize(
            solver_name="highs",
            extra_functionality=lambda n, _: constraint_carbon_accounting(
                n, snakemake, 2050
            ),
        )
        return carbon_accounting_claims(n)

    def test_claimed(self, credits):
        claimed = credits.xs("claimed", level=DataModel.BUS_CARRIER)
        assert claimed[("DE", "renewable oil claim")] == pytest.approx(20 * 0.2571)
        assert claimed[("AT", "renewable oil claim")] == pytest.approx(0.0, abs=1e-6)

    def test_reference_is_eu_average_share(self, credits):
        reference = credits.xs("reference", level=DataModel.BUS_CARRIER)
        # 20 MWh green oil, 40 MWh consumed: both countries get half of their use
        for ct in ("AT", "DE"):
            assert reference[(ct, "renewable oil claim")] == pytest.approx(10 * 0.2571)
        assert reference[("DE", "renewable gas claim")] == pytest.approx(20 * 0.198)

    def test_unit(self, credits):
        assert credits.attrs["unit"] == "t_co2"
        assert credits.ge(-1e-9).all()


def test_carbon_accounting_claims_fair_share_cap():
    """D18: the cap of a budget country is tolerance x key x EU green production."""
    n = build_oil_toy()
    n.loads.loc["AT1 shipping", "p_set"] = 5.0
    n.loads.loc["DE1 shipping", "p_set"] = 15.0
    snakemake = carbon_accounting_snakemake(budgets=("AT",), fair_share=1.0)
    apply_carbon_accounting(n, snakemake, carbon_accounting_costs())
    n.meta = snakemake.config
    n.optimize(
        solver_name="highs",
        extra_functionality=lambda n, _: constraint_carbon_accounting(
            n, snakemake, 2050
        ),
    )
    cap = carbon_accounting_claims(n).xs("cap", level=DataModel.BUS_CARRIER)
    # 20 MWh green oil, AT key 0.25; DE has no budget and no cap
    assert cap[("AT", "renewable oil claim")] == pytest.approx(5 * 0.2571)
    assert "DE" not in cap.index.get_level_values(DataModel.LOCATION)


def test_carbon_accounting_claims_empty_without_claims():
    n = build_gas_toy()
    n.optimize(solver_name="highs")
    assert carbon_accounting_claims(n).empty
