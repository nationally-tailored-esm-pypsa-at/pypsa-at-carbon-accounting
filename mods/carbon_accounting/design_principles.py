# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Switches for the design-principle effect and sensitivity runs.

See ``docs-ca/explanations/design-principle-effects-spec.md`` and
``docs-ca/explanations/design-principle-sensitivities-spec.md``. The switches
turn off or change PyPSA-AT features that have no config key of their own.
"""

from logging import getLogger

import numpy as np
import pandas as pd
import pypsa
from snakemake.script import Snakemake

# the pairing of gas pipelines and retrofit candidates must match the one of
# check_retrofit_pairing exactly, so the helper is reused, not mirrored
from mods.network.gas import _gas_pipeline_legs

logger = getLogger(__name__)

# MW below the minimum capacity that still count as rounding of ``s_nom_opt``
BOUND_TOLERANCE = 1e-3


def onwind_brownfield_enabled(config: dict) -> bool:
    """
    Return whether the KLIEN onshore-wind brownfield replaces PyPSA-Eur's.

    Off in the run ``DP1_no_national_data`` (principle P1): the existing
    onshore-wind capacities of PyPSA-Eur stay in Austria.

    Parameters
    ----------
    config
        The workflow configuration.

    Returns
    -------
    :
        The value of ``mods.carbon_accounting.onwind_brownfield.enable``.
    """
    return bool(config["mods"]["carbon_accounting"]["onwind_brownfield"]["enable"])


def cross_border(
    n: pypsa.Network, bus0: pd.Series, bus1: pd.Series, countries: list[str]
) -> pd.Series:
    """
    Return whether each branch connects two countries, one of them in ``countries``.

    Parameters
    ----------
    n
        The network, with ``n.buses.country``.
    bus0, bus1
        The bus columns of the branches.
    countries
        Country codes.

    Returns
    -------
    :
        A boolean Series on the index of ``bus0``.
    """
    country0 = bus0.map(n.buses.country)
    country1 = bus1.map(n.buses.country)
    listed = country0.isin(countries) | country1.isin(countries)
    return listed & (country0 != country1)


def _limit(
    static: pd.DataFrame,
    index: pd.Index,
    attr: str,
    upstream: float | None,
    extension: float,
) -> None:
    """
    Set ``{attr}_max`` of the branches to the upstream basis plus ``extension``.

    ``prepare_network.py`` sets ``{attr}_max = {attr} + upstream`` before the
    brownfield of a myopic run moves ``s_nom`` to the previous ``s_nom_opt``.
    The basis is therefore ``{attr}_max - upstream``, the capacity of the base
    network in every horizon. Branches whose bound lies below ``upstream``
    got it from another step (e.g. ``p_nom_max = 0`` for DC projects that
    cannot be built yet) and keep it.
    """
    if upstream is None or not np.isfinite(upstream) or upstream <= 0:
        raise ValueError(
            f"Cross-border extension limits need the upstream {attr}_max_extension "
            f"as basis, but it is {upstream}."
        )
    current = static.loc[index, f"{attr}_max"]
    kept = current < upstream - BOUND_TOLERANCE
    if kept.any():
        logger.info(
            f"Kept the {attr}_max of {kept.sum()} branches set below the upstream "
            f"extension: {', '.join(kept.index[kept])}."
        )
    index = index[~kept.to_numpy()]
    bound = static.loc[index, f"{attr}_max"] - upstream + extension
    minimum = static.loc[index, f"{attr}_min"]
    below = bound < minimum - BOUND_TOLERANCE
    if below.any():
        raise ValueError(
            f"The {attr}_max_extension of {extension} MW lies below {attr}_min of "
            f"{', '.join(below.index[below])}."
        )
    static.loc[index, f"{attr}_max"] = bound.clip(lower=minimum)


def apply_cross_border_extension_limits(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Limit the extension of the cross-border AC lines and DC links of some countries.

    Used by the design-principle sensitivity S4: the upstream keys
    ``lines.s_nom_max_extension`` and ``links.p_nom_max_extension`` apply to
    every AC line and DC link, these limits only to the extendable branches
    between two countries of which one is in ``countries``. The limits replace
    the upstream ones on the same basis, see :func:`_limit`.

    Parameters
    ----------
    n
        The network, after the brownfield.
    snakemake
        The Snakemake object, for ``mods.carbon_accounting.cross_border_extension_limits``,
        ``lines`` and ``links``.

    Raises
    ------
    ValueError
        If a new bound lies below the minimum capacity of a branch, or the
        upstream extension limit is not set.
    """
    config = snakemake.config
    limits = config["mods"]["carbon_accounting"]["cross_border_extension_limits"]
    lines_max = limits["s_nom_max_extension"]
    links_max = limits["p_nom_max_extension"]
    if not limits["enable"] or (lines_max is None and links_max is None):
        return
    countries = limits["countries"]

    if lines_max is not None:
        lines = n.lines[n.lines.s_nom_extendable]
        index = lines.index[cross_border(n, lines.bus0, lines.bus1, countries)]
        upstream = config["lines"]["s_nom_max_extension"]
        _limit(n.lines, index, "s_nom", upstream, lines_max)
        logger.info(
            f"Limited the extension of {len(index)} cross-border AC lines of "
            f"{', '.join(countries)} to {lines_max} MW."
        )
    if links_max is not None:
        links = n.links[(n.links.carrier == "DC") & n.links.p_nom_extendable]
        index = links.index[cross_border(n, links.bus0, links.bus1, countries)]
        upstream = config["links"]["p_nom_max_extension"]
        _limit(n.links, index, "p_nom", upstream, links_max)
        logger.info(
            f"Limited the extension of {len(index)} cross-border DC links of "
            f"{', '.join(countries)} to {links_max} MW."
        )


def fix_unpaired_gas_pipelines(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Fix the gas pipelines without a retrofit candidate after the gas grid threshold year.

    Up to ``mods.threshold_year_for_gas_grid_expansion``,
    ``fix_gas_grid_capacity`` (``mods/network/gas.py``) fixes every gas
    pipeline without an extendable ``H2 pipeline retrofitted`` candidate,
    because the upstream retrofit constraint pairs both by position. After the
    threshold year it does nothing. PyPSA-DE keeps the DE-internal retrofit
    candidates non-extendable up to 2030 (Kernnetz assumption), so a threshold
    year before 2030 (``DP3_no_national_policy`` and the sensitivity runs
    based on it) leaves these pipelines extendable without a candidate, and
    ``check_retrofit_pairing`` stops the compose. This function treats them as
    ``fix_gas_grid_capacity`` does before the threshold year: fixed at their
    capacity.

    Parameters
    ----------
    n
        The pre-network, after the gas pipeline modifications of PyPSA-AT.
    snakemake
        The Snakemake object, for ``mods`` and the ``horizon`` wildcard.
    """
    mods = snakemake.config["mods"]
    if not mods.get("modify_brownfield_gas_network_AT"):
        return
    horizon = int(snakemake.wildcards.horizon)
    # up to the threshold year, fix_gas_grid_capacity does this itself
    if horizon <= int(mods["threshold_year_for_gas_grid_expansion"]):
        return
    links = n.links
    candidates = links.index[
        (links.carrier == "H2 pipeline retrofitted") & links.p_nom_extendable
    ]
    # without candidates, the retrofit constraint pairs nothing
    if candidates.empty:
        return
    unpaired = (
        (links.carrier == "gas pipeline")
        & links.p_nom_extendable
        & ~links.index.isin(_gas_pipeline_legs(candidates))
    )
    if not unpaired.any():
        return
    n.links.loc[unpaired, "p_nom_extendable"] = False
    logger.info(
        f"Fixed {unpaired.sum()} gas pipeline(s) without an extendable retrofit "
        f"candidate in {horizon}, after the gas grid threshold year: "
        f"{', '.join(links.index[unpaired])}."
    )
