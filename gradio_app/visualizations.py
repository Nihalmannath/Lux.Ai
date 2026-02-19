"""
visualizations.py — Reusable Plotly chart builders for the Solar Pipeline.

Each function takes standard data (pipeline results or IFCore checker output)
and returns a plotly.graph_objects.Figure.  No Gradio dependency — these work
standalone in Jupyter, Dash, React (via plotly.js), or any Plotly-compatible
frontend.

Usage:
    from gradio_app.visualizations import create_yield_bar_chart
    fig = create_yield_bar_chart(checker_data)
    fig.show()                     # standalone
    gr.Plot(value=fig)             # Gradio
    fig.to_json()                  # send to React / plotly.js
"""

from __future__ import annotations

from typing import Any

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ── Colour palette ────────────────────────────────────────────────────────────

_COLOURS = {
    "green":      "#22c55e",
    "green_light": "#bbf7d0",
    "red":        "#ef4444",
    "red_light":  "#fecaca",
    "amber":      "#f59e0b",
    "amber_light": "#fef3c7",
    "blue":       "#3b82f6",
    "blue_light": "#bfdbfe",
    "slate":      "#64748b",
    "slate_light": "#e2e8f0",
    "white":      "#ffffff",
    "dark":       "#1e293b",
}


# ── Public API ────────────────────────────────────────────────────────────────

