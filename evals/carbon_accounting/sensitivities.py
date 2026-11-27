# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Compare the design-principle sensitivity runs with their reference runs.

Backs the notebook
``evals/carbon_accounting/notebooks/design_principle_sensitivities.py``. Each
sensitivity run (``DP<principle>S_<what>``) differs from its reference run in
one choice; the effect of a principle at a sensitivity point is the difference
of two runs in the headline metrics. See
``docs-ca/explanations/design-principle-sensitivities-spec.md``.

The functions reuse :mod:`evals.carbon_accounting.design_principles` and
:mod:`evals.carbon_accounting.accounting`. Unlike the DP evaluation, a missing
horizon does not stop the comparison: effects cover the horizons solved in
both runs, and :func:`solve_status` reports the others.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from evals.carbon_accounting.accounting import (
    BN,
    EU_CO2_LIMIT,
    MT,
    Check,
    co2_price,
    country_cost,
    national_budget,
    national_co2_categories,
    port_flows,
    read_meta,
)
from evals.carbon_accounting.design_principles import (
    DP_DIFFERENCES,
    GW,
    bus_locations,
    config_diff,
    energy_supply,
    potential_summary,
)

Networks = Mapping[str, Mapping[str, pypsa.Network]]

DP1 = "DP1_no_national_data"
DP3_WITH = "DP3_with_national_policy"
DP3_NO = "DP3_no_national_policy"
BASE = "DP_base"

# keys of DP3_no_national_policy that S2 removes in DP3S_targets_only: the
# national policy targets; the rest are the cross-border flow and
# infrastructure constraints, removed in DP3S_embedding_only
TARGET_KEYS: frozenset[str] = frozenset(
    k
    for k in DP_DIFFERENCES[DP3_NO]
    if k.startswith(
        (
            "solving.constraints.co2_budget_national.",
            "solving.constraints.limits_volume_min.",
            "solving.constraints.limits_capacity_min.",
            "mods.net_zero_electricity.",
        )
    )
)
EMBEDDING_KEYS: frozenset[str] = frozenset(DP_DIFFERENCES[DP3_NO] - TARGET_KEYS)
EU_CAP_KEYS: frozenset[str] = frozenset(
    f"co2_budget.upper.{year}" for year in range(2025, 2055, 5)
)
EXTENSION_KEYS: frozenset[str] = frozenset(
    f"mods.carbon_accounting.cross_border_extension_limits.{key}"
    for key in ("s_nom_max_extension", "p_nom_max_extension")
)

# keys in which each sensitivity run differs from its reference run
SENSITIVITY_DIFFERENCES: dict[str, set[str]] = {
    "DP1S_klien_low": {"mods.klien_potential_limits.ambition"},
    "DP1S_klien_high": {"mods.klien_potential_limits.ambition"},
    "DP3S_targets_only": set(TARGET_KEYS),
    "DP3S_embedding_only": set(EMBEDDING_KEYS),
    "DP3S_h2_price_low": {"sector.imports.price.H2"},
    "DP3S_h2_price_high": {"sector.imports.price.H2"},
    "DP3S_extension_half": set(EXTENSION_KEYS),
    "DP3S_extension_double": set(EXTENSION_KEYS),
    "DP3S_eu_cap_at_path_no_policy": set(EU_CAP_KEYS),
    "DP3S_eu_cap_at_path_with_policy": set(EU_CAP_KEYS),
}
# the reference run of each sensitivity run (one choice apart)
SENSITIVITY_REFERENCES: dict[str, str] = {
    "DP1S_klien_low": BASE,
    "DP1S_klien_high": BASE,
    "DP3S_targets_only": DP3_WITH,
    "DP3S_embedding_only": DP3_WITH,
    "DP3S_h2_price_low": DP3_NO,
    "DP3S_h2_price_high": DP3_NO,
    "DP3S_extension_half": DP3_NO,
    "DP3S_extension_double": DP3_NO,
    "DP3S_eu_cap_at_path_no_policy": DP3_NO,
    "DP3S_eu_cap_at_path_with_policy": DP3_WITH,
}
# documented causes of solves without an optimal solution, keyed by (run,
# horizon); filled from the results notes of the spec
DOCUMENTED_CAUSES: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class Point:
    """One effect at a sensitivity point: ``run`` minus ``reference``."""

    family: str
    point: str
    run: str
    reference: str


