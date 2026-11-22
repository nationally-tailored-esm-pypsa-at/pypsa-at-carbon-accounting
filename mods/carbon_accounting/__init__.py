# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Carbon accounting: switchable accounting method for national CO2 budgets.

Owned by the carbon accounting fork. PyPSA-AT files only call the
orchestrators re-exported here, inside fenced hook blocks.
"""

from mods.carbon_accounting.budget import (
    carbon_accounting_enabled,
    constraint_national_co2_budgets_ca,
)
from mods.carbon_accounting.constraints import constraint_carbon_accounting
from mods.carbon_accounting.network import apply_carbon_accounting

__all__ = [
    "apply_carbon_accounting",
    "carbon_accounting_enabled",
    "constraint_carbon_accounting",
    "constraint_national_co2_budgets_ca",
]
