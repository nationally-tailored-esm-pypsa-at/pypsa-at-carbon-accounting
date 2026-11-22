# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Guard the soft fork: carbon accounting changes stay in CA-owned paths (#7).

Compares the working tree with its merge base with PyPSA-AT. Every changed
file must be CA-owned or a hooked file, and every change in a hooked file
must lie inside a fenced carbon accounting block. See ``CLAUDE.CA.md``.

Needs the PyPSA-AT ref ``upstream/main`` (override with ``CA_UPSTREAM_REF``):

    git remote add upstream https://github.com/AGGM-AG/pypsa-at.git
    git fetch upstream main
"""

import os
import re
import subprocess
from collections import Counter
from functools import cache

import pytest

UPSTREAM_REF = os.environ.get("CA_UPSTREAM_REF", "upstream/main")

CA_OWNED = (
    "mods/carbon_accounting/",
    "evals/carbon_accounting/",
    "test/test_carbon_accounting/",
    "docs-ca/",
    "config/config.ca.yaml",
    "config/plotting.ca.yaml",
    "config/config.carbon-accounting.yaml",
    "config/scenarios.carbon-accounting.yaml",
    "CHANGELOG.CA.md",
    "CLAUDE.CA.md",
    ".github/workflows/ca-fork-guard.yaml",
)

# AT-owned files that may differ from PyPSA-AT inside fenced blocks only;
# keep in line with the hook table in CLAUDE.CA.md
HOOKED = (
    "Snakefile",
    "mods/network/common.py",
    "scripts/pypsa-at/additional_functionality.py",
    "evals/views/__init__.py",
    "evals/views/balances.py",
    "evals/constants.py",
    "evals/config.default.toml",
    "CLAUDE.md",
    ".github/pull_request_template.md",
)

# PyPSA-AT lines that a fenced hook replaces, per hooked file (stripped). Any
# other PyPSA-AT line that a hooked file drops or changes fails the guard.
REPLACED = {
    "mods/network/common.py": ("apply_onwind_brownfield(n, snakemake)",),
    "scripts/pypsa-at/additional_functionality.py": (
        "constraint_national_co2_budgets(n, snakemake, investment_year)",
    ),
    "evals/views/balances.py": (
        "mask_carrier = (",
        'co2_balance.index.get_level_values(DM.CARRIER) == "kerosene for aviation"',
    ),
}

START = "--- START: Block Maintained by Carbon Accounting ---"
END = "--- END: Block Maintained by Carbon Accounting ---"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


@cache
def _merge_base() -> str:
    try:
        return _git("merge-base", "HEAD", UPSTREAM_REF).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"PyPSA-AT ref '{UPSTREAM_REF}' not available")


def _changed_files() -> list[str]:
    # without rename detection, a moved file lists its source path as well
    return _git("diff", "--name-only", "--no-renames", _merge_base()).split()


def is_ca_owned(path: str) -> bool:
    """Return whether a path belongs to the carbon accounting fork."""
    return any(
        path == owned or (owned.endswith("/") and path.startswith(owned))
        for owned in CA_OWNED
    )


def fenced_lines(lines: list[str]) -> set[int]:
    """
    Return the 1-based numbers of the lines inside fenced blocks, fences included.

    Raises
    ------
    ValueError
        If the fences are not balanced.
    """
    fenced, start = set(), None
    for number, line in enumerate(lines, start=1):
        if START in line:
            if start is not None:
                raise ValueError(f"Nested fence at line {number}")
            start = number
        elif END in line:
            if start is None:
                raise ValueError(f"Unopened fence at line {number}")
            fenced.update(range(start, number + 1))
            start = None
    if start is not None:
        raise ValueError(f"Unclosed fence at line {start}")
    return fenced


def unfenced_changes(diff: str, lines: list[str]) -> list[int]:
    """
    Return the line numbers of changes outside fenced blocks.

    Parameters
    ----------
    diff
        Output of ``git diff -U0`` for one file.
    lines
        The current lines of the file.

    Returns
    -------
    :
        Added lines outside a fence. Blank lines added right next to a fence
        are allowed (formatters insert them). Deleted lines are checked by
        :func:`removed_lines`.
    """
    fenced = fenced_lines(lines)
    outside = []
    for line in diff.splitlines():
        match = HUNK.match(line)
        if not match:
            continue
        first, count = int(match[1]), int(match[2] or 1)
        for number in range(first, first + count):
            if number in fenced:
                continue
            blank = not lines[number - 1].strip()
            if blank and {number - 1, number + 1} & fenced:
                continue
            outside.append(number)
    return outside


def removed_lines(diff: str, replaced: tuple[str, ...] = ()) -> list[str]:
    """
    Return the PyPSA-AT lines that a diff drops or changes, apart from ``replaced``.

    Parameters
    ----------
    diff
        Output of ``git diff -U0`` for one file.
    replaced
        Stripped PyPSA-AT lines that a fenced hook may replace.

    Returns
    -------
    :
        Stripped removed lines that are not blank and not in ``replaced``.
    """
    removed = Counter(
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---") and line[1:].strip()
    )
    return sorted((removed - Counter(replaced)).elements())


def test_only_ca_owned_or_hooked_files_differ_from_pypsa_at():
    unexpected = [
        path
        for path in _changed_files()
        if not is_ca_owned(path) and path not in HOOKED
    ]
    assert not unexpected, (
        f"Files differ from PyPSA-AT ({UPSTREAM_REF}) outside CA-owned paths: "
        f"{unexpected}. Move the change to a CA-owned path, or add a fenced hook "
        "and list the file in HOOKED and CLAUDE.CA.md."
    )


@pytest.mark.parametrize("path", HOOKED)
def test_hooked_files_change_only_inside_fences(path):
    if path not in _changed_files():
        pytest.skip(f"{path} is identical to PyPSA-AT")
    summary = _git("diff", "--summary", "--numstat", _merge_base(), "--", path)
    assert "mode change" not in summary, f"{path} changes its file mode"
    assert not summary.startswith("-\t-\t"), f"{path} has a binary change"
    diff = _git("diff", "-U0", _merge_base(), "--", path)
    with open(path) as f:
        lines = f.read().splitlines()
    assert not unfenced_changes(diff, lines), (
        f"{path} changes PyPSA-AT outside fenced carbon accounting blocks at lines "
        f"{unfenced_changes(diff, lines)}"
    )
    assert not removed_lines(diff, REPLACED.get(path, ())), (
        f"{path} drops or changes PyPSA-AT lines {removed_lines(diff)}. Keep them, or "
        "replace them in a fenced hook and list them in REPLACED."
    )


class TestUnfencedChanges:
    """Unit tests of the fence check, independent of git."""

    LINES = ["a", f"# {START}", "hook", f"# {END}", "", "b"]

    def test_fenced_lines(self):
        assert fenced_lines(self.LINES) == {2, 3, 4}

    def test_unbalanced_fence_raises(self):
        with pytest.raises(ValueError):
            fenced_lines(["a", f"# {START}"])

    def test_change_inside_fence_passes(self):
        assert unfenced_changes("@@ -1,0 +2,3 @@", self.LINES) == []

    def test_blank_line_next_to_fence_passes(self):
        assert unfenced_changes("@@ -1,0 +5 @@", self.LINES) == []

    def test_change_outside_fence_fails(self):
        assert unfenced_changes("@@ -6 +6 @@", self.LINES) == [6]

    def test_removed_line_fails(self):
        diff = "@@ -7 +5,0 @@\n-c"
        assert removed_lines(diff) == ["c"]

    def test_line_removed_next_to_fence_fails(self):
        # a fence added next to a deletion does not cover it
        diff = f"@@ -2 +2,3 @@\n-old\n+# {START}\n+hook\n+# {END}"
        assert unfenced_changes(diff, self.LINES) == []
        assert removed_lines(diff) == ["old"]

    def test_replaced_line_passes(self):
        diff = f"@@ -2 +2,3 @@\n-    old()\n+# {START}\n+hook\n+# {END}"
        assert removed_lines(diff, ("old()",)) == []

    def test_removed_blank_line_passes(self):
        assert removed_lines("@@ -3 +2,0 @@\n-") == []

    @pytest.mark.parametrize(
        "path, owned",
        [
            ("mods/carbon_accounting/network.py", True),
            ("config/config.ca.yaml", True),
            ("mods/constraints/co2_budget.py", False),
            ("mods/carbon_accounting.py", False),
        ],
    )
    def test_is_ca_owned(self, path, owned):
        assert is_ca_owned(path) is owned
