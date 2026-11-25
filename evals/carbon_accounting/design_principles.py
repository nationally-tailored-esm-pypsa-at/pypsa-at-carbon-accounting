# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Compare the design-principle runs with ``DP_base`` for one country.

Backs the notebook ``evals/carbon_accounting/notebooks/design_principles.py``.
Functions that read networks take a mapping scenario -> horizon -> network and
return frames with a ``scenario`` and a ``horizon`` level. See
``docs-ca/explanations/design-principle-eval-spec.md``.

The values of the AT policy constraints (:func:`policy_values`) re-evaluate the
constraint expressions of ``mods/constraints/production.py``,
``mods/constraints/eag.py`` and ``scripts/pypsa-de/additional_functionality.py``
on the solved network; the evals do not import ``mods``. A test compares them
with the solver's values.
"""

import re
from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd
import pypsa

from evals.carbon_accounting.accounting import (
    BN,
    EU_CO2_LIMIT,
    MT,
    NON_TRADE_BUS_CARRIERS,
    Check,
    country_cost,
    national_co2_categories,
    port_flows,
    read_meta,
    system_cost,
)

Networks = Mapping[str, Mapping[str, pypsa.Network]]

REFERENCE = "DP_base"
TWH = 1e6  # MWh per TWh
GW = 1e3  # MW per GW
TOLERANCE = 0.999  # share of a bound at which it counts as reached
MU_TOLERANCE = 1e-3  # |mu| above which a global constraint binds

# keys in which each design-principle run differs from its reference run, see
# docs-ca/explanations/design-principle-effects-spec.md
DP_DIFFERENCES: dict[str, set[str]] = {
    "DP1_no_national_data": {
        "mods.klien_potential_limits.technologies",
        "mods.carbon_accounting.onwind_brownfield.enable",
    },
    "DP2_at10": {"mods.modify_nuts3_shapes", "clustering.administrative.AT"},
    # basis of the P3 pair: KLIEN technical potentials instead of scenario potentials
    "DP3_with_national_policy": {
        "mods.klien_potential_limits.use_technical_potentials"
    },
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
        # cross-border flow and infrastructure constraints
        "mods.tyndp_cross_border_flow_limits.enable",
        "mods.tyndp_lower_bounds.enable",
        "mods.threshold_year_for_gas_grid_expansion",
        "sector.imports.carriers_tyndp",
        *(
            f"solving.constraints.limits_volume_max.electricity_import.DE.{year}"
            for year in range(2020, 2055, 5)
        ),
    },
}
# runs that are compared with another run than ``REFERENCE`` (one choice apart)
DP_REFERENCES: dict[str, str] = {
    "DP3_no_national_policy": "DP3_with_national_policy",
}
# config keys that differ between every pair of runs; ``resources`` is input data
# provenance written by the workflow, not configuration
IGNORED_KEYS: tuple[str, ...] = ("run", "wildcards", "description", "resources")
# AT AC buses per NUTS level of clustering.administrative
BUSES_PER_LEVEL: dict[int, int] = {2: 10, 3: 35}

# carrier groups of the potentials (question A); ground PV shares one land potential
POTENTIAL_GROUPS: dict[str, tuple[str, ...]] = {
    "onwind": ("onwind",),
    "ground PV": ("solar", "solar-hsat"),
    "rooftop PV": ("solar rooftop",),
    "ror": ("ror",),
}
# the carrier whose p_nom_max is the potential of a group
SHARED_POTENTIAL: dict[str, str] = {"ground PV": "solar"}
BIOMASS_CARRIERS: tuple[str, ...] = ("biogas", "solid biomass")

# technologies of the regional comparison (question B): component, carriers, capacity
GENERATOR_TECHNOLOGIES: dict[str, tuple[str, ...]] = {
    **POTENTIAL_GROUPS,
    "hydro inflow": ("hydro inflow", "PHS inflow"),
}
LINK_TECHNOLOGIES: dict[str, str] = {
    "electrolysis": r"^H2 Electrolysis$",
    "gas power": r"^(?:OCGT|CCGT)$",
    "gas CHP": r"gas CHP",
    "heat pump": r"heat pump",
    "biomass CHP": r"solid biomass CHP",
    "H2 power": r"^(?:H2 OCGT|H2 CCGT|urban central H2 CHP)$",
}
STORE_TECHNOLOGIES: dict[str, tuple[str, ...]] = {
    "battery": ("battery", "home battery"),
}

# intra-country branches (question B ii), link carrier pattern -> group
TRANSMISSION: dict[str, str] = {
    "DC": r"^DC$",
    "H2 pipeline": r"^H2 pipeline",
    "gas pipeline": r"^gas pipeline",
}

# mirrors of the constraint definitions, see the module docstring
ELECTRICITY_CARRIERS: tuple[str, ...] = ("AC", "low voltage")
NON_ENERGY_CARRIERS: tuple[str, ...] = ("co2", "co2 stored", "process emissions")
PRODUCTION_GENERATORS: dict[str, tuple[str, ...]] = {
    "solar": ("solar", "solar-hsat", "solar rooftop"),
    "wind": ("onwind", "offwind-ac", "offwind-dc", "offwind-float"),
    "hydro": ("hydro inflow", "ror", "PHS inflow"),
}
PRODUCTION_LINKS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "biomass": (("solid biomass", "biogas", "renewable gas"), ELECTRICITY_CARRIERS),
}
# added to the biomass sources when the net-zero electricity constraint is enabled
EAG_BIOMASS_ADDITIONS: tuple[str, ...] = ("gas",)
DISCHARGERS: tuple[str, ...] = (
    "battery discharger",
    "home battery discharger",
    "V2G",
    "PHS discharger",
    "hydro discharger",
)
OUTPUT_PORTS: tuple[int, ...] = (1, 2, 3, 4)

# national policy constraints of P3; {ct} is the country
POLICY_CONSTRAINTS: tuple[str, ...] = (
    "co2_limit-{ct}",
    "production_limit_lower-solar-{ct}",
    "production_limit_lower-wind-{ct}",
    "production_limit_lower-hydro-{ct}",
    "production_limit_lower-biomass-{ct}",
    "capacity_minimum-{ct}-Link-H2-Electrolysis",
    "net-zero-electricity-production-{ct}",
    "green-gas-production-{ct}",
    "green-h2-production-{ct}",
    "green-methanol-production-{ct}",
)
# indicators of the binding constraints on the elements of each policy (question C3)
POLICY_ELEMENTS: dict[str, tuple[str, ...]] = {
    "co2_limit-{ct}": ("EU CO2 price", "CO2 sequestration price"),
    "production_limit_lower-solar-{ct}": (
        "binding buses ground PV",
        "binding buses rooftop PV",
    ),
    "production_limit_lower-wind-{ct}": ("binding buses onwind",),
    "production_limit_lower-hydro-{ct}": ("binding buses ror",),
    "production_limit_lower-biomass-{ct}": ("biomass potential used",),
    "capacity_minimum-{ct}-Link-H2-Electrolysis": ("electrolysis links at p_nom_max",),
    "net-zero-electricity-production-{ct}": ("net import AC",),
    "green-gas-production-{ct}": ("net import gas",),
    "green-h2-production-{ct}": ("net import H2",),
    "green-methanol-production-{ct}": ("net import methanol",),
}


def _country_frame(
    networks: Networks, func: Callable[[pypsa.Network], pd.Series | pd.DataFrame]
) -> pd.DataFrame:
    """Apply ``func`` to every network and stack the results by scenario and horizon."""
    frames = {}
    for scenario, horizons in networks.items():
        for horizon, n in horizons.items():
            result = func(n)
            frames[(scenario, horizon)] = (
                result.to_frame().T if isinstance(result, pd.Series) else result
            )
    frame = pd.concat(frames, names=["scenario", "horizon"])
    if all(isinstance(f.index, pd.RangeIndex) for f in frames.values()):
        frame = frame.droplevel(-1)
    return frame


def add_deltas(
    table: pd.DataFrame, reference: str, columns: list[str] | None = None
) -> pd.DataFrame:
    """
    Add the difference to the reference scenario for numeric columns.

    Parameters
    ----------
    table
        Frame with a ``scenario`` level and further levels shared by all scenarios.
    reference
        The reference scenario.
    columns
        Columns to compare; all numeric columns if missing.

    Returns
    -------
    :
        A copy with a column ``Δ <column>`` per compared column.
    """
    table = table.copy()
    columns = columns or list(table.select_dtypes("number").columns)
    others = [name for name in table.index.names if name != "scenario"]
    ref = table.xs(reference, level="scenario")[columns]
    aligned = ref.reindex(table.index.droplevel("scenario")).to_numpy()
    for i, column in enumerate(columns):
        table[f"Δ {column}"] = table[column].to_numpy() - aligned[:, i]
    return table.reorder_levels(["scenario", *others]) if others else table


# --- locations -----------------------------------------------------------------


def bus_locations(n: pypsa.Network) -> pd.Series:
    """Return the location of every bus; buses without one locate at themselves."""
    location = n.buses.location.fillna("")
    return location.where(location != "", n.buses.index.to_series())


def region(locations: pd.Series, level: int = 2) -> pd.Series:
    """Return the NUTS region of a level (``AT111`` -> ``AT11`` for level 2)."""
    return locations.str[: 2 + level]


def _in_country(n: pypsa.Network, buses: pd.Series, country: str) -> pd.Series:
    """Whether each bus of a component column lies in the country."""
    return buses.map(bus_locations(n)).fillna("").str[:2].eq(country)


# --- (1) checks ----------------------------------------------------------------


def flatten(d: dict, prefix: str = "") -> dict:
    """Return the leaves of a nested dict, keyed by their dotted path."""
    flat = {}
    for key, value in d.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat |= flatten(value, f"{path}.")
        else:
            flat[path] = value
    return flat


def config_diff(meta: dict, reference: dict, expected: set[str] = frozenset()) -> set:
    """
    Return the config keys in which a run differs from the reference.

    Parameters
    ----------
    meta, reference
        Resolved run configurations (``n.meta``).
    expected
        Keys that may differ; a key set to null drops all leaves below it,
        so leaves below an expected key are reported as that key.

    Returns
    -------
    :
        Dotted keys, without :data:`IGNORED_KEYS`.
    """
    a = {k: v for k, v in meta.items() if k not in IGNORED_KEYS}
    b = {k: v for k, v in reference.items() if k not in IGNORED_KEYS}
    a, b = flatten(a), flatten(b)
    differ = {k for k in a.keys() | b.keys() if not _same(a.get(k), b.get(k))}
    return {next((e for e in expected if k.startswith(f"{e}.")), k) for k in differ}


def _same(a, b) -> bool:
    """Whether two config values are equal, NaN equal to NaN."""
    if isinstance(a, float) and isinstance(b, float) and np.isnan(a) and np.isnan(b):
        return True
    return a == b


def at_buses(n: pypsa.Network, country: str) -> int:
    """Return the number of AC buses in the country."""
    buses = n.buses[n.buses.carrier == "AC"]
    return int(bus_locations(n)[buses.index].str[:2].eq(country).sum())


def checks(
    files: Mapping[str, Mapping[str, object]],
    networks: Networks,
    reference: str,
    country: str,
) -> list[Check]:
    """
    Run the checks of step 1.

    Parameters
    ----------
    files
        Network file per horizon per scenario, see ``find_scenarios``.
    networks
        Solved networks per horizon per scenario.
    reference
        The reference scenario.
    country
        Country code.

    Returns
    -------
    :
        Checks ``Solved``, ``Spatial``, ``Config diff`` and ``P3 constraints``.
    """
    results = []

    horizons = {s: tuple(sorted(h)) for s, h in files.items() if s in networks}
    differ = {s: h for s, h in horizons.items() if h != horizons[reference]}
    results.append(
        Check(
            "Solved",
            "fail" if differ else "ok",
            f"horizons differ from {reference}: {differ}"
            if differ
            else f"{len(horizons)} scenarios × {len(horizons[reference])} horizons",
        )
    )

    rows = []
    for scenario, nets in networks.items():
        for horizon, n in nets.items():
            level = n.meta["clustering"]["administrative"].get(country)
            rows.append(
                {
                    "scenario": scenario,
                    "horizon": horizon,
                    "level": level,
                    "expected": BUSES_PER_LEVEL.get(level, np.nan),
                    "buses": at_buses(n, country),
                }
            )
    spatial = pd.DataFrame(rows).set_index(["scenario", "horizon"])
    wrong = spatial[spatial.buses != spatial.expected]
    results.append(
        Check(
            "Spatial",
            "fail" if len(wrong) else "ok",
            f"{len(wrong)} networks with an unexpected number of {country} AC buses"
            if len(wrong)
            else f"{country} AC buses match the NUTS level of every run",
            spatial,
        )
    )

    rows = []
    for scenario in networks:
        if scenario == reference:
            continue
        # a run is compared with its own reference, e.g. the P3 pair
        ref = DP_REFERENCES.get(scenario, reference)
        if ref not in files:
            rows.append(
                {
                    "scenario": scenario,
                    "expected": f"reference {ref} not loaded",
                    "unexpected": "",
                    "missing": "",
                }
            )
            continue
        ref_meta = read_meta(next(iter(files[ref].values())))
        expected = DP_DIFFERENCES.get(scenario)
        meta = read_meta(next(iter(files[scenario].values())))
        found = config_diff(meta, ref_meta, expected or set())
        rows.append(
            {
                "scenario": scenario,
                "expected": ", ".join(sorted(expected)) if expected else "unknown run",
                "unexpected": ", ".join(sorted(found - (expected or found))),
                "missing": ", ".join(sorted((expected or found) - found)),
            }
        )
    diff = pd.DataFrame(rows).set_index("scenario") if rows else pd.DataFrame()
    bad = diff[(diff.unexpected != "") | (diff.missing != "")] if rows else diff
    unknown = (
        diff[diff.expected.str.startswith(("unknown run", "reference "))]
        if rows
        else diff
    )
    status = "fail" if len(bad) else "warn" if len(unknown) else "ok"
    results.append(
        Check(
            "Config diff",
            status,
            f"{len(bad)} runs differ from their reference in other keys than expected"
            if len(bad)
            else "every run differs from its reference only in its principle"
            + (f" ({len(unknown)} runs without expected keys)" if len(unknown) else ""),
            diff,
        )
    )

    rows = []
    for scenario, nets in networks.items():
        # only the run without policies; its pair keeps them
        if scenario not in DP_REFERENCES or "P3" not in _principle(scenario):
            continue
        for horizon, n in nets.items():
            names = [c.format(ct=country) for c in POLICY_CONSTRAINTS]
            present = n.global_constraints.reindex(names).dropna(subset=["sense"])
            active = present[present.constant.abs() > 0]
            active = active[~active.index.str.startswith(("green-", "net-zero"))]
            # zero limits stay in the network, non-binding
            rows.append(
                {
                    "scenario": scenario,
                    "horizon": horizon,
                    "remaining": ", ".join(
                        sorted(
                            set(active.index)
                            | {
                                k
                                for k in present.index
                                if k.startswith(("green-", "net-zero"))
                            }
                        )
                    ),
                }
            )
    p3 = pd.DataFrame(rows)
    left = p3[p3.remaining != ""] if len(p3) else p3
    results.append(
        Check(
            "P3 constraints",
            "fail" if len(left) else "ok",
            f"{len(left)} P3 networks keep a national policy constraint"
            if len(left)
            else "no national policy constraint left in the P3 runs",
            p3.set_index(["scenario", "horizon"]) if len(p3) else p3,
        )
    )
    return results


def _principle(scenario: str) -> str:
    """Return the principle a DP run switches off (``DP3_...`` -> ``P3``)."""
    match = re.match(r"DP(\d+)", scenario)
    return f"P{match.group(1)}" if match else ""


# --- (4) binding constraints ---------------------------------------------------


def constraint_group(name: str, country: str) -> str:
    """Return the group of a global constraint: national policy, EU/DE, TYNDP or other."""
    policy = {c.format(ct=country) for c in POLICY_CONSTRAINTS}
    if name in policy:
        return "national policy"
    if name.startswith(("tyndp", "Trajectories")):
        return "TYNDP & trajectories"
    if name in (EU_CO2_LIMIT, "co2_sequestration_limit") or re.search(
        r"-DE($|-)", name
    ):
        return "EU / DE"
    return "other"


def global_constraints(networks: Networks, country: str) -> pd.DataFrame:
    """
    Return every global constraint with its dual, TYNDP constraints summed per type.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code, for the grouping.

    Returns
    -------
    :
        Columns ``group``, ``count``, ``binding`` (number of binding
        constraints), ``constant`` and ``mu`` (sums for TYNDP types), indexed
        by ``scenario``, ``horizon`` and ``name``.
    """

    def table(n: pypsa.Network) -> pd.DataFrame:
        gc = n.global_constraints[["constant", "mu"]].rename_axis(None)
        gc["name"] = gc.index.str.replace(r"\[.*\]$", "", regex=True)
        gc["binding"] = gc.mu.abs() > MU_TOLERANCE
        gc["count"] = 1
        out = gc.groupby("name").agg(
            count=("count", "sum"),
            binding=("binding", "sum"),
            constant=("constant", "sum"),
            mu=("mu", "sum"),
        )
        out.insert(0, "group", [constraint_group(i, country) for i in out.index])
        return out

    return _country_frame(networks, table)


def binding_matrix(table: pd.DataFrame, group: str | None = None) -> pd.DataFrame:
    """Return ``mu`` as constraint × (scenario, horizon), only binding rows."""
    if group:
        table = table[table.group == group]
    mu = table.mu.unstack(["scenario", "horizon"])
    return mu[(mu.abs() > MU_TOLERANCE).any(axis=1)]


# --- (5) cost ------------------------------------------------------------------


def costs(networks: Networks, country: str) -> pd.DataFrame:
    """
    Return the cost in the country and the EU system cost in bn EUR.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.

    Returns
    -------
    :
        Columns ``capex``, ``opex``, ``trade``, ``total`` (cost in the
        country, see ``country_cost``) and ``system cost``, indexed by
        ``scenario`` and ``horizon``.
    """

    def row(n: pypsa.Network) -> pd.Series:
        cost = country_cost(n, country) / BN
        cost["system cost"] = system_cost(n) / BN
        return cost

    return _country_frame(networks, row).astype(float)


# --- (A) potentials ------------------------------------------------------------


def potentials(n: pypsa.Network, country: str) -> pd.DataFrame:
    """
    Return potential, capacity and production per bus location and carrier group.

    The potential of a location is the ``p_nom_max`` of the extendable
    generators (the headroom left after the brownfield deduction) plus the
    ``p_nom`` of the existing ones. Ground PV takes the ``p_nom_max`` of
    ``solar`` only, as ``solar`` and ``solar-hsat`` share one land potential.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        Columns ``potential``, ``capacity`` (MW), ``production``,
        ``available`` (MWh), ``forced`` (every extendable generator has
        ``p_nom_min`` at its ``p_nom_max``) and ``binding`` (capacity at the
        potential and not forced), indexed by ``location`` and ``group``.
    """
    groups = {c: g for g, carriers in POTENTIAL_GROUPS.items() for c in carriers}
    gens = n.generators[
        n.generators.carrier.isin(groups) & _in_country(n, n.generators.bus, country)
    ].copy()
    columns = ["potential", "capacity", "production", "available", "forced", "binding"]
    if gens.empty:
        return pd.DataFrame(columns=columns)
    gens["group"] = gens.carrier.map(groups)
    gens["location"] = gens.bus.map(bus_locations(n))
    weights = n.snapshot_weightings.generators
    p = n.generators_t.p.reindex(columns=gens.index, fill_value=0.0)
    p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu")[gens.index]
    gens["production"] = p.mul(weights, axis=0).sum()
    gens["available"] = p_max_pu.mul(gens.p_nom_opt).mul(weights, axis=0).sum()

    shared = gens.group.map(SHARED_POTENTIAL)
    counts = gens.p_nom_extendable & (shared.isna() | (gens.carrier == shared))
    gens["headroom"] = gens.p_nom_max.where(counts & gens.p_nom_extendable, 0.0)
    gens["existing"] = gens.p_nom.where(~gens.p_nom_extendable, 0.0)
    gens["is_forced"] = (
        gens.p_nom_extendable
        & (gens.p_nom_max > 0)
        & (gens.p_nom_min >= TOLERANCE * gens.p_nom_max)
    ).where(counts, True)

    out = gens.groupby(["location", "group"]).agg(
        headroom=("headroom", "sum"),
        existing=("existing", "sum"),
        capacity=("p_nom_opt", "sum"),
        production=("production", "sum"),
        available=("available", "sum"),
        forced=("is_forced", "all"),
    )
    out["potential"] = out.headroom + out.existing
    out["forced"] = out.forced & (out.headroom > 0)
    out["binding"] = (
        (out.potential > 0)
        & (out.capacity >= TOLERANCE * out.potential)
        & ~out.forced
        & np.isfinite(out.potential)
    )
    return out[columns]


def potential_summary(networks: Networks, country: str) -> pd.DataFrame:
    """
    Sum :func:`potentials` over the country.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.

    Returns
    -------
    :
        Columns ``potential``, ``capacity`` (GW), ``utilisation``,
        ``binding buses``, ``forced buses``, ``buses``, ``capacity at binding``
        (share of the capacity at binding buses), ``production``,
        ``curtailment`` (TWh) and ``capacity factor``, indexed by
        ``scenario``, ``horizon`` and ``group``.
    """

    def summary(n: pypsa.Network) -> pd.DataFrame:
        bus = potentials(n, country)
        rows = {}
        for group, b in bus.groupby(level="group"):
            capacity = b.capacity.sum()
            rows[group] = {
                "potential": b.potential.sum() / GW,
                "capacity": capacity / GW,
                "utilisation": capacity / b.potential.sum()
                if b.potential.sum() > 0
                else np.nan,
                "binding buses": int(b.binding.sum()),
                "forced buses": int(b.forced.sum()),
                "buses": len(b),
                "capacity at binding": b.capacity[b.binding].sum() / capacity
                if capacity > 0
                else np.nan,
                "production": b.production.sum() / TWH,
                "curtailment": (b.available.sum() - b.production.sum()) / TWH,
                "capacity factor": b.production.sum() / (capacity * 8760)
                if capacity > 0
                else np.nan,
            }
        out = pd.DataFrame.from_dict(rows, orient="index")
        out.index.name = "group"
        return out

    return _country_frame(networks, summary)


# --- (B) regional capacities ---------------------------------------------------


def regional_capacities(n: pypsa.Network, country: str, level: int = 2) -> pd.Series:
    """
    Return capacities per NUTS region and technology.

    Generators and links by ``p_nom_opt`` (links at their input, heat pumps
    by their nominal power), stores by ``e_nom_opt``. A component lies in the
    region of its bus (``bus0`` for links).

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.
    level
        NUTS level of the regions.

    Returns
    -------
    :
        GW (GWh for stores), indexed by ``region`` and ``technology``.
    """
    regions = region(bus_locations(n), level)
    parts = []

    gens = n.generators
    for technology, carriers in GENERATOR_TECHNOLOGIES.items():
        g = gens[gens.carrier.isin(carriers)]
        parts.append(_by_region(g.p_nom_opt, g.bus.map(regions), technology))
    for technology, pattern in LINK_TECHNOLOGIES.items():
        link = n.links[n.links.carrier.str.contains(pattern)]
        parts.append(_by_region(link.p_nom_opt, link.bus0.map(regions), technology))
    for technology, carriers in STORE_TECHNOLOGIES.items():
        s = n.stores[n.stores.carrier.isin(carriers)]
        parts.append(_by_region(s.e_nom_opt, s.bus.map(regions), technology))

    out = pd.concat(parts) / GW
    return out[out.index.get_level_values("region").str[:2] == country]


def _by_region(values: pd.Series, regions: pd.Series, technology: str) -> pd.Series:
    out = values.groupby(regions).sum()
    out.index = pd.MultiIndex.from_product(
        [out.index, [technology]], names=["region", "technology"]
    )
    return out


def regional_comparison(
    networks: Networks, country: str, reference: str, other: str, level: int = 2
) -> pd.DataFrame:
    """
    Compare the regional capacities of two runs at one NUTS level.

    The finer run is summed to the regions of ``level``, so runs of different
    spatial resolution compare region by region.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.
    reference, other
        The two scenarios.
    level
        NUTS level of the comparison.

    Returns
    -------
    :
        Columns ``reference``, ``other``, ``Δ`` and ``Δ %``, indexed by
        ``horizon``, ``technology`` and ``region``. Regions missing in one run
        count as zero.
    """
    frames = {}
    for horizon in networks[reference]:
        a = regional_capacities(networks[reference][horizon], country, level)
        b = regional_capacities(networks[other][horizon], country, level)
        frame = pd.concat({"reference": a, "other": b}, axis=1).fillna(0.0)
        frames[horizon] = frame.swaplevel().sort_index()
    out = pd.concat(frames, names=["horizon"])
    out["Δ"] = out.other - out.reference
    out["Δ %"] = 100 * out["Δ"] / out.reference.where(out.reference.abs() > 1e-9)
    return out


def regional_shift(comparison: pd.DataFrame) -> pd.DataFrame:
    """
    Separate how much is built from where it is built.

    Parameters
    ----------
    comparison
        Output of :func:`regional_comparison`.

    Returns
    -------
    :
        Columns ``reference``, ``other``, ``Δ total`` (GW) and ``shift``
        (``Σ_regions |Δ| / reference total``), indexed by ``horizon`` and
        ``technology``.
    """
    grouped = comparison.groupby(level=["horizon", "technology"])
    out = grouped[["reference", "other"]].sum()
    out["Δ total"] = out.other - out.reference
    absolute = grouped["Δ"].apply(lambda d: d.abs().sum())
    out["shift"] = absolute / out.reference.where(out.reference.abs() > 1e-9)
    return out


# --- (B ii) transmission -------------------------------------------------------


def _branches(n: pypsa.Network, country: str, level: int) -> pd.DataFrame:
    """Return the branches inside a country with their flows and bounds."""
    regions = region(bus_locations(n), level)
    countries = bus_locations(n).str[:2]
    frames = []
    for component, static, p0, nom, max_pu in [
        ("Line", n.lines, n.lines_t.p0, "s_nom", "s_max_pu"),
        ("Link", n.links, n.links_t.p0, "p_nom", "p_max_pu"),
    ]:
        if component == "Line":
            group = pd.Series("AC", index=static.index)
        else:
            group = pd.Series(np.nan, index=static.index, dtype=object)
            for name, pattern in TRANSMISSION.items():
                group[static.carrier.str.contains(pattern)] = name
        inside = (
            group.notna()
            & static.bus0.map(countries).eq(country)
            & static.bus1.map(countries).eq(country)
        )
        s = static[inside]
        frames.append(
            pd.DataFrame(
                {
                    "component": component,
                    "carrier": group[inside],
                    "cross": s.bus0.map(regions).to_numpy()
                    != s.bus1.map(regions).to_numpy(),
                    "length": s.length,
                    "nom": s[nom],
                    "nom_opt": s[f"{nom}_opt"],
                    "max_pu": s[max_pu],
                }
            )
        )
    return pd.concat(frames)


def transmission(n: pypsa.Network, country: str, level: int = 2) -> pd.DataFrame:
    """
    Return the gross transmission on the branches inside a country.

    Gross means no netting of directions, snapshots or branches: a flow
    counts once per branch it passes. Transport work (TWh·km) weights every
    branch with its length and does not depend on how a route is split.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.
    level
        NUTS level that defines the branches crossing region borders.

    Returns
    -------
    :
        Columns ``branches``, ``energy`` (TWh), ``transport work`` (TWh·km),
        ``capacity``, ``added`` (GW), ``mean loading`` (capacity-weighted)
        and ``time at limit`` (share of time, averaged over branches),
        indexed by ``carrier`` and ``view`` (``all`` or ``cross-region``).
    """
    branches = _branches(n, country, level)
    weights = n.snapshot_weightings.generators
    flows = pd.concat(
        [
            n.lines_t.p0.reindex(columns=branches.index[branches.component == "Line"]),
            n.links_t.p0.reindex(columns=branches.index[branches.component == "Link"]),
        ],
        axis=1,
    ).fillna(0.0)
    flows = flows.loc[:, ~flows.columns.duplicated()].abs()
    branches = branches[~branches.index.duplicated()]
    limit = (branches.nom_opt * branches.max_pu).where(lambda s: s > 0)
    loading = flows.div(limit)
    branches["energy"] = flows.mul(weights, axis=0).sum()
    branches["work"] = branches.energy * branches.length
    branches["loading"] = loading.mul(weights, axis=0).sum() / weights.sum()
    branches["at_limit"] = (loading >= 0.99).mul(weights, axis=0).sum() / weights.sum()

    rows = {}
    for carrier, b in branches.groupby("carrier"):
        for view, part in [("all", b), ("cross-region", b[b.cross])]:
            capacity = part.nom_opt.sum()
            rows[(carrier, view)] = {
                "branches": len(part),
                "energy": part.energy.sum() / TWH,
                "transport work": part.work.sum() / TWH,
                "capacity": capacity / GW,
                "added": (part.nom_opt - part.nom).sum() / GW,
                "mean loading": (part.loading * part.nom_opt).sum() / capacity
                if capacity > 0
                else np.nan,
                "time at limit": part.at_limit.mean() if len(part) else np.nan,
            }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.names = ["carrier", "view"]
    return out


def transmission_table(
    networks: Networks, country: str, level: int = 2
) -> pd.DataFrame:
    """Return :func:`transmission` for every run."""
    return _country_frame(networks, lambda n: transmission(n, country, level))


# --- (C) policy ----------------------------------------------------------------


def _energy(p: pd.DataFrame, columns: pd.Index, weights: pd.Series) -> pd.Series:
    """Return the weighted annual sum of the columns of a flow table."""
    return p.reindex(columns=columns, fill_value=0.0).mul(weights, axis=0).sum()


def _turbine_weights(n: pypsa.Network, generators: pd.Index) -> pd.Series:
    """Mirror of ``mods.utils.inflow_turbine_weights``."""
    electricity = n.buses.index[n.buses.carrier.isin(ELECTRICITY_CARRIERS)]
    turbines = n.links[n.links.bus1.isin(electricity)]
    efficiency = turbines.groupby("bus0")["efficiency"].mean()
    weights = pd.Series(1.0, index=generators)
    on_store = ~n.generators.loc[generators, "bus"].isin(electricity)
    store_buses = n.generators.loc[generators[on_store], "bus"]
    weights[store_buses.index] = store_buses.map(efficiency).to_numpy()
    return weights


def production(
    n: pypsa.Network, source: str, region: str, eag: bool | None = None
) -> float:
    """
    Return the production of an EAG source, as in ``production_limit_*``.

    Mirrors ``mods.constraints.production._production_expression``.

    Parameters
    ----------
    n
        A solved network.
    source
        ``solar``, ``wind``, ``hydro`` or ``biomass``.
    region
        Region prefix of the components.
    eag
        Whether biomass includes gas-to-power (``mods.net_zero_electricity.enable``);
        from ``n.meta`` if missing. Pass the reference's setting to compare
        runs with the same formula.

    Returns
    -------
    :
        Production in MWh.
    """
    weights = n.snapshot_weightings.generators
    if source in PRODUCTION_GENERATORS:
        gens = n.generators[
            n.generators.bus.str.startswith(region)
            & n.generators.carrier.isin(PRODUCTION_GENERATORS[source])
            & n.generators.active
        ].index
        energy = _energy(n.generators_t.p, gens, weights)
        return float((energy * _turbine_weights(n, gens)).sum())
    sources, targets = PRODUCTION_LINKS[source]
    if eag is None:
        eag = n.meta["mods"]["net_zero_electricity"]["enable"]
    if eag:
        sources = (*sources, *EAG_BIOMASS_ADDITIONS)
    at_region = n.buses.index.str.startswith(region)
    from_buses = n.buses.index[n.buses.carrier.isin(sources) & at_region]
    to_buses = n.buses.index[n.buses.carrier.isin(targets) & at_region]
    total = 0.0
    for port in _ports(n.links):
        eff = _efficiency_column(port)
        links = n.links[
            n.links.bus0.isin(from_buses)
            & n.links[f"bus{port}"].isin(to_buses)
            & n.links.active
            & (n.links[eff] > 0)
        ]
        total += (_energy(n.links_t.p0, links.index, weights) * links[eff]).sum()
    return float(total)


def _efficiency_column(port: int) -> str:
    return "efficiency" if port == 1 else f"efficiency{port}"


def electrolysis_capacity(n: pypsa.Network, country: str) -> float:
    """
    Return the extendable electrolysis capacity, as in ``capacity_minimum``.

    Mirrors ``add_capacity_limits`` of ``scripts/pypsa-de/additional_functionality.py``:
    the constant of the constraint is the limit minus the existing capacity, so
    only the extendable capacity counts.
    """
    carrier = "H2 Electrolysis"
    links = n.links[
        (n.links.index.str[:2] == country)
        & (n.links.carrier.str[: len(carrier)] == carrier)
        & ~n.links.carrier.str.contains("thermal")
        & n.links.p_nom_extendable
        & n.links.active
    ]
    return float(links.p_nom_opt.sum())


def _electricity_fraction(n: pypsa.Network, links: pd.DataFrame) -> pd.Series:
    """Mirror of ``mods.constraints.eag._compute_electricity_fraction``."""
    electricity = n.buses.index[n.buses.carrier.isin(ELECTRICITY_CARRIERS)]
    non_energy = n.buses.index[n.buses.carrier.isin(NON_ENERGY_CARRIERS)]
    elec = pd.Series(0.0, index=links.index)
    total = pd.Series(0.0, index=links.index)
    for port in _ports(links):
        eff = links[_efficiency_column(port)].fillna(0.0).clip(lower=0.0)
        assigned = links[f"bus{port}"].fillna("").ne("")
        eff = eff.where(assigned & ~links[f"bus{port}"].isin(non_energy), 0.0)
        elec += eff.where(links[f"bus{port}"].isin(electricity), 0.0)
        total += eff
    return (elec / total.replace(0.0, np.nan)).fillna(1.0)


def _ports(links: pd.DataFrame) -> list[int]:
    """Return the output ports of the links table that exist."""
    return [p for p in OUTPUT_PORTS if f"bus{p}" in links]


def _country_links(n: pypsa.Network, country: str) -> pd.DataFrame:
    return n.links[n.links.index.str.startswith(country) & n.links.active]


def _has_electricity_output(
    n: pypsa.Network, links: pd.DataFrame, positive: bool = True
) -> pd.Series:
    electricity = n.buses.index[n.buses.carrier.isin(ELECTRICITY_CARRIERS)]
    out = pd.Series(False, index=links.index)
    for port in _ports(links):
        mask = links[f"bus{port}"].isin(electricity)
        if positive:
            mask &= links[_efficiency_column(port)] > 0
        out |= mask
    return out


def net_zero_electricity(n: pypsa.Network, country: str) -> tuple[float, float]:
    """
    Return the green production net of demand and the fixed demand.

    Mirrors ``mods.constraints.eag._add_net_zero_electricity_production_constraint``:
    the constraint reads ``value >= fixed demand``.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        ``(value, fixed demand)`` in MWh.
    """
    weights = n.snapshot_weightings.generators
    electricity = n.buses.index[n.buses.carrier.isin(ELECTRICITY_CARRIERS)]
    hydro = set(n.meta["renewable"]["hydro"]["carriers"])
    renewables = (set(n.meta["renewable"]) | {"solar rooftop"}) | hydro
    fuels = n.meta["mods"]["net_zero_electricity"]["fuels"]
    links = _country_links(n, country)
    gens = n.generators[
        n.generators.index.str.startswith(country) & n.generators.active
    ]
    loads = n.loads[n.loads.index.str.startswith(country) & n.loads.active]
    buses = n.buses[n.buses.index.str.startswith(country)]
    p = n.links_t.p0

    load = loads[loads.bus.isin(electricity)].index
    dynamic = n.loads_t.p_set.columns.intersection(load)
    fixed = (
        n.loads_t.p_set[dynamic].mul(weights, axis=0).sum().sum()
        + loads.loc[load.difference(dynamic), "p_set"].sum() * weights.sum()
    )

    lhs = _energy(
        n.generators_t.p,
        gens.index[gens.bus.isin(electricity) & gens.carrier.isin(renewables)],
        weights,
    ).sum()
    fuel_buses = buses.index[buses.carrier.isin(fuels)]
    for port in _ports(links):
        eff = _efficiency_column(port)
        idx = links.index[
            links.bus0.isin(fuel_buses)
            & links[f"bus{port}"].isin(electricity)
            & (links[eff] > 0)
        ]
        lhs += (_energy(p, idx, weights) * links.loc[idx, eff]).sum()
    idx = links.index[links.bus1.isin(electricity) & links.carrier.isin(DISCHARGERS)]
    lhs += (_energy(p, idx, weights) * links.loc[idx, "efficiency"]).sum()

    has_output = _has_electricity_output(n, links, positive=False)
    idx = links.index[links.bus0.isin(electricity) & ~has_output]
    rhs = _energy(p, idx, weights).sum()
    for port in _ports(links):
        eff = _efficiency_column(port)
        idx = links.index[links[f"bus{port}"].isin(electricity) & (links[eff] < 0)]
        rhs -= (_energy(p, idx, weights) * links.loc[idx, eff]).sum()
    reverse = links.p_max_pu.le(0)
    for port in _ports(links):
        eff = _efficiency_column(port)
        idx = links.index[
            reverse & links[f"bus{port}"].isin(electricity) & (links[eff] > 0)
        ]
        if idx.empty:
            continue
        cop = n.links_t.get(eff, pd.DataFrame()).reindex(columns=idx)
        rhs -= (
            p.reindex(columns=idx, fill_value=0.0)
            .mul(cop)
            .mul(weights, axis=0)
            .sum()
            .sum()
        )
    idx = links.index[links.carrier == "electricity distribution grid"]
    rhs += (_energy(p, idx, weights) * (1 - links.loc[idx, "efficiency"])).sum()
    lines = n.lines[
        n.lines.bus0.str.startswith(country) & n.lines.bus1.str.startswith(country)
    ]
    if n.meta["solving"]["options"].get("transmission_losses", 0) and not lines.empty:
        losses = n.lines_t.p0[lines.index] + n.lines_t.p1[lines.index]
        rhs += losses.mul(weights, axis=0).sum().sum()
    return float(lhs - rhs), float(fixed)


def _green_fuel(
    n: pypsa.Network,
    country: str,
    fuel: str,
    producers: Callable[[pd.DataFrame, pd.Series], pd.Series],
) -> float:
    """Return green production minus electricity-bound use of a fuel (lhs - rhs)."""
    weights = n.snapshot_weightings.generators
    fuel_buses = n.buses.index[(n.buses.country == country) & (n.buses.carrier == fuel)]
    links = _country_links(n, country)
    bus0_carrier = links.bus0.map(n.buses.carrier)
    p = n.links_t.p0
    green = links.index[links.bus1.isin(fuel_buses) & producers(links, bus0_carrier)]
    lhs = (_energy(p, green, weights) * links.loc[green, "efficiency"]).sum()
    positive = fuel != "methanol"
    to_power = links[
        links.bus0.isin(fuel_buses) & _has_electricity_output(n, links, positive)
    ]
    rhs = (
        _energy(p, to_power.index, weights) * _electricity_fraction(n, to_power)
    ).sum()
    if fuel == "H2":
        others = [
            f for f in n.meta["mods"]["net_zero_electricity"]["fuels"] if f != "H2"
        ]
        targets = n.buses.index[
            (n.buses.country == country) & n.buses.carrier.isin(others)
        ]
        to_fuel = pd.Series(False, index=links.index)
        for port in _ports(links):
            to_fuel |= links[f"bus{port}"].isin(targets)
        rhs += _energy(
            p, links.index[links.bus0.isin(fuel_buses) & to_fuel], weights
        ).sum()
    return float(lhs - rhs)


def green_gas(n: pypsa.Network, country: str) -> float:
    """Mirror of ``_add_green_gas_production_constraint``: value ``>= 0``, MWh."""
    return _green_fuel(n, country, "gas", lambda links, bus0: bus0 != "gas")


def green_h2(n: pypsa.Network, country: str) -> float:
    """Mirror of ``_add_hydrogen_production_constraint``: value ``>= 0``, MWh."""
    sources = n.meta["mods"]["net_zero_electricity"]["h2_sources"]
    return _green_fuel(n, country, "H2", lambda links, bus0: bus0.isin(sources))


def green_methanol(n: pypsa.Network, country: str) -> float:
    """Mirror of ``_add_methanol_production_constraint``: value ``>= 0``, MWh."""
    return _green_fuel(n, country, "methanol", lambda links, bus0: bus0 != "methanol")


def policy_values(n: pypsa.Network, country: str, eag: bool | None = None) -> pd.Series:
    """
    Return the value of every national policy constraint, present or not.

    The value is the left-hand side in the terms of the constraint's
    ``constant`` (``co2_limit``: t CO2, production limits and net-zero
    electricity: MWh, electrolysis: MW, green fuels: MWh with constant 0).
    A run without the constraint shows what the expression reaches freely.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.
    eag
        Passed to :func:`production`.

    Returns
    -------
    :
        Values indexed by constraint name.
    """
    ct = country
    net_zero, _ = net_zero_electricity(n, ct)
    return pd.Series(
        {
            f"co2_limit-{ct}": national_co2_categories(n, ct).sum(),
            **{
                f"production_limit_lower-{s}-{ct}": production(n, s, ct, eag)
                for s in ("solar", "wind", "hydro", "biomass")
            },
            f"capacity_minimum-{ct}-Link-H2-Electrolysis": electrolysis_capacity(n, ct),
            f"net-zero-electricity-production-{ct}": net_zero,
            f"green-gas-production-{ct}": green_gas(n, ct),
            f"green-h2-production-{ct}": green_h2(n, ct),
            f"green-methanol-production-{ct}": green_methanol(n, ct),
        }
    )


def policy_status(networks: Networks, country: str, reference: str) -> pd.DataFrame:
    """
    Return value, bound and dual of every national policy constraint.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.
    reference
        Scenario whose constants are the targets of every run; its formulas
        apply to every run (biomass with or without gas-to-power).

    Returns
    -------
    :
        Columns ``sense``, ``constant`` (of the run, NaN without the
        constraint), ``target`` (constant of the reference), ``value``,
        ``slack`` (value minus target, signed so that negative means
        violated), ``mu`` and ``binding``, indexed by ``scenario``,
        ``horizon`` and ``constraint``.
    """
    frames = {}
    for scenario, horizons in networks.items():
        for horizon, n in horizons.items():
            ref_network = networks[reference][horizon]
            ref = ref_network.global_constraints
            eag = ref_network.meta["mods"]["net_zero_electricity"]["enable"]
            values = policy_values(n, country, eag)
            gc = n.global_constraints.reindex(values.index)
            target = ref.reindex(values.index)
            sense = gc.sense.fillna(target.sense)
            sign = np.where(sense == "<=", -1.0, 1.0)
            frame = pd.DataFrame(
                {
                    "sense": sense,
                    "constant": gc.constant,
                    "target": target.constant,
                    "value": values,
                    "slack": sign * (values - target.constant),
                    "mu": gc.mu,
                }
            )
            frame["binding"] = frame.mu.abs() > MU_TOLERANCE
            frames[(scenario, horizon)] = frame
    return pd.concat(frames, names=["scenario", "horizon", "constraint"])


def net_imports(n: pypsa.Network, country: str) -> pd.Series:
    """
    Return the net import of every carrier into a country in TWh.

    Counts the ports of transfers (lines, and links whose ``bus0`` has the
    carrier of the port) that connect the country with a bus of the same
    carrier outside it; accounting carriers are left out. Conversion links
    with a port abroad (``co2 atmosphere``, EU copper plates) are no trade.
    """
    flows = port_flows(n)
    branches = flows[flows.component.isin(["Line", "Link"])]
    bus0_carrier = branches.name.map(n.links.bus0.map(n.buses.carrier))
    branches = branches[
        (branches.component == "Line") | (bus0_carrier == branches.bus_carrier)
    ]
    countries = branches.groupby("name").bus_country.agg(set)
    crossing = countries.index[
        countries.map(lambda c: country in c and len(c - {"", country}) > 0)
    ]
    at_port = branches[
        branches.name.isin(crossing)
        & (branches.bus_country == country)
        & ~branches.bus_carrier.isin(NON_TRADE_BUS_CARRIERS)
    ]
    return -at_port.groupby("bus_carrier").energy.sum() / TWH


def policy_elements(n: pypsa.Network, country: str) -> pd.Series:
    """
    Return the indicators of the constraints that bind the policy elements.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        ``EU CO2 price`` and ``CO2 sequestration price`` (EUR/t), binding
        potential buses per group of (A), ``biomass potential used`` (share),
        ``electrolysis links at p_nom_max``, ``net import <carrier>`` (TWh)
        and ``binding TYNDP & trajectories`` with country elements.
    """
    gc = n.global_constraints
    out = {
        "EU CO2 price": -gc.mu.get(EU_CO2_LIMIT, np.nan),
        "CO2 sequestration price": gc.mu.get("co2_sequestration_limit", np.nan),
    }
    bus = potentials(n, country)
    for group in POTENTIAL_GROUPS:
        b = bus.xs(group, level="group") if group in bus.index.unique("group") else bus
        out[f"binding buses {group}"] = int(b.binding.sum()) if len(b) else 0

    weights = n.snapshot_weightings.generators
    bio = n.generators[
        n.generators.carrier.isin(BIOMASS_CARRIERS)
        & _in_country(n, n.generators.bus, country)
    ]
    used = _energy(n.generators_t.p, bio.index, weights).sum()
    potential = bio.e_sum_max.replace(np.inf, np.nan).sum()
    out["biomass potential used"] = used / potential if potential > 0 else np.nan

    links = n.links[
        (n.links.carrier == "H2 Electrolysis")
        & n.links.p_nom_extendable
        & _in_country(n, n.links.bus0, country)
    ]
    out["electrolysis links at p_nom_max"] = int(
        (links.p_nom_opt >= TOLERANCE * links.p_nom_max).sum()
    )
    imports = net_imports(n, country)
    for carrier in ("AC", "gas", "H2", "methanol"):
        out[f"net import {carrier}"] = imports.get(carrier, 0.0)
    tyndp = gc[
        gc.index.str.startswith(("tyndp", "Trajectories"))
        & gc.index.str.contains(rf"\b{country}")
    ]
    out["binding TYNDP & trajectories"] = int((tyndp.mu.abs() > MU_TOLERANCE).sum())
    return pd.Series(out)


def replacement_table(
    networks: Networks, country: str, reference: str, other: str
) -> pd.DataFrame:
    """
    Map every policy constraint to the indicators of its elements in two runs.

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.
    reference, other
        The run with and the run without the national policies.

    Returns
    -------
    :
        Columns ``reference``, ``other`` and ``Δ``, indexed by ``horizon``,
        ``constraint`` and ``indicator``.
    """
    rows = {}
    for horizon in networks[reference]:
        a = policy_elements(networks[reference][horizon], country)
        b = policy_elements(networks[other][horizon], country)
        for constraint, indicators in POLICY_ELEMENTS.items():
            for indicator in indicators:
                rows[(horizon, constraint.format(ct=country), indicator)] = {
                    "reference": a[indicator],
                    "other": b[indicator],
                }
    out = pd.DataFrame.from_dict(rows, orient="index").astype(float)
    out.index.names = ["horizon", "constraint", "indicator"]
    out["Δ"] = out.other - out.reference
    return out


def electrolysis_total(n: pypsa.Network, country: str) -> float:
    """Return the electrolysis capacity of all vintages in a country, MW."""
    links = n.links[
        (n.links.carrier == "H2 Electrolysis") & _in_country(n, n.links.bus0, country)
    ]
    return float(links.p_nom_opt.sum())


def policy_outcomes(networks: Networks, country: str, reference: str) -> pd.DataFrame:
    """
    Return the outcomes on the elements of the national policies (question C2).

    Parameters
    ----------
    networks
        Solved networks per horizon per scenario.
    country
        Country code.
    reference
        Scenario whose formulas apply to every run, see :func:`policy_status`.

    Returns
    -------
    :
        ``CO2`` (Mt), EAG production per source (TWh), ``electrolysis``
        (GW, all vintages), ``electricity balance`` (net-zero value minus fixed
        demand, TWh), ``green gas`` and ``green H2`` surplus (TWh) and the net
        imports (TWh), indexed by ``scenario`` and ``horizon``.
    """

    def row(n: pypsa.Network, eag: bool) -> pd.Series:
        values = policy_values(n, country, eag)
        _, fixed = net_zero_electricity(n, country)
        ct = country
        out = {
            "CO2": values[f"co2_limit-{ct}"] / MT,
            **{
                f"{s} production": values[f"production_limit_lower-{s}-{ct}"] / TWH
                for s in ("solar", "wind", "hydro", "biomass")
            },
            "electrolysis": electrolysis_total(n, ct) / GW,
            "electricity balance": (
                values[f"net-zero-electricity-production-{ct}"] - fixed
            )
            / TWH,
            "green gas surplus": values[f"green-gas-production-{ct}"] / TWH,
            "green H2 surplus": values[f"green-h2-production-{ct}"] / TWH,
        }
        imports = net_imports(n, country)
        for carrier in ("AC", "gas", "H2", "oil", "methanol"):
            out[f"net import {carrier}"] = imports.get(carrier, 0.0)
        return pd.Series(out)

    frames = {}
    for scenario, horizons in networks.items():
        for horizon, n in horizons.items():
            ref = networks[reference][horizon]
            eag = ref.meta["mods"]["net_zero_electricity"]["enable"]
            frames[(scenario, horizon)] = row(n, eag)
    out = pd.DataFrame.from_dict(frames, orient="index").astype(float)
    out.index.names = ["scenario", "horizon"]
    return out


# --- (C) target attainment and energy supply -----------------------------------

# short label and unit (label, divisor) of every national policy constraint
POLICY_LABELS: dict[str, str] = {
    "co2_limit-{ct}": "CO2 budget",
    "production_limit_lower-solar-{ct}": "EAG solar",
    "production_limit_lower-wind-{ct}": "EAG wind",
    "production_limit_lower-hydro-{ct}": "EAG hydro",
    "production_limit_lower-biomass-{ct}": "EAG biomass",
    "capacity_minimum-{ct}-Link-H2-Electrolysis": "Electrolysis",
    "net-zero-electricity-production-{ct}": "100 % RE electricity",
    "green-gas-production-{ct}": "Green gas surplus",
    "green-h2-production-{ct}": "Green H2 surplus",
    "green-methanol-production-{ct}": "Green methanol surplus",
}
POLICY_UNITS: dict[str, tuple[str, float]] = {
    "co2_limit": ("Mt CO2", MT),
    "capacity_minimum": ("GW", GW),
}
DEFAULT_POLICY_UNIT: tuple[str, float] = ("TWh", TWH)


def policy_attainment(status: pd.DataFrame, country: str) -> pd.DataFrame:
    """
    Return :func:`policy_status` in plot units, one row per run and constraint.

    Parameters
    ----------
    status
        Output of :func:`policy_status`.
    country
        Country code of the constraint names.

    Returns
    -------
    :
        Columns ``scenario``, ``horizon``, ``constraint`` (name), ``label``,
        ``unit``, ``value``, ``target``, ``slack`` (in ``unit``), ``mu`` and
        ``binding``, in the order of :data:`POLICY_LABELS`.
    """
    labels = {k.format(ct=country): v for k, v in POLICY_LABELS.items()}
    out = status.reset_index()
    out = out[out.constraint.isin(labels)].copy()
    units = out.constraint.map(
        lambda c: next(
            (u for prefix, u in POLICY_UNITS.items() if c.startswith(prefix)),
            DEFAULT_POLICY_UNIT,
        )
    )
    divisor = units.str[1]
    for column in ("value", "target", "slack"):
        out[column] = out[column] / divisor
    out["label"] = out.constraint.map(labels)
    out["unit"] = units.str[0]
    out["order"] = out.constraint.map({c: i for i, c in enumerate(labels)})
    columns = ["scenario", "horizon", "constraint", "label", "unit", "value"]
    columns += ["target", "slack", "mu", "binding"]
    return out.sort_values(["order", "scenario", "horizon"])[columns].reset_index(
        drop=True
    )


# energy carriers of the supply balance (question C2), carrier -> bus carriers;
# storage buses belong to the carrier they store, so storage is not production
ENERGY_CARRIERS: dict[str, tuple[str, ...]] = {
    "electricity": (
        "AC",
        "low voltage",
        "battery",
        "home battery",
        "EV battery",
        "PHS",
        "hydro",
    ),
    "methane": ("gas", "gas for industry"),
    "hydrogen": ("H2", "H2 for industry"),
    "liquid fuels": (
        "oil",
        "land transport oil",
        "agriculture machinery oil",
        "shipping oil",
        "kerosene for aviation",
        "naphtha for industry",
        "methanol",
        "industry methanol",
        "shipping methanol",
    ),
    "solid biomass": ("solid biomass", "solid biomass for industry"),
}
# generators that bring a carrier from outside the model into a country
IMPORT_GENERATOR = r"^import"


def energy_supply(n: pypsa.Network, country: str) -> pd.DataFrame:
    """
    Return how each energy carrier reaches a country: produced there or imported.

    ``produced`` is what generators and conversion links located in the country
    inject into buses of the carrier (renewables, power plants, electrolysis,
    biogas upgrading, Fischer-Tropsch, ...). Hydro and PHS count their inflow,
    before the turbine. A link is a *transfer* of a carrier if its ``bus0`` is a
    bus of that carrier (grids, pipelines, distribution, storage charging,
    ``gas for industry``); transfers neither produce nor consume.

    ``net import`` is the net inflow over transfers that connect the country's
    buses of the carrier with buses abroad, plus the carrier the country's
    assets take from (or put on) buses outside the country, such as the EU oil
    and methanol copper plates, plus ``import`` generators in the country.
    Negative values are net exports.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        Columns ``produced`` and ``net import`` in TWh, indexed by ``carrier``
        (the keys of :data:`ENERGY_CARRIERS`).
    """
    flows = port_flows(n)
    bus0_carrier = n.links.bus0.map(n.buses.carrier)
    rows = {}
    for carrier, bus_carriers in ENERGY_CARRIERS.items():
        f = flows[flows.bus_carrier.isin(bus_carriers)]
        transfer = (f.component == "Line") | (
            (f.component == "Link")
            & f.name.map(bus0_carrier).isin(bus_carriers).fillna(False)
        )
        imported = f.carrier.str.contains(IMPORT_GENERATOR) & (
            f.component == "Generator"
        )
        home = f.bus_country == country
        # transfers with ports of this carrier at home and abroad
        countries = f[transfer].groupby("name").bus_country.agg(set)
        crossing = countries.index[
            countries.map(lambda c: country in c and len(c - {country}) > 0)
        ]
        across = -f[transfer & home & f.name.isin(crossing)].energy.sum()
        assets = (
            f.component.isin(["Generator", "Link"])
            & ~transfer
            & (f.asset_country == country)
        )
        abroad = f[assets & ~imported & ~home].energy.sum()
        generators = -f[imported & home].energy.sum()
        injected = f[assets & ~imported].energy
        rows[carrier] = {
            "produced": -injected[injected < 0].sum() / TWH,
            "net import": (across + abroad + generators) / TWH,
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "carrier"
    return out


def energy_supply_table(networks: Networks, country: str) -> pd.DataFrame:
    """Return :func:`energy_supply` for every run, indexed by scenario, horizon, carrier."""
    frames = {
        (scenario, horizon): energy_supply(n, country)
        for scenario, horizons in networks.items()
        for horizon, n in horizons.items()
    }
    return pd.concat(frames, names=["scenario", "horizon"])
