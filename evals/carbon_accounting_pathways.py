# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Evaluate the emissions of any scenario under every carbon accounting method.

Backs the notebook ``evals/notebooks/carbon_accounting_pathways.py``. A
scenario is optimised under one method, but its flows can be evaluated ex
post under either method (the *evaluator*). Both evaluators read the same
network elements of a run; they differ only in the coefficients of the green
producers, the green imports and the claim links. An element a run does not
have (the claim links of a technology run) counts as 0.

``CA_technology``
    The technology that releases CO2 books it; biofuel producers book
    ``-EF`` at creation, green imports draw their carbon from the atmosphere,
    claims count 0. For carrier scenarios, the transformation of the spec
    (section 3.2) is inverted: ``atm_technology = atm_carrier - EF_out * out
    - used``.
``CA_carrier``
    Green producers book no creation credit, synthetic fuel producers book
    the CO2 they use, green imports book 0, and the claim links book the
    claims of the run. Reproduces a carrier scenario as booked; a
    technology scenario has no claims, so its green fuels count as fossil
    at the consumer.

Emissions are split into the categories of the national balance bridge
(:data:`evals.carbon_accounting.CATEGORIES`) by
:func:`evals.carbon_accounting.link_categories`, so both notebooks use the
same categories. National totals follow the national CO2 budget (name prefix,
kerosene and kerosene claims scaled by the domestic aviation share).
"""

from collections.abc import Mapping

import pandas as pd
import pypsa

from evals.carbon_accounting import (
    CATEGORIES,
    FUELS,
    GAS_TRANSPORT,
    GREEN_BIO_PRODUCERS,
    GREEN_IMPORTS,
    GREEN_SYNTHETIC_PRODUCERS,
    MT,
    REL_TOL,
    Check,
    _country_frame,
    _method,
    bridge_row,
    emission_factors,
    link_categories,
    national_budget,
    national_categories,
    port_flows,
)
from evals.constants import FUEL_CLAIM_CARRIERS

Networks = Mapping[str, Mapping[str, pypsa.Network]]

TECHNOLOGY = "CA_technology"
CARRIER = "CA_carrier"
EVALUATORS: tuple[str, ...] = (TECHNOLOGY, CARRIER)
GREEN_PRODUCERS: tuple[str, ...] = (
    *GREEN_BIO_PRODUCERS,
    *GREEN_SYNTHETIC_PRODUCERS,
    *GREEN_IMPORTS,
)


def link_table(n: pypsa.Network, flows: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Return the annual quantities that define the emissions of every link.

    Parameters
    ----------
    n
        A solved network.
    flows
        Port flows of ``n``, see :func:`evals.carbon_accounting.port_flows`.

    Returns
    -------
    :
        One row per link with ``carrier``, ``country`` (name prefix),
        ``native`` (t CO2 booked at ``co2 atmosphere`` in the
        run), ``fuel_out`` and ``out`` (green fuel output of producers, MWh),
        ``used`` (CO2 taken from ``co2 stored`` by synthetic fuel producers,
        t), ``p0`` (MWh or t), ``fuel_in`` (the fuel consumed at ``bus0``, empty
        for transport) and ``claim`` (the claim kind of consumers and claim
        links, e.g. ``renewable oil claim aviation``).
    """
    flows = port_flows(n) if flows is None else flows
    flows = flows[flows.component == "Link"]
    links = n.links
    table = pd.DataFrame(
        {
            "carrier": links.carrier,
            "country": links.index.str[:2],
        },
        index=links.index,
    )
    by_link = flows.groupby(["name", "bus_carrier"]).energy.sum().unstack(fill_value=0)
    by_link = by_link.reindex(links.index, fill_value=0.0)
    table["native"] = -by_link.get("co2", 0.0)
    table["p0"] = (
        flows[flows.port == "0"].groupby("name").energy.sum().reindex(links.index)
    ).fillna(0.0)

    is_producer = links.carrier.isin(GREEN_PRODUCERS)
    output = -by_link.reindex(columns=list(FUELS), fill_value=0.0).clip(upper=0.0)
    table["fuel_out"] = output.idxmax(axis=1).where(
        is_producer & output.gt(0).any(axis=1), ""
    )
    table["out"] = output.max(axis=1).where(table.fuel_out != "", 0.0)
    is_synthetic = links.carrier.isin(GREEN_SYNTHETIC_PRODUCERS)
    table["used"] = (
        by_link.get("co2 stored", 0.0).clip(lower=0.0).where(is_synthetic, 0.0)
    )

    fuel_in = links.bus0.map(n.buses.carrier)
    is_consumer = fuel_in.isin(FUELS) & ~links.carrier.isin(GAS_TRANSPORT)
    table["fuel_in"] = fuel_in.where(is_consumer, "")
    claim = ("renewable " + fuel_in + " claim").where(is_consumer, "")
    claim = claim.where(
        links.carrier != "kerosene for aviation", "renewable oil claim aviation"
    )
    is_claim = links.carrier.isin(FUEL_CLAIM_CARRIERS)
    table["claim"] = claim.where(~is_claim, links.carrier)
    table["is_claim"] = is_claim
    # links transformed by the carrier method (marker of mods.network.carbon_accounting)
    marker = links.get("carbon_accounting", pd.Series("", index=links.index))
    table["transformed"] = marker.fillna("").eq("carrier")
    return table