# the effect shown per sensitivity point, see the evaluation table of the spec
POINTS: tuple[Point, ...] = (
    # S1: P1 effect per KLIEN ambition, variant - DP1
    Point("S1", "low", "DP1S_klien_low", DP1),
    Point("S1", "medium", BASE, DP1),
    Point("S1", "high", "DP1S_klien_high", DP1),
    Point("S1", "technical", DP3_WITH, DP1),
    # S2: target, embedding and full P3 effect
    Point("S2", "targets", "DP3S_targets_only", DP3_WITH),
    Point("S2", "embedding", "DP3S_embedding_only", DP3_WITH),
    Point("S2", "full", DP3_NO, DP3_WITH),
    # S3, S4: P3 effect at each point
    Point("S3", "37 EUR/MWh", "DP3S_h2_price_low", DP3_WITH),
    Point("S3", "74 EUR/MWh", DP3_NO, DP3_WITH),
    Point("S3", "111 EUR/MWh", "DP3S_h2_price_high", DP3_WITH),
    Point("S4", "half", "DP3S_extension_half", DP3_WITH),
    Point("S4", "upstream", DP3_NO, DP3_WITH),
    Point("S4", "double", "DP3S_extension_double", DP3_WITH),
    # S5: effect of the cap and P3 effect at the same ambition
    Point("S5", "P3, EU cap", DP3_NO, DP3_WITH),
    Point("S5", "P3, AT path", "DP3S_eu_cap_at_path_no_policy", DP3_WITH),
    Point(
        "S5",
        "P3, AT path as both",
        "DP3S_eu_cap_at_path_no_policy",
        "DP3S_eu_cap_at_path_with_policy",
    ),
    Point("S5", "cap, no policy", "DP3S_eu_cap_at_path_no_policy", DP3_NO),
    Point("S5", "cap, with policy", "DP3S_eu_cap_at_path_with_policy", DP3_WITH),
)
FAMILIES: dict[str, str] = {
    "S1": "KLIEN ambition (P1)",
    "S2": "DP3 split into targets and embedding (P3)",
    "S3": "H2 import price (P3)",
    "S4": "transmission extension limits (P3)",
    "S5": "general emission cap set to the AT path (P3)",
}

# unit of each metric group of :func:`headline`
UNITS: dict[str, str] = {
    "CO2": "Mt",
    "CO2 price": "EUR/t",
    "cost": "bn EUR",
    "net import": "TWh",
    "capacity": "GW",
    "production": "TWh",
    "cross-border capacity": "GW",
}


def runs() -> list[str]:
    """Return every run a sensitivity evaluation needs: sensitivities and references."""
    needed = [*SENSITIVITY_DIFFERENCES]
    needed += [p.run for p in POINTS] + [p.reference for p in POINTS]
    return list(dict.fromkeys(needed))


# --- setup and checks ----------------------------------------------------------


def solve_status(
    files: Mapping[str, Mapping[str, object]],
    scenarios: list[str],
    horizons: list[str],
    causes: Mapping[tuple[str, str], str] | None = None,
) -> pd.DataFrame:
    """
    Return the outcome of every run and horizon.

    Parameters
    ----------
    files
        Network file per horizon per scenario, see ``find_scenarios``.
    scenarios
        Runs to report.
    horizons
        Planning horizons of the runs.
    causes
        Documented causes of unsolved horizons, :data:`DOCUMENTED_CAUSES` if
        missing.

    Returns
    -------
    :
        ``solved``; ``not solved`` (with the documented cause, if any) for the
        first horizon without a network; ``not reached`` for the later ones,
        which a myopic run cannot solve. Indexed by scenario, horizon columns.
    """
    causes = DOCUMENTED_CAUSES if causes is None else causes
    rows = {}
    for scenario in scenarios:
        solved = files.get(scenario, {})
        row, failed = {}, False
        for horizon in horizons:
            if horizon in solved and not failed:
                row[horizon] = "solved"
            elif failed:
                row[horizon] = "not reached"
            else:
                failed = True
                cause = causes.get((scenario, horizon))
                row[horizon] = f"not solved: {cause}" if cause else "not solved"
        rows[scenario] = row
    table = pd.DataFrame.from_dict(rows, orient="index", columns=horizons)
    table.index.name = "scenario"
    return table


