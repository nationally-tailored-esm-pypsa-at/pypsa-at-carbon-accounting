# PyPSA-AT Carbon Accounting

This repository is a soft fork of [PyPSA-AT](https://pypsa-at.readthedocs.io), i.e. a
copy that adds one feature and regularly takes over all updates of PyPSA-AT. The feature
is a choice of *carbon accounting method*: the rule that decides in which country the
emissions and negative emissions of green fuels (biomethane, bio-oil, e-fuels) count.
The chosen method applies to the national CO2 budgets, the EU-wide CO2 limit and the
reported emissions.

- **Technology-based method** (default, as in PyPSA-AT): the country that produces a green
  fuel gets a negative emission, and the country that burns it gets the full emission, as
  if the fuel were fossil.
- **Carrier-based method**: a green fuel counts as zero emission. The country that
  consumes it can claim its green certificate and so lowers its own emissions.

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

## For developers: where the code lives

You need this section only if you change the model code. All code of the carbon
accounting sits in its own folders, so that updates of PyPSA-AT can be taken over without
conflicts:

| Path | Content |
|---|---|
| `mods/carbon_accounting/` | network transformation, constraints, national CO2 budget, constants |
| `evals/carbon_accounting/` | evaluations, the claims view, notebooks and scripts |
| `test/test_carbon_accounting/` | all carbon accounting tests |
| `config/config.ca.yaml`, `config/plotting.ca.yaml` | defaults and tech colours |
| `docs-ca/` | these pages (Markdown only) |

Files of PyPSA-AT itself are changed only in a few marked places, which switch the
carbon accounting on. Each of them sits between a `START` and an `END` line reading
`Block Maintained by Carbon Accounting`.
