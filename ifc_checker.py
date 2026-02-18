"""IFC Compliance Checker — YOUR CODE GOES HERE"""

import ifcopenshell


# ─── Write your check functions below ──────────────────────────
# Each function takes a model, returns a list of strings.
# One string per element you checked.

def check_door_width(model, min_width_mm=800):
    """Check that all doors are at least 800mm wide."""
    results = []
    for door in model.by_type("IfcDoor"):
        width_m = door.OverallWidth  # IFC stores in meters
        width_mm = round(width_m * 1000) if width_m else None
        if width_mm is None:
            results.append(f"[???] {door.Name}: width unknown")
        elif width_mm >= min_width_mm:
            results.append(f"[PASS] {door.Name}: {width_mm} mm (min {min_width_mm} mm)")
        else:
            results.append(f"[FAIL] {door.Name}: {width_mm} mm (min {min_width_mm} mm)")
    return results


# def check_room_area(model):
#     """Your next check..."""
#     results = []
#     for space in model.by_type("IfcSpace"):
#         ...
#     return results


# ─── Main entry point used by app.py ───────────────────────────

def run_all_checks(ifc_path):
    """Run all compliance checks on an IFC file.

    Returns dict with:
        - results: list of check result dicts
        - failed_ids: set of GlobalIds that failed
        - summary: dict with passed/failed/unknown/total counts
    """
    model = ifcopenshell.open(ifc_path)
    results = []
    failed_ids = set()

    # --- Door width check ---
    for door in model.by_type("IfcDoor"):
        width_m = door.OverallWidth
        width_mm = round(width_m * 1000) if width_m else None

        if width_mm is None:
            passed = None
            actual = "unknown"
        elif width_mm >= 800:
            passed = True
            actual = f"{width_mm} mm"
        else:
            passed = False
            actual = f"{width_mm} mm"
            failed_ids.add(door.GlobalId)

        results.append({
            "element_id": door.GlobalId,
            "element_type": "IfcDoor",
            "element_name": door.Name or "Unnamed Door",
            "rule": "Min Door Width",
            "requirement": ">= 800 mm",
            "actual": actual,
            "passed": passed,
        })

    # Add more checks here by appending to results and failed_ids

    passed = sum(1 for r in results if r["passed"] is True)
    failed = sum(1 for r in results if r["passed"] is False)
    unknown = sum(1 for r in results if r["passed"] is None)

    return {
        "results": results,
        "failed_ids": failed_ids,
        "summary": {
            "passed": passed,
            "failed": failed,
            "unknown": unknown,
            "total": len(results),
        },
    }
