"""
checker_lux_solar.py — IFCore-compatible check functions for the Lux.Ai
solar production pipeline.

Bridges the team's ``final_pipeline.analyze.analyze_ifc()`` results into the
IFCore Validation Schema (element_results dicts) so the platform orchestrator
can auto-discover and run them.

Contract (from IFCore-skill):
  - File lives directly inside tools/
  - Functions prefixed with check_*
  - First argument is always ``model`` (ifcopenshell.file)
  - Returns list[dict] with element_results fields
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import ifcopenshell

log = logging.getLogger(__name__)

# ── Ensure the Lux.Ai repo root is on sys.path so final_pipeline is importable
_THIS_DIR = Path(__file__).resolve().parent          # tools/
_REPO_ROOT = _THIS_DIR.parent                        # Lux.Ai/
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_pipeline(model: ifcopenshell.file) -> dict:
    """
    Write the in-memory model to a temp file and run the full Lux solar
    pipeline.  Returns the result dict from analyze_ifc().
    """
    from final_pipeline.analyze import analyze_ifc  # lazy import

    # The pipeline expects a file path, so persist the model temporarily
    fd, tmp_path = tempfile.mkstemp(suffix=".ifc")
    try:
        model.write(tmp_path)
        result = analyze_ifc(tmp_path, call_api=True)
    finally:
        os.close(fd)
        os.unlink(tmp_path)
    return result


def _make_element_result(
    *,
    element_id: str | None = None,
    element_type: str | None = None,
    element_name: str | None = None,
    element_name_long: str | None = None,
    check_status: str,
    actual_value: str | None = None,
    required_value: str | None = None,
    comment: str | None = None,
    log_text: str | None = None,
) -> dict:
    """Build one element_results dict per IFCore Validation Schema."""
    return {
        "element_id":        element_id,
        "element_type":      element_type,
        "element_name":      element_name,
        "element_name_long": element_name_long,
        "check_status":      check_status,
        "actual_value":      actual_value,
        "required_value":    required_value,
        "comment":           comment,
        "log":               log_text,
    }


# ── Check Functions ───────────────────────────────────────────────────────────

def check_solar_production(
    model: ifcopenshell.file,
    min_production_kwh: float = 0.0,
) -> list[dict]:
    """
    Run the full Lux.Ai solar pipeline on the IFC model and return one
    element_results row per roof segment with its annual kWh yield.

    Also appends a building-level summary row with the total production
    and LEED renewable-energy score.

    Parameters
    ----------
    model : ifcopenshell.file
        The IFC model (passed by the IFCore platform orchestrator).
    min_production_kwh : float
        Minimum annual production threshold in kWh/yr per segment.
        Segments below this value get check_status="warning".
        Default 0 means every segment passes.
    """
    results: list[dict] = []

    # Run the pipeline
    analysis = _run_pipeline(model)

    if not analysis.get("ok"):
        # Pipeline failed — return a single blocked result
        results.append(_make_element_result(
            element_type="IfcRoof",
            element_name="Solar Analysis",
            element_name_long="Solar Analysis — pipeline error",
            check_status="blocked",
            comment=analysis.get("error", "Unknown pipeline error"),
        ))
        return results

    # Per-segment results
    for seg in analysis.get("segments", []):
        seg_id = seg.get("id", "unknown")
        area = seg.get("area", 0.0)
        tilt = seg.get("tilt", 0.0)
        azimuth = seg.get("azimuth", 0.0)
        kwh = seg.get("annual_kwh", 0.0)
        capacity = seg.get("capacity_kw", 0.0)
        global_id = seg.get("global_id")
        ifc_type = seg.get("ifc_type", "IfcRoof")

        # Determine status
        if kwh > min_production_kwh:
            status = "pass"
            comment = None
        elif kwh == 0.0:
            status = "warning"
            comment = "Zero production — API may have failed or segment is north-facing"
        else:
            status = "warning"
            comment = (
                f"Production {kwh:,.0f} kWh/yr is below threshold "
                f"{min_production_kwh:,.0f} kWh/yr"
            )

        detail = (
            f"Area: {area:.1f} m² | Tilt: {tilt:.1f}° | "
            f"Azimuth: {azimuth:.0f}° | Capacity: {capacity:.1f} kW"
        )

        results.append(_make_element_result(
            element_id=global_id,
            element_type=ifc_type,
            element_name=seg_id,
            element_name_long=f"{seg_id} ({detail})",
            check_status=status,
            actual_value=f"{kwh:,.1f} kWh/yr",
            required_value=(
                f"≥ {min_production_kwh:,.0f} kWh/yr"
                if min_production_kwh > 0 else None
            ),
            comment=comment,
            log_text=detail,
        ))

    # Building-level summary row
    total = analysis.get("total_production", 0.0)
    leed = analysis.get("leed_score", 0.0)
    consumption = analysis.get("consumption", 0.0)
    total_roof = analysis.get("total_roof_area_m2", 0.0)
    total_cap = analysis.get("total_capacity_kw", 0.0)

    if leed >= 100:
        summary_status = "pass"
        summary_comment = "Net-zero energy achieved"
    elif leed >= 50:
        summary_status = "pass"
        summary_comment = f"Good renewable coverage ({leed:.1f}%)"
    elif leed > 0:
        summary_status = "warning"
        summary_comment = f"Low renewable coverage ({leed:.1f}%)"
    else:
        summary_status = "fail"
        summary_comment = "No solar production estimated"

    summary_detail = (
        f"Roof: {total_roof:,.1f} m² | Capacity: {total_cap:,.1f} kW | "
        f"Consumption: {consumption:,.0f} kWh/yr"
    )

    results.append(_make_element_result(
        element_type="IfcBuilding",
        element_name="Solar Summary",
        element_name_long=(
            f"Solar Summary — {analysis.get('project_name', 'unknown')} "
            f"({analysis.get('ifc_file', '')})"
        ),
        check_status=summary_status,
        actual_value=f"{total:,.1f} kWh/yr (LEED {leed:.1f}%)",
        required_value=None,
        comment=summary_comment,
        log_text=summary_detail,
    ))

    return results


def check_leed_renewable_score(
    model: ifcopenshell.file,
    min_leed_pct: float = 50.0,
) -> list[dict]:
    """
    Check whether the building's LEED renewable-energy score meets a
    minimum percentage threshold.

    Returns a single element_results row for the whole building.

    Parameters
    ----------
    model : ifcopenshell.file
        The IFC model.
    min_leed_pct : float
        Minimum LEED renewable energy percentage required.
        Default 50% (a common intermediate target).
    """
    analysis = _run_pipeline(model)

    if not analysis.get("ok"):
        return [_make_element_result(
            element_type="IfcBuilding",
            element_name="LEED Score",
            element_name_long="LEED Renewable Energy Score — pipeline error",
            check_status="blocked",
            comment=analysis.get("error", "Unknown pipeline error"),
        )]

    leed = analysis.get("leed_score", 0.0)
    total = analysis.get("total_production", 0.0)
    consumption = analysis.get("consumption", 0.0)

    if leed >= min_leed_pct:
        status = "pass"
        comment = (
            f"Score {leed:.1f}% meets the {min_leed_pct:.0f}% threshold"
            + (" — net-zero achieved!" if leed >= 100 else "")
        )
    else:
        status = "fail"
        comment = (
            f"Score {leed:.1f}% is below the {min_leed_pct:.0f}% threshold. "
            f"Consider adding more panel capacity or reducing consumption."
        )

    return [_make_element_result(
        element_type="IfcBuilding",
        element_name="LEED Score",
        element_name_long=(
            f"LEED Renewable Energy Score — "
            f"{analysis.get('project_name', 'unknown')}"
        ),
        check_status=status,
        actual_value=f"{leed:.1f}% ({total:,.0f} / {consumption:,.0f} kWh/yr)",
        required_value=f"≥ {min_leed_pct:.0f}%",
        comment=comment,
        log_text=(
            f"Production: {total:,.1f} kWh/yr | "
            f"Consumption: {consumption:,.1f} kWh/yr | "
            f"Score: {leed:.1f}%"
        ),
    )]


def check_roof_segment_count(
    model: ifcopenshell.file,
    min_segments: int = 1,
) -> list[dict]:
    """
    Verify that the IFC model contains at least ``min_segments`` roof
    segments suitable for solar panel installation.

    This is a lightweight geometry-only check (no API call needed).
    """
    analysis = _run_pipeline(model)

    if not analysis.get("ok"):
        return [_make_element_result(
            element_type="IfcRoof",
            element_name="Roof Segments",
            element_name_long="Roof Segment Count — pipeline error",
            check_status="blocked",
            comment=analysis.get("error", "Unknown pipeline error"),
        )]

    segments = analysis.get("segments", [])
    count = len(segments)

    if count >= min_segments:
        status = "pass"
        comment = f"Found {count} roof segment(s)"
    elif count == 0:
        status = "fail"
        comment = "No roof segments detected — model may lack IfcRoof elements"
    else:
        status = "fail"
        comment = f"Found {count} segment(s), need at least {min_segments}"

    return [_make_element_result(
        element_type="IfcRoof",
        element_name="Roof Segments",
        element_name_long=f"Roof Segment Count — {count} segment(s) detected",
        check_status=status,
        actual_value=str(count),
        required_value=f"≥ {min_segments}",
        comment=comment,
    )]
