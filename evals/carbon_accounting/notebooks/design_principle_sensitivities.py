# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Design-principle sensitivity notebook (marimo).

Shows the effect of a design principle at each sensitivity point next to its
base effect. All computations live in
``evals/carbon_accounting/sensitivities.py``; this file only does UI, caching
and plotting. Run it from the repository root with

    pixi run marimo edit evals/carbon_accounting/notebooks/design_principle_sensitivities.py

Specification: ``docs-ca/explanations/design-principle-sensitivities-spec.md``.
"""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="Design-principle sensitivities")


@app.cell
def _():
    import sys
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import plotly.graph_objects as go

    REPO = Path(__file__).resolve().parents[3]
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    from evals.carbon_accounting import accounting as ca
    from evals.carbon_accounting import sensitivities as sens

    return REPO, ca, go, mo, pd, sens


@app.cell
def _(mo):
    # categorical slots in fixed order; a point keeps its colour within a family
    PALETTE = [
        "#2a78d6",
        "#eb6834",
        "#1baf7a",
        "#eda100",
        "#e87ba4",
        "#008300",
        "#6250d6",
        "#e34948",
    ]
    ICONS = {"ok": "✓", "warn": "⚠", "fail": "✗"}
    KINDS = {"ok": "success", "warn": "warn", "fail": "danger"}
    STATUS_COLOURS = {"solved": "#1baf7a", "not reached": "#c3c2b7"}

    def badge(check) -> mo.Html:
        """Return a callout with the status icon, name and message of a check."""
        text = mo.md(f"**{ICONS[check.status]} {check.name}** — {check.message}")
        return mo.callout(text, kind=KINDS[check.status])

    def layout(fig, title: str, yaxis: str):
        fig.update_layout(
            title=title,
            template="plotly_white",
            bargap=0.3,
            legend=dict(orientation="h", y=-0.25),
            hovermode="closest",
            margin=dict(t=60, b=40),
        )
        fig.update_yaxes(title_text=yaxis, zeroline=True, zerolinecolor="#c3c2b7")
        return fig

    def table(frame, digits: int = 3, label: str = ""):
        """Return a rounded, flat marimo table."""
        return mo.ui.table(
            frame.round(digits).reset_index(), selection=None, label=label
        )

    return PALETTE, STATUS_COLOURS, badge, layout, table


@app.cell
def _(mo):
    mo.md(r"""
    # Design-principle sensitivities

    Each sensitivity run differs from its reference run in **one choice**. For each
    headline metric, the notebook shows the effect of the principle at every
    sensitivity point next to its base effect. It sets no robustness threshold.
    Unlike the DP notebook, a missing horizon does not stop the evaluation: effects
    cover the horizons solved in both runs. Specification:
    `docs-ca/explanations/design-principle-sensitivities-spec.md`.
    """)
    return


@app.cell
def _(REPO, mo):
    root_input = mo.ui.text(
        value=str(REPO / "results" / "design-principles"),
        label="Result root",
        full_width=True,
    )
    country_select = mo.ui.dropdown(options=["AT"], value="AT", label="Country")
    mo.hstack([root_input, country_select], justify="start", gap=2)
    return country_select, root_input


@app.cell
def _(ca, mo, root_input, sens):
    files = ca.find_scenarios(root_input.value)
    mo.stop(
        not files,
        mo.callout(
            mo.md(f"✗ No solved networks found in `{root_input.value}`."), kind="danger"
        ),
    )
    _meta = ca.read_meta(next(iter(next(iter(files.values())).values())))
    horizons = [str(h) for h in _meta["planning_horizons"]]
    available = [s for s in sens.runs() if s in files]
    paths = {s: str(next(iter(h.values())).parents[1]) for s, h in files.items()}
    return available, files, horizons, paths


@app.cell(expand_output=True)
def _(STATUS_COLOURS, badge, files, horizons, mo, sens, table_or_empty):
    _status = sens.solve_status(files, sens.runs(), horizons)

    def _colour(value):
        colour = STATUS_COLOURS.get(value, "#e34948")
        return {"backgroundColor": colour, "color": "white"}

    _config = sens.config_check(files)
    mo.vstack(
        [
            mo.md(
                "## 0 Setup and checks\n\n"
                "Outcome per run and horizon. *not solved* is the first horizon "
                "without a network, with its documented cause "
                "(`DOCUMENTED_CAUSES`); a myopic run cannot solve the later "
                "horizons, which are *not reached*."
            ),
            mo.ui.table(
                _status.reset_index(),
                selection=None,
                style_cell=lambda _row, column, value: (
                    _colour(value) if column in horizons else {}
                ),
                label="Solve status",
            ),
            badge(_config),
            mo.accordion(
                {"Config diff against the reference": table_or_empty(_config)}
            ),
        ]
    )
    return


@app.cell
def _(mo):
    def table_or_empty(check):
        if check.details.empty:
            return mo.md("No details.")
        return mo.ui.table(check.details.reset_index(), selection=None)

    return (table_or_empty,)


@app.cell
def _(ca, files, mo, paths):
    def stamp(scenario: str) -> tuple:
        """Return the files of a scenario with size and mtime, the cache key."""
        return tuple(
            (str(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in files[scenario].values()
        )

    @mo.cache
    def load(path: str, state: tuple) -> dict:
        """Load the solved networks of one scenario, once per file state."""
        return ca.load_networks(path)

    def networks(scenario: str) -> dict:
        return load(paths[scenario], stamp(scenario))

    return networks, stamp


@app.cell
def _(mo, networks, sens, stamp):
    @mo.cache
    def cached_headlines(scenario: str, country: str, state: tuple):
        """Return the headline metrics of one scenario, once per file state."""
        return sens.headlines({scenario: networks(scenario)}, country)

    @mo.cache
    def cached_bounds(run: str, reference: str, country: str, states: tuple):
        """Return the S4 bound check per horizon solved in both runs."""
        a, b = networks(run), networks(reference)
        return {
            h: sens.bound_changes(a[h], b[h], country) for h in sorted(a.keys() & b)
        }

    return cached_bounds, cached_headlines


@app.cell(expand_output=True)
def _(
    available,
    badge,
    ca,
    cached_bounds,
    country_select,
    mo,
    pd,
    sens,
    stamp,
):
    _views = []
    for _run in ("DP3S_extension_half", "DP3S_extension_double"):
        _ref = sens.SENSITIVITY_REFERENCES[_run]
        if _run not in available or _ref not in available:
            continue
        _checks = cached_bounds(
            _run, _ref, country_select.value, (stamp(_run), stamp(_ref))
        )
        for _horizon, _check in _checks.items():
            _named = ca.Check(
                f"S4 bounds {_run} {_horizon}", _check.status, _check.message
            )
            _views.append(badge(_named))
        _details = pd.concat(
            {h: c.details for h, c in _checks.items()}, names=["horizon"]
        )
        _views.append(
            mo.accordion(
                {
                    f"{_run}: changed bounds": mo.ui.table(
                        _details.reset_index(), selection=None
                    )
                }
            )
        )
    mo.vstack(
        [
            mo.md(
                "**S4 bounds.** In the S4 runs only the cross-border AC lines and "
                f"DC links of {country_select.value} may have other "
                "`s_nom_max` / `p_nom_max` than in the reference."
            ),
            *(_views or [mo.md("No solved S4 run with its reference.")]),
        ]
    )
    return


@app.cell
def _(available, cached_headlines, country_select, mo, pd, sens, stamp):
    _frames = [
        cached_headlines(s, country_select.value, stamp(s))
        for s in mo.status.progress_bar(
            available, title="Evaluating runs", remove_on_exit=True
        )
    ]
    headlines = pd.concat(_frames)
    effects = sens.effects(headlines)
    return effects, headlines


@app.cell
def _(PALETTE, go, layout, mo, pd, sens, table):
    def family_view(effects, family: str, group: str, intro: str, metrics=None):
        """Return the effect per point of one family and metric group: plot and table."""
        title = f"## {family} {sens.FAMILIES[family]}"
        matrix = sens.effect_matrix(effects, family, group) if group else pd.DataFrame()
        if matrix.empty:
            return mo.vstack([mo.md(f"{title}\n\n{intro}"), mo.md("No solved pair.")])
        if metrics:
            matrix = matrix.loc[[m for m in metrics if m in matrix.index]]
        unit = sens.UNITS[group]
        fig = go.Figure()
        points = list(dict.fromkeys(matrix.columns.get_level_values("point")))
        for i, point in enumerate(points):
            values = matrix[point]
            x = [
                [m for m in values.index for _ in values.columns],
                [h for _ in values.index for h in values.columns],
            ]
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=values.to_numpy().ravel(),
                    name=point,
                    marker_color=PALETTE[i % len(PALETTE)],
                    hovertemplate=f"<b>{point}</b> %{{x}}<br>%{{y:.3g}} {unit}"
                    "<extra></extra>",
                )
            )
        layout(fig, f"Effect on {group} per sensitivity point", unit)
        pairs = "; ".join(
            f"**{p.point}** = `{p.run}` − `{p.reference}`"
            for p in sens.POINTS
            if p.family == family
        )
        return mo.vstack(
            [
                mo.md(f"{title}\n\n{intro}\n\n{pairs}"),
                mo.ui.plotly(fig),
                table(
                    effects.xs((family, group), level=["family", "group"]),
                    label=f"{group} ({unit}): run, reference, effect",
                ),
            ]
        )

    return (family_view,)


@app.cell
def _(effects, mo, sens):
    _groups = (
        sorted(effects.index.unique("group")) if len(effects) else list(sens.UNITS)
    )

    def group_select(value: str):
        return mo.ui.dropdown(
            options=_groups, value=value if value in _groups else None, label="Metrics"
        )

    s1_group = group_select("capacity")
    s2_group = group_select("CO2")
    s3_group = group_select("net import")
    s4_group = group_select("cross-border capacity")
    s5_group = group_select("CO2")
    return s1_group, s2_group, s3_group, s4_group, s5_group


@app.cell(expand_output=True)
def _(effects, family_view, mo, s1_group):
    mo.vstack(
        [
            s1_group,
            family_view(
                effects,
                "S1",
                s1_group.value,
                "P1 effect per KLIEN ambition: each variant minus "
                "`DP1_no_national_data`. Look at *capacity*, *production*, *cost* "
                "and *CO2*. The ambition also sets the KLIEN run-of-river corridor, "
                "so the low and high points contain a ror part (capacity `ror`); "
                "the technical point keeps the medium corridor.",
            ),
        ]
    )
    return


@app.cell(expand_output=True)
def _(effects, family_view, mo, s2_group, sens, table):
    _split = sens.interaction(effects)
    _shown = (
        _split.xs(s2_group.value, level="group")
        if s2_group.value in _split.index.unique("group")
        else _split
    )
    mo.vstack(
        [
            s2_group,
            family_view(
                effects,
                "S2",
                s2_group.value,
                "The target effect, the embedding effect and the full P3 effect, "
                "each against `DP3_with_national_policy`.",
            ),
            mo.md(
                "**Interaction** = full − (targets + embedding). Zero: the two parts "
                "of P3 add up; otherwise removing one changes the effect of the other."
            ),
            table(_shown, label="Targets, embedding, full and interaction"),
        ]
    )
    return


@app.cell(expand_output=True)
def _(effects, family_view, mo, s3_group):
    mo.vstack(
        [
            s3_group,
            family_view(
                effects,
                "S3",
                s3_group.value,
                "P3 effect (run − `DP3_with_national_policy`) at each H2 import "
                "price. The other import prices stay, so derivative imports (NH3, "
                "methanol) may take over part of the change: see *net import* "
                "`hydrogen` and `liquid fuels`.",
            ),
        ]
    )
    return


@app.cell(expand_output=True)
def _(effects, family_view, mo, s4_group):
    mo.vstack(
        [
            s4_group,
            family_view(
                effects,
                "S4",
                s4_group.value,
                "P3 effect (run − `DP3_with_national_policy`) at each extension "
                "limit of the AT cross-border lines and links. *cross-border "
                "capacity* is the added capacity.",
            ),
        ]
    )
    return


@app.cell(expand_output=True)
def _(PALETTE, effects, family_view, go, headlines, layout, mo, s5_group, sens):
    _runs = [
        sens.DP3_WITH,
        sens.DP3_NO,
        "DP3S_eu_cap_at_path_with_policy",
        "DP3S_eu_cap_at_path_no_policy",
    ]
    _co2 = headlines.xs("CO2", level="group").value
    _scenarios = _co2.index.unique("scenario")
    _fig = go.Figure()
    for _i, _run in enumerate(r for r in _runs if r in _scenarios):
        _r = _co2.xs(_run, level="scenario")
        _total = _r.xs("total", level="metric")
        _fig.add_trace(
            go.Scatter(
                x=_total.index,
                y=_total,
                name=_run,
                mode="lines+markers",
                line=dict(color=PALETTE[_i]),
            )
        )
    if sens.DP3_WITH in _scenarios:
        _budget = _co2.xs((sens.DP3_WITH, "budget"), level=["scenario", "metric"])
        _fig.add_trace(
            go.Scatter(
                x=_budget.index,
                y=_budget,
                name="AT budget",
                mode="lines",
                line=dict(color="#6b6a63", dash="dash"),
            )
        )
    layout(_fig, "AT CO2 against the AT budget", "Mt")
    _fig.update_xaxes(type="category")
    mo.vstack(
        [
            s5_group,
            family_view(
                effects,
                "S5",
                s5_group.value,
                "`co2_budget.upper` follows the AT budget path. *P3, EU cap* is the "
                "base P3 effect; *P3, AT path* the P3 effect at the same ambition; "
                "*cap* the effect of the cap alone. Look at *CO2* (total and "
                "budget), *CO2 price* (`EU` = mu of `CO2Limit-upper`) and *cost*. "
                "The AT path is relative to AT 1990 CO2, the EU cap to the EU GHG "
                "goals: the same numbers are not the same ambition.",
            ),
            mo.ui.plotly(_fig),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
