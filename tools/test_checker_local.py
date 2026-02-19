"""
Local test runner for checker_lux_solar.py
Runs all 3 check functions against a sample IFC file and prints results.

Usage:
    python test_checker_local.py
    python test_checker_local.py path/to/your_model.ifc
"""

import sys
import os
import ifcopenshell

# Add parent paths so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from checker_lux_solar import (
    check_solar_production,
    check_leed_renewable_score,
    check_roof_segment_count,
)

# ── Schema validation ──────────────────────────────────────────────
REQUIRED_KEYS = {
    "element_id",
    "element_type",
    "element_name",
    "element_name_long",
    "check_status",
    "actual_value",
    "required_value",
    "comment",
    "log",
}

VALID_STATUSES = {"pass", "fail", "warning", "blocked"}


def validate_row(row: dict, check_name: str, idx: int) -> list[str]:
    """Validate a single result row against the IFCore schema."""
    errors = []
    prefix = f"[{check_name}][row {idx}]"

    # Check required keys
    missing = REQUIRED_KEYS - set(row.keys())
    if missing:
        errors.append(f"{prefix} Missing keys: {missing}")

    # Check status value
    status = row.get("check_status")
    if status not in VALID_STATUSES:
        errors.append(f"{prefix} Invalid check_status: '{status}' (expected one of {VALID_STATUSES})")

    return errors


def run_check(name: str, func, model, **kwargs):
    """Run a single check function, validate output, print results."""
    print(f"\n{'='*70}")
    print(f"  CHECK: {name}")
    print(f"{'='*70}")

    try:
        results = func(model, **kwargs)
    except Exception as e:
        print(f"  CRASHED: {e}")
        import traceback
        traceback.print_exc()
        return False

    if not isinstance(results, list):
        print(f"  Return type must be list, got {type(results).__name__}")
        return False

    if len(results) == 0:
        print(f"  Returned empty list (no rows)")
        return True

    # Validate each row
    all_errors = []
    for i, row in enumerate(results):
        all_errors.extend(validate_row(row, name, i))

    # Print results table
    print(f"\n  Rows returned: {len(results)}")
    print(f"  {'Status':<10} {'Element Type':<25} {'Actual Value':<30} {'Comment'}")
    print(f"  {'-'*10} {'-'*25} {'-'*30} {'-'*40}")
    for row in results:
        status = row.get("check_status", "?")
        etype = (row.get("element_type") or "?")[:25]
        actual = (row.get("actual_value") or "")[:30]
        comment = (row.get("comment") or "")[:60]
        icon = {"pass": "[PASS]", "fail": "[FAIL]", "warning": "[WARN]", "blocked": "[BLOCK]"}.get(status, "[?]")
        print(f"  {icon:<10} {etype:<25} {actual:<30} {comment}")

    # Print schema errors
    if all_errors:
        print(f"\n  SCHEMA ERRORS ({len(all_errors)}):")
        for err in all_errors:
            print(f"     - {err}")
        return False
    else:
        print(f"\n  Schema validation passed - all rows conform to IFCore contract")
        return True


def main():
    # Resolve IFC file
    if len(sys.argv) > 1:
        ifc_path = sys.argv[1]
    else:
        # Default: try the sample models in the starter repo
        candidates = [
            os.path.join("..", "..", "iaac-bimwise-starter", "00_data", "ifc_models", "Ifc4_SampleHouse.ifc"),
            os.path.join("..", "..", "iaac-bimwise-starter", "00_data", "ifc_models", "Ifc4_SampleHouse_1_Roof.ifc"),
            os.path.join("..", "..", "iaac-bimwise-starter", "00_data", "ifc_models", "01_Duplex_Apartment.ifc"),
        ]
        base = os.path.dirname(os.path.abspath(__file__))
        ifc_path = None
        for c in candidates:
            full = os.path.normpath(os.path.join(base, c))
            if os.path.exists(full):
                ifc_path = full
                break

        if not ifc_path:
            print("No IFC file found. Usage:")
            print("   python test_checker_local.py path/to/model.ifc")
            sys.exit(1)

    print(f"{'='*70}")
    print(f"  Lux Solar Checker - Local Test Runner")
    print(f"{'='*70}")
    print(f"  IFC file: {os.path.basename(ifc_path)}")

    # Load model
    try:
        model = ifcopenshell.open(ifc_path)
        print(f"  Model loaded: {model.schema} - {len(list(model))} entities")
    except Exception as e:
        print(f"\n  Failed to open IFC file: {e}")
        sys.exit(1)

    # Run all 3 checks
    results = {}
    results["check_solar_production"] = run_check(
        "check_solar_production", check_solar_production, model
    )
    results["check_leed_renewable_score"] = run_check(
        "check_leed_renewable_score", check_leed_renewable_score, model, min_leed_pct=50
    )
    results["check_roof_segment_count"] = run_check(
        "check_roof_segment_count", check_roof_segment_count, model, min_segments=1
    )

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    all_pass = True
    for name, passed in results.items():
        icon = "[OK]" if passed else "[FAIL]"
        print(f"  {icon} {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print(f"\n  All checks executed and schema-valid. Ready for IFCore integration.")
    else:
        print(f"\n  Some checks had issues. Fix them before deploying to IFCore.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
