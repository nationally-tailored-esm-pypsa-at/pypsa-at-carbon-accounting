# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Helper functions of the carbon accounting evaluations."""

import pandas as pd
import pypsa

from evals.carbon_accounting.constants import AVIATION_CARRIERS, FUEL_CLAIM_CARRIERS
from evals.constants import DataModel


def scale_domestic_aviation(
    co2_balance: pd.DataFrame, domestic_shares: pd.Series
) -> pd.DataFrame:
    """
    Scale aviation CO2 with the domestic aviation share per country.

    Scales kerosene emissions and, under the carrier-based carbon accounting,
    the green kerosene claims alike, as the national CO2 budget does.

    Parameters
    ----------
    co2_balance
        CO2 balance with ``location`` and ``carrier`` index levels.
    domestic_shares
        Domestic share of aviation per country code.

    Returns
    -------
    :
        A copy of the balance with scaled aviation rows.
    """
    scaled = co2_balance.copy()
    locations = scaled.index.get_level_values(DataModel.LOCATION)
    is_aviation = scaled.index.get_level_values(DataModel.CARRIER).isin(
        AVIATION_CARRIERS
    )
    for ct, share in domestic_shares.items():
        scaled.loc[locations.str.startswith(ct) & is_aviation] *= share
    return scaled


def _link_ports(n: pypsa.Network) -> list[str]:
    ports = n.links.columns[n.links.columns.str.fullmatch(r"bus\d+")].str[3:]
    return sorted(ports, key=int)


def claimable_consumption(n: pypsa.Network, p0: pd.Series) -> pd.DataFrame:
    """
    Return the annual consumption that bounds each claim, per country.

    Mirrors ``mods.carbon_accounting.constraints.claimable_consumers``.

    Parameters
    ----------
    n
        A solved network.
    p0
        Weighted annual flow at ``bus0`` per link.

    Returns
    -------
    :
        Consumption in MWh, indexed by country, one column per claim carrier.
    """
    links = n.links
    fuel = links.bus0.map(n.buses.carrier)
    transport = links.carrier.isin(["gas pipeline", "gas pipeline new"])
    aviation = links.carrier == "kerosene for aviation"
    consumption = {}
    for claim, claimed_fuel in FUEL_CLAIM_CARRIERS.items():
        is_claim = (fuel == claimed_fuel) & ~transport
        if claimed_fuel == "oil":
            is_claim &= aviation if claim.endswith("aviation") else ~aviation
        consumers = links.index[is_claim]
        consumption[claim] = p0[consumers].groupby(consumers.str[:2]).sum()
    return pd.DataFrame(consumption).fillna(0.0)


def pool_inflow(n: pypsa.Network, p0: pd.Series, fuel: str) -> float:
    """
    Return the annual attributes that flow into the EU pool of a fuel.

    Mirrors ``mods.carbon_accounting.constraints.green_production``.

    Parameters
    ----------
    n
        A solved network.
    p0
        Weighted annual flow at ``bus0`` per link.
    fuel
        Pooled fuel, ``oil`` or ``methanol``.

    Returns
    -------
    :
        Attributes in MWh, 0 without a pool.
    """
    pool = f"EU renewable {fuel} attribute"
    inflow = 0.0
    for port in _link_ports(n)[1:]:
        column = "efficiency" if port == "1" else f"efficiency{port}"
        at_pool = n.links[f"bus{port}"] == pool
        inflow += (n.links[column].where(at_pool, 0.0) * p0).sum()
    return inflow


def fair_share_caps(n: pypsa.Network, p0: pd.Series) -> pd.Series:
    """
    Return the fair share cap of the claims of countries with a national budget.

    Mirrors ``mods.carbon_accounting.constraints._add_fair_share_bounds``:
    tolerance times key times the annual attributes flowing into the EU pool.
    Empty unless the network was composed with the fair share (D18).

    Parameters
    ----------
    n
        A solved network.
    p0
        Weighted annual flow at ``bus0`` per link.

    Returns
    -------
    :
        Cap in MWh of attributes per claim link.
    """
    if "fair_share_key" not in n.links:
        return pd.Series(dtype=float)
    tolerance = n.meta["mods"]["carbon_accounting"]["fair_share"]["tolerance"]
    budgets = n.meta["solving"]["constraints"]["co2_budget_national"] or {}
    keys = n.links["fair_share_key"].dropna()
    keys = keys[keys.index.str[:2].isin(list(budgets))]
    fuels = n.links.loc[keys.index, "carrier"].map(FUEL_CLAIM_CARRIERS)
    production = {fuel: pool_inflow(n, p0, fuel) for fuel in set(fuels)}
    return tolerance * keys * fuels.map(production)


def carbon_accounting_claims(n: pypsa.Network) -> pd.Series:
    """
    Compare the claimed CO2 credits of each country with a reference.

    Under the carrier-based carbon accounting, countries claim green fuel
    credits up to their own consumption (D14). The reference for a fuel is
    the credit at the EU-average green share of that fuel. With the optional
    fair share (D18), the cap of each country with a national budget is
    added as a third group.

    Parameters
    ----------
    n
        A solved network.

    Returns
    -------
    :
        Credits in t CO2, positive, indexed by ``location`` (country),
        ``carrier`` (the claim) and ``bus_carrier`` (``claimed``,
        ``reference`` or ``cap``). Empty without claim links.
    """
    weightings = n.snapshot_weightings.generators
    p0 = n.links_t.p0.mul(weightings, axis=0).sum().reindex(n.links.index, fill_value=0)
    claims = n.links[n.links.carrier.isin(FUEL_CLAIM_CARRIERS)]
    names = pd.MultiIndex.from_arrays([[], [], []], names=DataModel.IDX_NAMES)
    if claims.empty:
        return pd.Series(dtype=float, index=names)

    keys = pd.MultiIndex.from_arrays(
        [claims.index.str[:2], claims.carrier], names=DataModel.IDX_NAMES[:2]
    )
    factor = pd.Series(-claims.efficiency.to_numpy(), index=keys)
    claimed = pd.Series(p0[claims.index].to_numpy(), index=keys)

    consumption = claimable_consumption(n, p0).stack()
    consumption.index.names = DataModel.IDX_NAMES[:2]
    fuel = consumption.index.get_level_values(DataModel.CARRIER).map(
        FUEL_CLAIM_CARRIERS
    )
    claimed_fuel = claimed.reindex(consumption.index, fill_value=0.0)
    share = claimed_fuel.groupby(fuel.to_numpy()).sum() / consumption.groupby(
        fuel.to_numpy()
    ).sum().replace(0.0, float("nan"))
    reference = consumption * fuel.map(share).fillna(0.0).to_numpy()

    reference = reference * factor.reindex(reference.index)
    groups = {"claimed": claimed * factor, "reference": reference.dropna()}
    caps = fair_share_caps(n, p0)
    if not caps.empty:
        caps.index = pd.MultiIndex.from_arrays(
            [caps.index.str[:2], n.links.loc[caps.index, "carrier"]],
            names=DataModel.IDX_NAMES[:2],
        )
        groups["cap"] = caps * factor.reindex(caps.index)
    credits = pd.concat(groups, names=[DataModel.BUS_CARRIER])
    credits = credits.reorder_levels(DataModel.IDX_NAMES).sort_index()
    credits.attrs["unit"] = "t_co2"
    return credits