def config_check(files: Mapping[str, Mapping[str, Path]]) -> Check:
    """
    Check that each sensitivity run differs from its reference in its choice only.

    Parameters
    ----------
    files
        Network file per horizon per scenario, see ``find_scenarios``.

    Returns
    -------
    :
        ``fail`` if a run differs in other keys than expected, ``warn`` if a
        reference is not solved.
    """
    rows = []
    for scenario, expected in SENSITIVITY_DIFFERENCES.items():
        if scenario not in files:
            continue
        reference = SENSITIVITY_REFERENCES[scenario]
        if reference not in files:
            rows.append(
                {
                    "scenario": scenario,
                    "reference": reference,
                    "unexpected": "",
                    "missing": "",
                    "note": "reference not solved",
                }
            )
            continue
        meta = read_meta(next(iter(files[scenario].values())))
        ref_meta = read_meta(next(iter(files[reference].values())))
        found = config_diff(meta, ref_meta, expected)
        rows.append(
            {
                "scenario": scenario,
                "reference": reference,
                "unexpected": ", ".join(sorted(found - expected)),
                "missing": ", ".join(sorted(expected - found)),
                "note": "",
            }
        )
    if not rows:
        return Check("Config diff", "warn", "no sensitivity run solved")
    diff = pd.DataFrame(rows).set_index("scenario")
    bad = diff[(diff.unexpected != "") | (diff.missing != "")]
    unchecked = diff[diff.note != ""]
    if len(bad):
        status = "fail"
        message = f"{len(bad)} runs differ from their reference in other keys"
    elif len(unchecked):
        status = "warn"
        message = f"{len(unchecked)} runs without a solved reference"
    else:
        status = "ok"
        message = "every run differs from its reference only in its choice"
    return Check("Config diff", status, message, diff)


# --- cross-border branches (S4) --------------------------------------------------