def technology_emissions(table: pd.DataFrame, ef: dict[str, float]) -> pd.Series:
    """
    Return the emissions of every link under the method ``technology``, in t.

    Inverts the carrier transformation where it was applied; links of a
    technology run come out unchanged.

    Parameters
    ----------
    table
        Output of :func:`link_table`.
    ef
        Emission factor per fuel.

    Returns
    -------
    :
        Emissions per link, claims are 0.
    """
    carrier = table.carrier
    creation = table.fuel_out.map(ef).fillna(0.0) * table.out
    bio = carrier.isin(GREEN_BIO_PRODUCERS) & table.transformed
    synthetic = carrier.isin(GREEN_SYNTHETIC_PRODUCERS) & table.transformed
    emissions = table.native.copy()
    emissions[bio] -= creation[bio]
    emissions[synthetic] -= table.used[synthetic]
    # green imports draw their carbon from the atmosphere
    imports = carrier.isin(GREEN_IMPORTS)
    emissions[imports] = -table.p0[imports]
    emissions[table.is_claim] = 0.0
    return emissions


def carrier_emissions(table: pd.DataFrame, ef: dict[str, float]) -> pd.Series:
    """
    Return the emissions of every link under the carrier rules.

    Bio-fuel producers lose their creation credit, synthetic fuel producers
    book the CO2 they use and green imports book zero (spec section 3.2).
    Claim links book the claims of the run; a run without claim links has
    none.

    Parameters
    ----------
    table
        Output of :func:`link_table`.
    ef
        Emission factor per fuel.

    Returns
    -------
    :
        Emissions per link in t.
    """
    emissions = technology_emissions(table, ef)
    carrier = table.carrier
    is_bio = carrier.isin(GREEN_BIO_PRODUCERS)
    creation = table.fuel_out.map(ef).fillna(0.0) * table.out
    emissions[is_bio] += creation[is_bio]
    is_synthetic = carrier.isin(GREEN_SYNTHETIC_PRODUCERS)
    emissions[is_synthetic] += table.used[is_synthetic]
    emissions[carrier.isin(GREEN_IMPORTS)] = 0.0
    emissions[table.is_claim] = table.native[table.is_claim]
    return emissions


def evaluate(
    n: pypsa.Network,
    evaluator: str,
    flows: pd.DataFrame | None = None,
    table: pd.DataFrame | None = None,
    scaled: bool = True,
) -> pd.DataFrame:
    """
    Return the emissions of every link of a scenario under an evaluator, by category.

    Parameters
    ----------
    n
        A solved network.
    evaluator
        One of :data:`EVALUATORS`.
    flows
        Port flows of ``n``, see :func:`evals.carbon_accounting.port_flows`;
        computed if missing.
    table
        Output of :func:`link_table`; computed if missing.
    scaled
        Whether to scale aviation by the domestic share; ``False`` for EU
        totals.

    Returns
    -------
    :
        Rows as :func:`evals.carbon_accounting.link_categories`, in t CO2.
    """
    flows = port_flows(n) if flows is None else flows
    table = link_table(n, flows) if table is None else table
    ef = emission_factors(n)
    if evaluator == TECHNOLOGY:
        emitted = technology_emissions(table, ef)
    elif evaluator == CARRIER:
        emitted = carrier_emissions(table, ef)
    else:
        raise ValueError(f"Unknown evaluator '{evaluator}'.")
    return link_categories(n, emitted, flows, scaled=scaled)


