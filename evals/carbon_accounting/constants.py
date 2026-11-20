# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Constants of the carbon accounting evaluations."""

from frozendict import frozendict

# links whose CO2 is scaled with the domestic aviation share: kerosene and the
# green kerosene claims of the carrier-based carbon accounting method. Mirrors
# mods.carbon_accounting.constants.AVIATION_CARRIERS (evals do not import mods).
AVIATION_CARRIERS: tuple[str, ...] = (
    "kerosene for aviation",
    "renewable oil claim aviation",
)

# claim links of the carrier-based carbon accounting method per fuel bus
# carrier. Mirrors mods.carbon_accounting.constants.CLAIM_CARRIERS.
FUEL_CLAIM_CARRIERS = frozendict(
    {
        "renewable gas claim": "gas",
        "renewable oil claim": "oil",
        "renewable oil claim aviation": "oil",
        "renewable methanol claim": "methanol",
    }
)
