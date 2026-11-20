# CLAUDE.CA.md — Carbon Accounting Fork

This repository is a **soft fork of PyPSA-AT** (`upstream` = `AGGM-AG/pypsa-at`). It adds a
switchable carbon accounting method (`mods.carbon_accounting`). The carbon accounting (CA)
is **never upstreamed**: it stays in this fork for good (Issue #7). Everything in
`CLAUDE.md` applies, except where this file says otherwise. This file wins for CA work.

## Path ownership

Every path is either **CA-owned** (edit freely; PyPSA-AT never touches it) or **AT-owned**
(identical to `upstream/main`, apart from fenced hook blocks).

| CA-owned path | Content |
|---|---|
| `mods/carbon_accounting/` | network transformation, constraints, national CO2 budget, constants; orchestrators re-exported from its `__init__.py` |
| `evals/carbon_accounting/` | computations (`accounting.py`, `pathways.py`), eval helpers (`utils.py`), the `view_balance_carbon_claims` view, `notebooks/`, `scripts/` |
| `test/test_carbon_accounting/` | all CA tests, mirroring the two packages above, own `conftest.py` |
| `config/config.ca.yaml`, `config/plotting.ca.yaml` | CA defaults and tech colours, loaded after the PyPSA-AT config |
| `config/config.carbon-accounting.yaml`, `config/scenarios.carbon-accounting.yaml` | reduced comparison runs (`--configfile` overlay) |
| `docs-ca/` | specs, explanations, how-to guides; plain Markdown, not rendered |
| `CHANGELOG.CA.md`, `CLAUDE.CA.md` | changelog and rules of this fork |
| `.github/workflows/ca-fork-guard.yaml` | CI: fork guard and weekly merge check against PyPSA-AT |

Everything else is AT-owned. Do not edit AT logic in place. When CA needs to change
AT behaviour, add CA code in a CA-owned path and call it from a hook. Example: the CA
national budget (`mods/carbon_accounting/budget.py`) replaces
`mods/constraints/co2_budget.py`, which stays identical to PyPSA-AT.

## Hooks in AT-owned files

AT-owned files may differ from `upstream/main` only inside fenced blocks. Keep hooks
one-liners where possible, and explain why in the block:

```python
# --- START: Block Maintained by Carbon Accounting ---
# why the hook is needed
...
# --- END: Block Maintained by Carbon Accounting ---
```

Use the comment syntax of the file (`#` in Python, YAML, TOML and Snakemake,
`<!-- ... -->` in Markdown). Put import hooks where isort would sort them, so that ruff
leaves them in place. The current hooks:

| File | Hook |
|---|---|
| `Snakefile` | `configfile:` for `config/config.ca.yaml` and `config/plotting.ca.yaml` |
| `mods/network/common.py` | `apply_carbon_accounting` as the last network change in `modify_prenetwork` |
| `scripts/pypsa-at/additional_functionality.py` | CA national budget instead of the AT one when `mods.carbon_accounting.enable`; `constraint_carbon_accounting` |
| `evals/views/__init__.py` | registers `view_balance_carbon_claims` |
| `evals/views/balances.py` | scales green kerosene claims with the domestic aviation share in `view_balance_carbon` |
| `evals/constants.py` | colours of the claim categories |
| `evals/config.default.toml` | claim categories and the `view_balance_carbon_claims` section (the evals read one override file only) |
| `CLAUDE.md` | imports this file |
| `.github/pull_request_template.md` | changelog and docs item for CA changes |

A new hook needs a reason why no CA-owned path can do the job. Add it to this table and
to `HOOKED` in `test/test_carbon_accounting/test_fork_guard.py`; a new CA-owned path goes
to `CA_OWNED` there.

## Guards

- `test/test_carbon_accounting/test_fork_guard.py` fails when a file outside the CA-owned
  paths differs from PyPSA-AT (merge base with `upstream/main`) without being listed as
  hooked, or when a hooked file changes outside a fenced block. It skips without the
  `upstream/main` ref; run it locally after `git fetch upstream`.
- `.github/workflows/ca-fork-guard.yaml` runs the guard on every PR and push to `main`,
  and every Monday checks with `git merge-tree` that `main` still merges `upstream/main`
  without conflicts. A failing merge check means: open a sync PR now.

## Rules that differ from CLAUDE.md

- **Changelog:** CA changes go to `CHANGELOG.CA.md`. `CHANGELOG.AT.md` stays identical to
  PyPSA-AT.
- **Orchestrators:** re-export CA orchestrators from `mods/carbon_accounting/__init__.py` and
  import them from `mods.carbon_accounting` in hooks. `mods/__init__.py` stays untouched.
- **Config:** new CA keys go to `config/config.ca.yaml` under `mods.carbon_accounting`, with
  `enable` as the first key. Never add CA keys to `config/config.at.yaml`.
- **Tests:** CA tests go to `test/test_carbon_accounting/` (`test_mods/`, `test_evals/`).
- **Docs:** CA docs go to `docs-ca/` as plain Markdown (GitHub alerts, relative links).
  Do not add CA pages to `docs-at/` or `mkdocs.yml`.
- **Evals:** `evals/carbon_accounting/` mirrors the CA carrier lists of
  `mods/carbon_accounting/constants.py` instead of importing `mods`; a test checks the
  mirror.
- **Failing evals in CA runs are expected.** `export_evaluation_pypsa_at` and
  `validate_pypsa_at` may fail for the `CA_*` scenarios; that is not a CA bug.

## Branches and upstream sync

`main` is the fork. There is no mirror branch and no rebasing. PyPSA-AT updates come in
through a sync PR:

```bash
git fetch upstream
git switch -c chore/sync-upstream-$(date +%F) origin/main
git merge upstream/main          # conflicts only inside fenced hooks, if any
pixi run pytest test/test_carbon_accounting   # drift test and fork guard
```

Then add an entry to `CHANGELOG.CA.md` naming the synced upstream commit, and open the PR.
A failing drift test (`test_mods/test_budget.py::TestDriftAgainstPyPSAAT`) means PyPSA-AT
changed its national CO2 budget: port the change to
`mods/carbon_accounting/budget.py` in the sync PR.
