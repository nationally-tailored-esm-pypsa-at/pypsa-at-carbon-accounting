# PyPSA-AT Carbon Accounting

This repository is a soft fork of [PyPSA-AT](https://pypsa-at.readthedocs.io). It adds a
switchable carbon accounting method for the national CO2 budgets, the EU-wide CO2 limit and
the reported emissions: the technology-based method of PyPSA-AT (default) and a
carrier-based method, under which green gas, oil and methanol book zero and the consuming
country claims their green certificates.

These pages document only what the fork adds. Everything else (installation, the
workflow, the other model modifications and evaluations) is in the
[PyPSA-AT documentation](https://pypsa-at.readthedocs.io).

- [Carbon Accounting Methods](explanations/carbon-accounting-methods.md): what the two
  methods do, with an example
- [Carbon Accounting Configuration](how-to-guides/carbon-accounting-config.md): run the
  reduced configuration that compares the methods
- [Specification](explanations/carbon-accounting-spec.md) and
  [Evaluation Specification](explanations/carbon-accounting-eval-spec.md)

The pages are plain Markdown and are not rendered into a docs site; the API is
documented in the docstrings of `mods/carbon_accounting/` and `evals/carbon_accounting/`.

## Where the code lives

| Path | Content |
|---|---|
| `mods/carbon_accounting/` | network transformation, constraints, national CO2 budget, constants |
| `evals/carbon_accounting/` | evaluations, the claims view, notebooks and scripts |
| `test/test_carbon_accounting/` | all carbon accounting tests |
| `config/config.ca.yaml`, `config/plotting.ca.yaml` | defaults and tech colours |
| `docs-ca/` | these pages (Markdown only) |

PyPSA-AT files call into these packages only from fenced
`Block Maintained by Carbon Accounting` hooks.