def evaluated_categories(
    n: pypsa.Network, country: str, evaluator: str, flows: pd.DataFrame | None = None
) -> pd.Series:
    """
    Return the national CO2 balance of a country per category, under an evaluator.

    ``CA_technology`` keeps the flows of the scenario and books them with the
    coefficients of the method ``technology``: biofuel producers get their
    credit back, synthetic fuel producers book nothing, green imports draw
    from the atmosphere and claims vanish. A technology scenario comes out as
    :func:`evals.carbon_accounting.national_co2_categories`.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.
    evaluator
        One of :data:`EVALUATORS`.
    flows
        Port flows of ``n``; computed if missing.

    Returns
    -------
    :
        t CO2 per category of :data:`evals.carbon_accounting.CATEGORIES`.
    """
    return national_categories(evaluate(n, evaluator, flows), country)


def evaluated_bridge(networks: Networks, country: str, evaluator: str) -> pd.DataFrame:
    """
    Return the national CO2 balance per category of every scenario, under an evaluator.

    Same layout as :func:`evals.carbon_accounting.balance_bridge`; with
    ``CA_technology``, technology scenarios give the same rows and carrier
    scenarios show their flows booked as ``CA_technology``.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.
    evaluator
        One of :data:`EVALUATORS`.

    Returns
    -------
    :
        Mt CO2 with one column per category, plus ``Total`` and ``Budget``,
        indexed by ``scenario`` and ``horizon``.
    """

    def bridge(n: pypsa.Network) -> pd.Series:
        return bridge_row(evaluated_categories(n, country, evaluator), n, country)

    return _country_frame(networks, bridge)


def emissions(networks: Networks) -> pd.DataFrame:
    """
    Return the emissions of every scenario under every evaluator, by country and category.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.

    Returns
    -------
    :
        Columns ``method`` (of the scenario) and ``emissions`` (Mt CO2),
        indexed by ``scenario``, ``horizon``, ``evaluator``, ``country`` and
        ``category``. The country ``EU`` holds the links without a country
        prefix.
    """
    frames = []
    for scenario, horizons in networks.items():
        for horizon, n in horizons.items():
            flows = port_flows(n)
            table = link_table(n, flows)
            for evaluator in EVALUATORS:
                values = evaluate(n, evaluator, flows, table)
                grouped = values.groupby(["country", "category"]).emissions.sum() / MT
                frame = grouped.rename("emissions").reset_index()
                frames.append(
                    frame.assign(
                        scenario=scenario,
                        horizon=horizon,
                        evaluator=evaluator,
                        method=_method(n.meta)[0],
                    )
                )
    frame = pd.concat(frames, ignore_index=True)
    index = ["scenario", "horizon", "evaluator", "country", "category"]
    return frame.set_index(index)[["method", "emissions"]]


def budgets(networks: Networks, countries: list[str]) -> pd.DataFrame:
    """Return the national CO2 budgets in Mt, indexed by ``scenario`` and ``horizon``, one column per country."""
    return _country_frame(
        networks, lambda n: {ct: national_budget(n, ct) / MT for ct in countries}
    )


def national_totals(frame: pd.DataFrame, country: str) -> pd.DataFrame:
    """
    Return the national totals of a country, one column per evaluator.

    Parameters
    ----------
    frame
        Output of :func:`emissions`.
    country
        Country code.

    Returns
    -------
    :
        Mt CO2, indexed by ``scenario``, ``method`` and ``horizon``.
    """
    rows = frame.xs(country, level="country")
    totals = rows.groupby(
        ["scenario", "method", "horizon", "evaluator"]
    ).emissions.sum()
    return totals.unstack("evaluator").reindex(columns=list(EVALUATORS))