def create_yield_bar_chart(
    checker_data: list[dict],
    *,
    title: str = "Solar Yield by Roof Segment",
    height: int = 420,
) -> go.Figure:
    """
    Build a Plotly bar chart from IFCore check_solar_production output.
    """
    segments = _extract_segment_rows(checker_data)
    if not segments:
        return _empty_figure(title, height, "No roof segments in checker output")

    names: list[str] = []
    kwh_values: list[float] = []
    statuses: list[str] = []
    hover_texts: list[str] = []

    for seg in segments:
        names.append(seg.get("element_name", "?"))
        kwh_values.append(_parse_kwh(seg.get("actual_value", "0")))
        statuses.append(seg.get("check_status", "log"))
        hover_texts.append(seg.get("log") or seg.get("element_name_long") or "")

    status_colours = {
        "pass": _COLOURS["green"], "fail": _COLOURS["red"],
        "warning": _COLOURS["amber"], "blocked": _COLOURS["slate"],
        "log": _COLOURS["slate"],
    }
    bar_colours = [status_colours.get(s, _COLOURS["slate"]) for s in statuses]

    fig = go.Figure(
        data=go.Bar(
            x=names, y=kwh_values, marker_color=bar_colours,
            hovertext=hover_texts,
            hovertemplate="<b>%{x}</b><br>Yield: %{y:,.0f} kWh/yr<br>%{hovertext}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=18)),
        xaxis_title="Roof Segment", yaxis_title="Annual Yield (kWh/yr)",
        height=height, template="plotly_white",
        margin=dict(l=60, r=30, t=60, b=60), yaxis=dict(rangemode="tozero"),
    )
    return fig


def create_yield_bar_chart_from_pipeline(
    pipeline_result: dict,
    *,
    height: int = 520,
) -> go.Figure:
    """
    Fancy compliance dashboard from the raw analyze_ifc() result.

    Shows:
      - Individual segment bars colour-coded by compliance share
      - Total Production bar on the right
      - Horizontal compliance threshold line (= consumption)
      - LEED score badge annotation
      - Per-bar compliance % labels
    """
    segments = pipeline_result.get("segments", [])
    if not segments:
        return _empty_figure("Solar Compliance", height, "No roof segments found")

    consumption = pipeline_result.get("consumption", 0.0)
    total_prod = pipeline_result.get("total_production", 0.0)
    leed_score = pipeline_result.get("leed_score", 0.0)
    n_seg = len(segments)

    # ── Per-segment data ──────────────────────────────────────────────────
    names = [s.get("id", "?").replace("Roof_Seg_", "Seg ") for s in segments]
    kwh_values = [s.get("annual_kwh", 0.0) for s in segments]
    areas = [s.get("area", 0.0) for s in segments]
    tilts = [s.get("tilt", 0.0) for s in segments]
    azimuths = [s.get("azimuth", 0.0) for s in segments]
    capacities = [s.get("capacity_kw", 0.0) for s in segments]

    # Fair-share threshold per segment (consumption split equally)
    fair_share = consumption / n_seg if n_seg > 0 else 0.0

    # ── Determine bar colours ─────────────────────────────────────────────
    seg_colours = []
    seg_border = []
    for kwh in kwh_values:
        if kwh >= fair_share and fair_share > 0:
            seg_colours.append(_COLOURS["green"])
            seg_border.append(_COLOURS["green"])
        elif kwh >= fair_share * 0.5:
            seg_colours.append(_COLOURS["amber"])
            seg_border.append(_COLOURS["amber"])
        else:
            seg_colours.append(_COLOURS["red"])
            seg_border.append(_COLOURS["red"])

    # Total bar colour
    if leed_score >= 100:
        total_colour = _COLOURS["green"]
        badge_text = f"⭐ NET-ZERO  {leed_score:.1f}%"
        badge_bg = _COLOURS["green"]
    elif leed_score >= 50:
        total_colour = _COLOURS["green"]
        badge_text = f"✓ COMPLIANT  {leed_score:.1f}%"
        badge_bg = _COLOURS["green"]
    elif leed_score >= 25:
        total_colour = _COLOURS["amber"]
        badge_text = f"⚠ PARTIAL  {leed_score:.1f}%"
        badge_bg = _COLOURS["amber"]
    else:
        total_colour = _COLOURS["red"]
        badge_text = f"✗ NON-COMPLIANT  {leed_score:.1f}%"
        badge_bg = _COLOURS["red"]

    # ── Build X axis: segments + gap + TOTAL ──────────────────────────────
    x_labels = names + ["", "TOTAL"]
    y_values = kwh_values + [0, total_prod]
    bar_colours_all = seg_colours + [_COLOURS["slate_light"], total_colour]
    border_all = seg_border + [_COLOURS["slate_light"], total_colour]

    hover_texts = []
    for i, s in enumerate(segments):
        pct_of_consumption = (kwh_values[i] / consumption * 100) if consumption > 0 else 0
        hover_texts.append(
            f"<b>{names[i]}</b><br>"
            f"Yield: {kwh_values[i]:,.0f} kWh/yr<br>"
            f"Area: {areas[i]:.1f} m²<br>"
            f"Tilt: {tilts[i]:.1f}° · Azimuth: {azimuths[i]:.0f}°<br>"
            f"Capacity: {capacities[i]:.1f} kW<br>"
            f"Share of consumption: {pct_of_consumption:.1f}%"
        )
    hover_texts.append("")  # spacer
    hover_texts.append(
        f"<b>TOTAL PRODUCTION</b><br>"
        f"{total_prod:,.0f} kWh/yr<br>"
        f"LEED Score: {leed_score:.1f}%<br>"
        f"Consumption: {consumption:,.0f} kWh/yr"
    )

    # ── Create figure ─────────────────────────────────────────────────────
    fig = go.Figure()

    # Segment bars
    fig.add_trace(go.Bar(
        x=x_labels[:n_seg],
        y=y_values[:n_seg],
        marker=dict(
            color=bar_colours_all[:n_seg],
            line=dict(color=border_all[:n_seg], width=1.5),
            opacity=0.85,
        ),
        hovertext=hover_texts[:n_seg],
        hovertemplate="%{hovertext}<extra></extra>",
        name="Segments",
        showlegend=False,
        text=[f"{v:,.0f}" for v in kwh_values],
        textposition="outside",
        textfont=dict(size=11, color=_COLOURS["dark"]),
    ))

    # Total bar (separate trace so it stands out)
    fig.add_trace(go.Bar(
        x=["TOTAL"],
        y=[total_prod],
        marker=dict(
            color=total_colour,
            line=dict(color=total_colour, width=2),
            opacity=0.95,
            pattern=dict(shape="/", fgcolor="rgba(255,255,255,0.3)"),
        ),
        hovertext=[hover_texts[-1]],
        hovertemplate="%{hovertext}<extra></extra>",
        name="Total",
        showlegend=False,
        text=[f"{total_prod:,.0f}"],
        textposition="outside",
        textfont=dict(size=13, color=_COLOURS["dark"], family="Arial Black"),
    ))

    # ── Compliance threshold line ─────────────────────────────────────────
    fig.add_hline(
        y=consumption,
        line=dict(color=_COLOURS["red"], width=2.5, dash="dash"),
        annotation=dict(
            text=f"  Consumption: {consumption:,.0f} kWh/yr",
            font=dict(size=12, color=_COLOURS["red"], family="Arial"),
            xanchor="left",
        ),
    )

    # Fair-share line per segment (lighter, dotted)
    if n_seg > 1:
        fig.add_hline(
            y=fair_share,
            line=dict(color=_COLOURS["amber"], width=1.5, dash="dot"),
            annotation=dict(
                text=f"  Fair share/segment: {fair_share:,.0f} kWh/yr",
                font=dict(size=10, color=_COLOURS["amber"]),
                xanchor="left",
                yanchor="top",
            ),
        )

    # ── LEED score badge (top-right) ──────────────────────────────────────
    fig.add_annotation(
        text=f"<b>LEED SCORE: {leed_score:.1f}%</b>",
        xref="paper", yref="paper",
        x=0.98, y=0.98,
        xanchor="right", yanchor="top",
        showarrow=False,
        font=dict(size=16, color=_COLOURS["white"], family="Arial Black"),
        bgcolor=badge_bg,
        bordercolor=badge_bg,
        borderwidth=2,
        borderpad=8,
        opacity=0.92,
    )

    # Status label under the badge
    if leed_score >= 100:
        status_label = "★ NET-ZERO ENERGY"
        status_color = _COLOURS["green"]
    elif leed_score >= 50:
        status_label = "✓ Meets 50% threshold"
        status_color = _COLOURS["green"]
    elif leed_score >= 25:
        status_label = "⚠ Below 50% — needs improvement"
        status_color = _COLOURS["amber"]
    else:
        status_label = "✗ Critical — major deficit"
        status_color = _COLOURS["red"]

    fig.add_annotation(
        text=f"<b>{status_label}</b>",
        xref="paper", yref="paper",
        x=0.98, y=0.90,
        xanchor="right", yanchor="top",
        showarrow=False,
        font=dict(size=12, color=status_color, family="Arial"),
    )

    # ── Compliance % labels on each segment bar ───────────────────────────
    for i in range(n_seg):
        if consumption > 0:
            pct = kwh_values[i] / consumption * 100
            label = f"{pct:.0f}%"
        else:
            label = "—"
        fig.add_annotation(
            x=names[i], y=kwh_values[i] / 2,
            text=f"<b>{label}</b>",
            showarrow=False,
            font=dict(size=12, color="white", family="Arial Black"),
        )

    # ── Layout ────────────────────────────────────────────────────────────
    y_max = max(consumption, total_prod, max(kwh_values)) * 1.25

    fig.update_layout(
        title=dict(
            text="☀️ Solar Production vs Consumption Compliance",
            font=dict(size=20, family="Arial", color=_COLOURS["dark"]),
            x=0.01, xanchor="left",
        ),
        xaxis=dict(
            title=None,
            tickfont=dict(size=12, family="Arial"),
            categoryorder="array",
            categoryarray=x_labels,
        ),
        yaxis=dict(
            title=dict(text="Energy (kWh/yr)", font=dict(size=13)),
            tickfont=dict(size=11),
            rangemode="tozero",
            range=[0, y_max],
            gridcolor="#f1f5f9",
            gridwidth=1,
        ),
        height=height,
        template="plotly_white",
        margin=dict(l=70, r=30, t=70, b=50),
        plot_bgcolor="#fafbfc",
        bargap=0.3,
        bargroupgap=0.1,
    )

    return fig


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_segment_rows(checker_data: list[dict]) -> list[dict]:
    """Filter checker output to roof-segment rows only (skip summary rows)."""
    return [
        row for row in checker_data
        if row.get("element_type") not in ("IfcBuilding", None)
        and row.get("element_name", "").startswith("Roof_Seg")
    ]


def _parse_kwh(value: str) -> float:
    """Parse a value string like '19,063.0 kWh/yr' into a float."""
    if not value:
        return 0.0
    try:
        cleaned = value.replace(",", "").replace("kWh/yr", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0


def _empty_figure(title: str, height: int, message: str) -> go.Figure:
    """Return a blank figure with a message annotation."""
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, font=dict(size=18)),
        height=height,
        template="plotly_white",
        annotations=[
            dict(
                text=message,
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=16, color="#94a3b8"),
            )
        ],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig
