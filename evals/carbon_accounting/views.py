# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Evaluation views of the carbon accounting."""

import logging
from pathlib import Path

import pandas as pd
from pypsa import NetworkCollection

from evals.carbon_accounting.utils import carbon_accounting_claims
from evals.constants import DataModel as DM
from evals.fileio import Exporter
from evals.utils import insert_index_level, rename_aggregate

logger = logging.getLogger(__name__)


def view_balance_carbon_claims(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export the CO2 credits claimed per country (carbon accounting).

    Under the carrier-based carbon accounting method, countries claim green
    fuel credits up to their own consumption. The view shows the claimed
    credits next to a reference: the credit at the EU-average green share of
    each fuel. Skipped for the technology-based method, which has no claims.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Collection of solved networks, indexed by year.
    config
        Configuration dictionary containing the view settings.
    """
    credits = [
        insert_index_level(carbon_accounting_claims(n), year, DM.YEAR)
        for year, n in nc.networks.items()
    ]
    credits = [c for c in credits if not c.empty]
    if not credits:
        logger.info("No carbon accounting claims found, skipping the view.")
        return

    statistic = pd.concat(credits)
    statistic = rename_aggregate(
        statistic, config["view"]["bus_carrier_groups"], level=DM.BUS_CARRIER
    )
    statistic.attrs["unit"] = "t_co2"
    exporter = Exporter(statistics=[statistic], view_config=config["view"])
    exporter.export(result_path, config["global"]["subdir"])