def checks(networks: Networks) -> list[Check]:
    """
    Check the evaluators against the scenarios.

    - ``CA_technology`` reproduces every link of a technology scenario.
    - ``CA_carrier`` reproduces every link of a carrier scenario.
    - Both evaluators give the same EU total for a carrier scenario (P5);
      computed without the aviation scaling, which is national. A
      technology scenario has no claims, so its green fuels have no credit
      under ``CA_carrier`` and the check does not apply.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.

    Returns
    -------
    :
        One check per test.
    """
    technology_error, carrier_error, eu = {}, {}, {}
    for scenario, horizons in networks.items():
        for horizon, n in horizons.items():
            key = (scenario, horizon)
            flows = port_flows(n)
            table = link_table(n, flows)
            ef = emission_factors(n)
            if _method(n.meta)[0] == "technology":
                technology = technology_emissions(table, ef)
                technology_error[key] = (technology - table.native).abs().max()
                continue
            carrier = carrier_emissions(table, ef)
            carrier_error[key] = (carrier - table.native).abs().max()
            totals = [
                evaluate(n, evaluator, flows, table, scaled=False).emissions.sum()
                for evaluator in EVALUATORS
            ]
            eu[key] = (max(totals) - min(totals)) / max(abs(totals[0]), 1.0)

    def check(name: str, values: dict, tolerance: float, what: str) -> Check:
        if not values:
            return Check(name, "ok", f"Nothing to check: no {what}.")
        series = pd.Series(values)
        status = "ok" if (series <= tolerance).all() else "fail"
        return Check(
            name,
            status,
            f"Largest deviation: {series.max():.1e}.",
            series.to_frame("deviation"),
        )

    return [
        check(
            f"{TECHNOLOGY} = technology scenarios (t per link)",
            technology_error,
            1e-3,
            "technology scenarios",
        ),
        check(
            f"{CARRIER} = carrier scenarios (t per link)",
            carrier_error,
            1e-3,
            "carrier scenarios",
        ),
        check(
            "Same EU total under both evaluators in carrier scenarios (P5)",
            eu,
            REL_TOL,
            "carrier scenarios",
        ),
    ]


def merge_checks(results: list[Check]) -> Check:
    """
    Merge the results of one check over several scenarios.

    Scenarios with nothing to check (no details) are left out, so a carrier
    run is not hidden behind a technology run that skipped the check.

    Parameters
    ----------
    results
        One result of the same check per scenario, see :func:`checks`.

    Returns
    -------
    :
        Failed if any scenario failed, with the details of all scenarios.
    """
    checked = [c for c in results if not c.details.empty]
    if not checked:
        return results[0]
    details = pd.concat([c.details for c in checked])
    return Check(
        results[0].name,
        "fail" if any(c.failed for c in checked) else "ok",
        f"Largest deviation: {details.deviation.max():.1e}.",
        details,
    )


def against_budget(totals: pd.DataFrame, budget: pd.Series) -> pd.DataFrame:
    """
    Return the national totals minus the national budget of the scenario and horizon.

    Parameters
    ----------
    totals
        Output of :func:`national_totals`.
    budget
        Budget in Mt per ``scenario`` and ``horizon``, a column of :func:`budgets`.

    Returns
    -------
    :
        Mt CO2 above (positive) or below (negative) the budget, like ``totals``.
    """
    keys = totals.index.droplevel("method")
    return totals.sub(budget.reindex(keys).to_numpy(), axis=0)


def category_pathway(
    frame: pd.DataFrame,
    country: str,
    scenario: str,
    evaluator: str,
    cutoff: float = 0.0,
) -> pd.DataFrame:
    """
    Return the emissions of a country by category over the horizons.

    Parameters
    ----------
    frame
        Output of :func:`emissions`.
    country
        Country code.
    scenario
        The scenario.
    evaluator
        One of :data:`EVALUATORS`.
    cutoff
        Categories whose absolute emissions are at most this in every horizon
        are left out.

    Returns
    -------
    :
        Mt CO2, indexed by ``horizon``, one column per category in the order
        of :data:`evals.carbon_accounting.CATEGORIES`.
    """
    index = frame.index
    rows = frame[
        (index.get_level_values("scenario") == scenario)
        & (index.get_level_values("evaluator") == evaluator)
        & (index.get_level_values("country") == country)
    ]
    pathway = rows.emissions.groupby(["horizon", "category"]).sum().unstack("category")
    pathway = pathway.reindex(columns=[c for c in CATEGORIES if c in pathway.columns])
    return pathway.loc[:, pathway.abs().gt(cutoff).any()].fillna(0.0)
