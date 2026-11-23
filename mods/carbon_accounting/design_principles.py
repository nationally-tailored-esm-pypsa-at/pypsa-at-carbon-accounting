# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Switches for the design-principle effect runs.

See ``docs-ca/explanations/design-principle-effects-spec.md``. The switches
turn off PyPSA-AT features that have no ``enable`` toggle of their own.
"""


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
