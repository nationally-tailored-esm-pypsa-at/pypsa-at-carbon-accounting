# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
National CO2 budget of the carbon accounting.

Replaces :func:`mods.constraints.co2_budget.constraint_national_co2_budgets`
of PyPSA-AT when ``mods.carbon_accounting.enable`` is set. With the method
``technology``, both constraints are equal; a drift test guards this.
"""

import logging

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.carbon_accounting.constants import AVIATION_CARRIERS

logger = logging.getLogger(__name__)


def _atmosphere_efficiency(links: pd.DataFrame) -> pd.Series:
    """
    Return the efficiency of each link at its ``co2 atmosphere`` port.

    Parameters
    ----------
    links
        Links with exactly one output port at ``co2 atmosphere``.

    Returns
    -------
    :
        Efficiency per link.

    Raises
    ------
    ValueError
        If a link has no or several output ports at ``co2 atmosphere``.
    """
    ports = links.columns[links.columns.str.fullmatch(r"bus[1-9]\d*")].str[3:]
    at_atm = pd.DataFrame({p: links[f"bus{p}"] == "co2 atmosphere" for p in ports})
    if not at_atm.sum(axis=1).eq(1).all():
        raise ValueError(f"Expected one 'co2 atmosphere' port at {list(links.index)}.")
    efficiency = pd.DataFrame(
        {p: links["efficiency" if p == "1" else f"efficiency{p}"] for p in ports}
    )
    return efficiency.where(at_atm).sum(axis=1)


def carbon_accounting_enabled(config: dict) -> bool:
    """
    Return whether the carbon accounting replaces the PyPSA-AT national budget.

    Parameters
    ----------
    config
        The workflow configuration.

    Returns
    -------
    :
        The value of ``mods.carbon_accounting.enable``.
    """
    return bool(config["mods"]["carbon_accounting"]["enable"])


def national_budgets(budgets: dict | None) -> dict:
    """
    Return the national CO2 budgets without the countries set to ``null``.

    A scenario cannot delete a country from ``co2_budget_national`` (the
    scenario overrides are deep-merged), so ``null`` removes its budget.

    Parameters
    ----------
    budgets
        The configuration ``solving.constraints.co2_budget_national``.

    Returns
    -------
    :
        Budget per planning horizon, per country with a budget.
    """
    return {ct: budget for ct, budget in (budgets or {}).items() if budget is not None}


def constraint_national_co2_budgets_ca(
    n: pypsa.Network, snakemake: Snakemake, investment_year: int
) -> None:
    """
    Add the national CO2 budgets of the carbon accounting.

    Same as the PyPSA-AT national budget, which this function replaces,
    apart from the claims of the carrier-based method and countries whose
    budget is ``null`` (no constraint, see :func:`national_budgets`):
      - adds CO2 national constraints based on a balance at
        the `co2 atmosphere` bus, so the claim links count with their
        negative efficiency at that bus
      - scales emissions from kerosene for aviation and the claims of
        green kerosene alike with the domestic / total aviation ratio
      - reads the efficiency of aviation links at their `co2 atmosphere`
        port instead of assuming `bus2`
      - emissions (positive and negative) are balanced at the
        respective model region

    Parameters
    ----------
    n
        The pypsa network to add the constraints to.
    snakemake
        The snakemake workflow object.
    investment_year
        The myopic planning horizon.

    Notes
    -----
    Keep in line with
    :func:`mods.constraints.co2_budget.constraint_national_co2_budgets`; the
    drift test in ``test/test_carbon_accounting/test_mods/test_budget.py``
    fails when PyPSA-AT changes its budget.
    """
    national_co2_budgets = national_budgets(
        snakemake.params.solving["constraints"]["co2_budget_national"]
    )
    logger.info(f"Adding national CO2 budgets to {n.name} for year {investment_year}")
    nhours = n.snapshot_weightings.generators.sum()
    nyears = nhours / 8760
    MtCO2_to_tCO2 = 1e6

    co2_totals = pd.read_csv(snakemake.input.co2_totals_name, index_col=0).mul(
        MtCO2_to_tCO2
    )
    from scripts.prepare_sector_network import determine_emission_sectors

    sectors = determine_emission_sectors(n.meta["sector"])
    co2_total_totals = co2_totals[sectors].sum(axis=1) * nyears

    for ct, budget in national_co2_budgets.items():
        limit = co2_total_totals[ct] * budget[investment_year]
        logger.info(
            f"Limiting emissions in country {ct} to {budget[investment_year]:.1%} of "
            f"1990 levels, i.e. {limit:,.2f} tCO2/a",
        )

        lhs = []
        weightings = n.snapshot_weightings.generators
        links = n.components.links.static
        link_ports = links.filter(like="bus").columns.str[3:]
        for port in link_ports:
            # exclude aviation here to multiply it with a domestic factor later
            idx = links.index[
                links.index.str.startswith(ct)
                & (links[f"bus{port}"] == "co2 atmosphere")
                & ~links.carrier.isin(AVIATION_CARRIERS)
            ]

            logger.info(
                f"For {ct} adding following link carriers to port {port} "
                f"CO2 constraint: {sorted(links.loc[idx, 'carrier'].unique())}"
            )

            if port == "0":
                efficiency = -1.0
            elif port == "1":
                efficiency = links.loc[idx, "efficiency"]
            else:
                efficiency = links.loc[idx, f"efficiency{port}"]

            port_emissions = (
                n.model["Link-p"].loc[:, idx].mul(efficiency).mul(weightings).sum()
            )
            lhs.append(port_emissions)

        # Aviation demand
        country_year = (ct, snakemake.params.energy_totals_year)
        energy_totals = pd.read_csv(snakemake.input.energy_totals, index_col=[0, 1])
        aviation_domestic = energy_totals.loc[country_year, "total domestic aviation"]
        aviation_international = energy_totals.loc[
            country_year, "total international aviation"
        ]
        aviation_total = aviation_domestic + aviation_international
        if aviation_total == 0:  # avoids division by zero errors
            domestic_aviation_factor = 0.0
        else:
            domestic_aviation_factor = aviation_domestic / aviation_total
        # kerosene and the claims of green kerosene (carbon accounting method
        # 'carrier') are scaled alike
        aviation_links = links[
            links.index.str.startswith(ct) & links.carrier.isin(AVIATION_CARRIERS)
        ]
        aviation_emissions = (
            n.model["Link-p"]
            .loc[:, aviation_links.index]
            .mul(_atmosphere_efficiency(aviation_links))
            .mul(weightings)
            .sum()
            .mul(domestic_aviation_factor)
        )
        lhs.append(aviation_emissions)
        logger.info(
            f"Adding domestic aviation emissions for {ct} with "
            f"a factor of {domestic_aviation_factor:.2f}"
        )

        # Navigation demand
        # todo: do we need to deduct emissions from internation navigation?

        # add total regional emissions to the model and make sure to drop existing
        # constraints from previous year
        lhs = sum(lhs)

        cname = f"co2_limit-{ct}"

        n.model.add_constraints(
            lhs <= limit,
            name=f"GlobalConstraint-{cname}",
        )

        if cname in n.global_constraints.index:
            logger.warning(
                f"Global constraint {cname} already exists. Dropping and adding it again."
            )
            n.global_constraints.drop(cname, inplace=True)

        n.add(
            "GlobalConstraint",
            cname,
            constant=limit,
            sense="<=",
            type="",
            carrier_attribute="",
        )