def _cross_border_branches(n: pypsa.Network, country: str) -> pd.DataFrame:
    """Return the AC lines and DC links of a network, flagged when they cross a border."""
    countries = bus_locations(n).str[:2]
    frames = []
    for component, static, attr in [
        ("Line", n.lines, "s_nom"),
        ("Link", n.links[n.links.carrier == "DC"], "p_nom"),
    ]:
        c0 = static.bus0.map(countries)
        c1 = static.bus1.map(countries)
        frames.append(
            pd.DataFrame(
                {
                    "component": component,
                    "name": static.index,
                    "extendable": static[f"{attr}_extendable"].to_numpy(),
                    "cross-border": (
                        (c0 != c1) & ((c0 == country) | (c1 == country))
                    ).to_numpy(),
                    "max": static[f"{attr}_max"].to_numpy(),
                    "opt": static[f"{attr}_opt"].to_numpy(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def cross_border_capacity(n: pypsa.Network, country: str) -> pd.Series:
    """
    Return the capacity of the country's cross-border AC lines and DC links in GW.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        ``AC`` and ``DC`` (``s_nom_opt`` / ``p_nom_opt``).
    """
    branches = _cross_border_branches(n, country)
    crossing = branches[branches["cross-border"]]
    capacity = crossing.groupby("component").opt.sum() / GW
    return capacity.rename({"Line": "AC", "Link": "DC"}).reindex(
        ["AC", "DC"], fill_value=0.0
    )


def bound_changes(n: pypsa.Network, reference: pypsa.Network, country: str) -> Check:
    """
    Check that only the cross-border lines and links of the country changed bounds.

    Compares ``s_nom_max`` / ``p_nom_max`` of the extendable AC lines and DC
    links of an S4 run with those of its reference, horizon by horizon.

    Parameters
    ----------
    n
        A solved S4 network.
    reference
        The solved network of the reference run, same horizon.
    country
        Country code.

    Returns
    -------
    :
        ``fail`` if another branch changed or no cross-border branch did.
    """
    run = _cross_border_branches(n, country).set_index(["component", "name"])
    ref = _cross_border_branches(reference, country).set_index(["component", "name"])
    both = run.join(ref["max"].rename("reference max"), how="inner")
    both = both[both.extendable]
    both["changed"] = ~np.isclose(both["max"], both["reference max"])
    changed = both.changed
    wrong = both[changed & ~both["cross-border"]]
    unchanged = both[~changed & both["cross-border"]]
    details = both[changed | both["cross-border"]]
    if len(wrong):
        return Check(
            "S4 bounds",
            "fail",
            f"{len(wrong)} branches outside the {country} borders changed bounds",
            details,
        )
    if len(unchanged):
        return Check(
            "S4 bounds",
            "fail",
            f"{len(unchanged)} {country} cross-border branches kept their bounds",
            details,
        )
    return Check(
        "S4 bounds",
        "ok",
        f"only the {int(changed.sum())} {country} cross-border branches changed",
        details,
    )


# --- headline metrics -------------------------------------------------------------


def headline(n: pypsa.Network, country: str) -> pd.Series:
    """
    Return the headline metrics of one network.

    Parameters
    ----------
    n
        A solved network.
    country
        Country code.

    Returns
    -------
    :
        Values indexed by ``group`` (see :data:`UNITS`) and ``metric``:
        national CO2 (``total``, ``budget`` and one row per category of
        ``national_co2_categories``, which include the claim categories),
        CO2 prices (national budget and ``CO2Limit-upper``), cost in the
        country (``country_cost``), net import per energy carrier, capacity
        and production per KLIEN carrier group (ror included) and the
        cross-border capacity.
    """
    flows = port_flows(n)
    co2 = national_co2_categories(n, country, flows) / MT
    co2 = pd.concat(
        [
            pd.Series({"total": co2.sum(), "budget": national_budget(n, country) / MT}),
            co2,
        ]
    )
    price = pd.Series(
        {
            "national": co2_price(n, f"co2_limit-{country}"),
            "EU": co2_price(n, EU_CO2_LIMIT),
        }
    )
    cost = country_cost(n, country, flows) / BN
    imports = energy_supply(n, country)["net import"]
    potential = potential_summary({"": {"": n}}, country).droplevel(
        ["scenario", "horizon"]
    )
    parts = {
        "CO2": co2,
        "CO2 price": price,
        "cost": cost,
        "net import": imports,
        "capacity": potential.capacity,
        "production": potential.production,
        "cross-border capacity": cross_border_capacity(n, country),
    }
    out = pd.concat(parts, names=["group", "metric"]).astype(float)
    return out


def headlines(networks: Networks, country: str) -> pd.DataFrame:
    """
    Return :func:`headline` for every run and horizon.

    Returns
    -------
    :
        Column ``value``, indexed by ``scenario``, ``horizon``, ``group`` and
        ``metric``.
    """
    frames = {
        (scenario, horizon): headline(n, country)
        for scenario, horizons in networks.items()
        for horizon, n in horizons.items()
    }
    if not frames:
        return pd.DataFrame(
            columns=["value"],
            index=pd.MultiIndex.from_tuples(
                [], names=["scenario", "horizon", "group", "metric"]
            ),
        )
    table = pd.concat(frames, names=["scenario", "horizon"])
    return table.to_frame("value")


# --- effects -------------------------------------------------------------------


def effects(
    table: pd.DataFrame, points: tuple[Point, ...] | list[Point] = POINTS
) -> pd.DataFrame:
    """
    Return the effect at every sensitivity point: run minus reference.

    Only horizons solved in both runs are compared; points with a run that is
    not in ``table`` are left out.

    Parameters
    ----------
    table
        Output of :func:`headlines`.
    points
        The points to compare.

    Returns
    -------
    :
        Columns ``run``, ``reference`` (values of both) and ``effect``,
        indexed by ``family``, ``point``, ``horizon``, ``group`` and
        ``metric``.
    """
    values = table["value"]
    scenarios = set(values.index.unique("scenario"))
    frames = {}
    for p in points:
        if p.run not in scenarios or p.reference not in scenarios:
            continue
        run = values.xs(p.run, level="scenario")
        ref = values.xs(p.reference, level="scenario")
        # only horizons of both runs; a metric missing in one run stays NaN
        common = run.index.unique("horizon").intersection(ref.index.unique("horizon"))
        both = pd.concat({"run": run, "reference": ref}, axis=1)
        both = both[both.index.get_level_values("horizon").isin(common)]
        both["effect"] = both.run - both.reference
        frames[(p.family, p.point)] = both
    if not frames:
        index = pd.MultiIndex.from_tuples(
            [], names=["family", "point", "horizon", "group", "metric"]
        )
        return pd.DataFrame(columns=["run", "reference", "effect"], index=index)
    return pd.concat(frames, names=["family", "point"])


def interaction(effect: pd.DataFrame) -> pd.DataFrame:
    """
    Split the full P3 effect into targets, embedding and their interaction (S2).

    Parameters
    ----------
    effect
        Output of :func:`effects`.

    Returns
    -------
    :
        Columns ``targets``, ``embedding``, ``full`` and ``interaction``
        (``full - (targets + embedding)``), indexed by ``horizon``, ``group``
        and ``metric``; only rows where all three effects exist.
    """
    columns = ["targets", "embedding", "full"]
    if "S2" not in effect.index.unique("family"):
        index = pd.MultiIndex.from_tuples([], names=["horizon", "group", "metric"])
        return pd.DataFrame(columns=[*columns, "interaction"], index=index)
    s2 = effect.xs("S2", level="family").effect.unstack("point")
    s2 = s2.reindex(columns=columns).dropna()
    s2["interaction"] = s2.full - (s2.targets + s2.embedding)
    return s2


def effect_matrix(effect: pd.DataFrame, family: str, group: str) -> pd.DataFrame:
    """
    Return the effects of one family and metric group as metric × (point, horizon).

    Points keep the order of :data:`POINTS`.
    """
    if family not in effect.index.unique("family"):
        return pd.DataFrame()
    rows = effect.xs((family, group), level=["family", "group"]).effect
    order = [p.point for p in POINTS if p.family == family]
    matrix = rows.unstack(["point", "horizon"])
    points = [p for p in order if p in matrix.columns.unique("point")]
    return matrix.reindex(columns=points, level="point")
