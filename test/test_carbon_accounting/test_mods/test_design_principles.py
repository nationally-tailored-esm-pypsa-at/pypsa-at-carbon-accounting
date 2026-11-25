# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests of the design-principle switches (mods/carbon_accounting/design_principles.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import mods.network.common as common
from mods.carbon_accounting import onwind_brownfield_enabled


@pytest.mark.parametrize("enable", [True, False])
def test_onwind_brownfield_enabled(enable):
    config = {"mods": {"carbon_accounting": {"onwind_brownfield": {"enable": enable}}}}
    assert onwind_brownfield_enabled(config) is enable


@pytest.mark.parametrize("enable", [True, False])
def test_modify_prenetwork_skips_onwind_brownfield(monkeypatch, enable):
    """The hook in modify_prenetwork calls the KLIEN brownfield only when enabled."""
    calls = []
    for name in dir(common):
        obj = getattr(common, name)
        if (
            callable(obj)
            and getattr(obj, "__module__", "").startswith("mods.")
            and name not in ("modify_prenetwork", "onwind_brownfield_enabled")
        ):
            monkeypatch.setattr(common, name, lambda *a, **k: None)
    monkeypatch.setattr(common, "apply_onwind_brownfield", lambda *a: calls.append(a))
    monkeypatch.setattr("scripts._helpers.load_costs", lambda *a, **k: None)
    snakemake = SimpleNamespace(
        config={
            "mods": {"carbon_accounting": {"onwind_brownfield": {"enable": enable}}}
        },
        input=SimpleNamespace(tech_costs=None),
        wildcards=SimpleNamespace(horizon="2030"),
    )
    common.modify_prenetwork(MagicMock(), snakemake)
    assert bool(calls) is enable
