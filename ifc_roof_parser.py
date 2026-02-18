"""
IFC Roof Parser
================
Extracts roof segment geometry from any IFC file and returns a
standardised list of segments with area, tilt, and azimuth.

Pipeline position:
    IFC file  →  [ifc_roof_parser]  →  list[RoofSegment dict]
                                          ↓
                                   [solar_production_engine]  →  kWh

The parser works with:
  • Monolithic IfcRoof elements  (barrel vaults, single-surface roofs)
  • Decomposed IfcRoof → IfcSlab  (hip / gable roofs in Revit exports)
  • Standalone IfcSlab with .ROOF. predefined type

Orientation (tilt & azimuth) is computed from triangulated face normals,
NOT from property sets — this makes it reliable across different BIM
authoring tools.
"""

import math
import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import trimesh


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Minimum angular gap (degrees) between cluster centroids.
# Faces within this angle of an existing cluster are merged into it.
# 25° works well for curved roofs (barrel vaults) where the surface
# gradually transitions — keeps logical orientations distinct while
# merging faces that belong to the same "side" of the roof.
CLUSTER_ANGLE_TOLERANCE = 25.0

# Ignore segments smaller than this (m²) — avoids noise from tiny faces.
MIN_SEGMENT_AREA = 1.0

# Only consider upward-facing faces (nz > threshold).  0 = horizontal;
# a small negative value captures nearly-vertical faces that still
# receive useful solar radiation.
MIN_NZ_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _normal_to_tilt(normal: np.ndarray) -> float:
    """Convert a unit normal vector to tilt angle in degrees.

    Tilt = angle between the surface normal and the vertical (Z up).
    A flat roof has tilt 0°; a vertical wall has tilt 90°.
    """
    nz = np.clip(normal[2], -1.0, 1.0)
    return math.degrees(math.acos(abs(nz)))


def _normal_to_azimuth(normal: np.ndarray) -> float:
    """Convert a unit normal vector to compass azimuth in degrees.

    Convention (IFC default): +Y = North, +X = East.
    atan2(east, north) gives compass bearing; 180° = due South.

    Returns a value in [0, 360).  Exactly 360 is mapped to 0.
    """
    azimuth = math.degrees(math.atan2(normal[0], normal[1])) % 360.0
    # PVWatts API requires azimuth in [0, 360) — reject exactly 360
    if azimuth >= 359.95:
        azimuth = 0.0
    return azimuth


def _angle_between(n1: np.ndarray, n2: np.ndarray) -> float:
    """Angle in degrees between two unit vectors.

    Uses the angular distance in the *horizontal projection* for the
    azimuth-sensitive comparison, but falls back to the full 3-D angle
    so that faces with very different tilts are not merged.
    """
    dot = np.clip(np.dot(n1, n2), -1.0, 1.0)
    return math.degrees(math.acos(dot))


# ---------------------------------------------------------------------------
# Face clustering
# ---------------------------------------------------------------------------
def _cluster_faces(
    normals: np.ndarray,
    areas: np.ndarray,
    tolerance: float = CLUSTER_ANGLE_TOLERANCE,
) -> list[dict]:
    """Group triangulated faces by angular similarity of their normals.

    Returns a list of cluster dicts, each containing:
        - "centroid":  area-weighted average unit normal (3,)
        - "area":      total area of faces in cluster (float)
        - "indices":   list of face indices in the cluster
    """
    clusters: list[dict] = []

    for i in range(len(normals)):
        n = normals[i]
        a = areas[i]

        # Skip downward-facing or near-horizontal-down faces
        if n[2] < MIN_NZ_THRESHOLD:
            continue

        # Try to merge into an existing cluster
        merged = False
        for cluster in clusters:
            if _angle_between(n, cluster["centroid"]) < tolerance:
                # Update the area-weighted centroid
                old_weight = cluster["area"]
                new_weight = old_weight + a
                cluster["centroid"] = (
                    cluster["centroid"] * old_weight + n * a
                ) / new_weight
                # Re-normalise to unit length
                norm = np.linalg.norm(cluster["centroid"])
                if norm > 0:
                    cluster["centroid"] /= norm
                cluster["area"] = new_weight
                cluster["indices"].append(i)
                merged = True
                break

        if not merged:
            clusters.append({
                "centroid": n.copy(),
                "area": float(a),
                "indices": [i],
            })

    return clusters


# ---------------------------------------------------------------------------
# Element geometry extraction
# ---------------------------------------------------------------------------
def _extract_mesh(
    element: ifcopenshell.entity_instance,
    settings: ifcopenshell.geom.settings,
) -> trimesh.Trimesh | None:
    """Extract a triangulated mesh for a single IFC element.

    Returns None if geometry cannot be computed.
    """
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        faces = np.array(shape.geometry.faces).reshape(-1, 3)
        if len(verts) == 0 or len(faces) == 0:
            return None
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    except Exception as exc:
        print(f"  [Geometry Warning] Could not process {element.Name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Roof element discovery
# ---------------------------------------------------------------------------
def _find_roof_elements(
    model: ifcopenshell.file,
) -> list[ifcopenshell.entity_instance]:
    """Find all IFC elements that represent roof surfaces.

    Strategy:
      1. Collect all IfcRoof entities.
      2. For each IfcRoof, check for decomposed children (IfcRelAggregates).
         If children exist, use them instead of the parent.
      3. Also pick up any IfcSlab with predefined type ROOF that isn't
         already captured via aggregation.
    """
    roof_elements: list[ifcopenshell.entity_instance] = []
    seen_ids: set[int] = set()

    # --- IfcRoof entities and their potential sub-slabs ----
    for roof in model.by_type("IfcRoof"):
        children = []
        for rel in model.by_type("IfcRelAggregates"):
            if rel.RelatingObject == roof:
                children.extend(rel.RelatedObjects)

        if children:
            # Decomposed roof → use children (usually IfcSlab .ROOF.)
            for child in children:
                if child.id() not in seen_ids:
                    roof_elements.append(child)
                    seen_ids.add(child.id())
        else:
            # Monolithic roof → use the IfcRoof itself
            if roof.id() not in seen_ids:
                roof_elements.append(roof)
                seen_ids.add(roof.id())

    # --- Standalone IfcSlab with .ROOF. predefined type ---
    for slab in model.by_type("IfcSlab"):
        if hasattr(slab, "PredefinedType") and slab.PredefinedType == "ROOF":
            if slab.id() not in seen_ids:
                roof_elements.append(slab)
                seen_ids.add(slab.id())

    return roof_elements


# ---------------------------------------------------------------------------
# Property-set helpers (for sanity-check / fallback)
# ---------------------------------------------------------------------------
def _get_pset_area(element: ifcopenshell.entity_instance) -> float | None:
    """Try to read TotalArea from Pset_RoofCommon or Area from Dimensions."""
    try:
        psets = ifcopenshell.util.element.get_psets(element)
    except Exception:
        return None

    # Pset_RoofCommon → TotalArea
    roof_common = psets.get("Pset_RoofCommon", {})
    if "TotalArea" in roof_common:
        return float(roof_common["TotalArea"])

    # Dimensions → Area
    dims = psets.get("Dimensions", {})
    if "Area" in dims:
        return float(dims["Area"])

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_roof_segments(
    ifc_path: str,
    cluster_tolerance: float = CLUSTER_ANGLE_TOLERANCE,
    min_segment_area: float = MIN_SEGMENT_AREA,
) -> list[dict]:
    """Parse an IFC file and return a list of roof segments.

    Each segment is a dict with keys:
        id       – human-readable label  (str)
        area     – segment area in m²    (float)
        tilt     – degrees from horizontal (float)
        azimuth  – compass bearing in degrees, 180 = south (float)

    Parameters
    ----------
    ifc_path : str
        Path to the IFC file.
    cluster_tolerance : float
        Angular tolerance (degrees) for grouping faces into segments.
    min_segment_area : float
        Discard segments smaller than this (m²).
    """
    print(f"  Opening IFC: {ifc_path}")
    model = ifcopenshell.open(ifc_path)

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    # 1 — Discover roof elements
    roof_elements = _find_roof_elements(model)
    if not roof_elements:
        print("  [Warning] No roof elements found in this IFC file.")
        return []

    print(f"  Found {len(roof_elements)} roof element(s):")
    for el in roof_elements:
        label = el.Name or el.is_a()
        print(f"    • {label}  ({el.is_a()}, #{el.id()})")

    # 2 — For each element, extract geometry and cluster faces
    all_segments: list[dict] = []
    segment_counter = 0

    for el in roof_elements:
        mesh = _extract_mesh(el, settings)
        if mesh is None:
            continue

        normals = mesh.face_normals        # (N, 3)
        face_areas = mesh.area_faces       # (N,)
        total_mesh_area = float(np.sum(face_areas))

        # Pset area for sanity check
        pset_area = _get_pset_area(el)
        if pset_area is not None:
            print(
                f"  Geometry area: {total_mesh_area:.2f} m²  |  "
                f"Pset area: {pset_area:.2f} m²"
            )
        else:
            print(f"  Geometry area: {total_mesh_area:.2f} m²")

        # 3 — Cluster upward-facing triangles
        clusters = _cluster_faces(normals, face_areas, cluster_tolerance)

        for cluster in clusters:
            if cluster["area"] < min_segment_area:
                continue

            segment_counter += 1
            tilt = _normal_to_tilt(cluster["centroid"])
            azimuth = _normal_to_azimuth(cluster["centroid"])

            seg = {
                "id": f"Roof_Seg_{segment_counter:02d}",
                "area": round(cluster["area"], 2),
                "tilt": round(tilt, 1),
                "azimuth": round(azimuth, 1),
                "source_element": el.Name or el.is_a(),
                "face_count": len(cluster["indices"]),
            }
            all_segments.append(seg)

    # 4 — Summary
    total_parsed = sum(s["area"] for s in all_segments)
    print(f"\n  Parsed {len(all_segments)} segment(s), "
          f"total usable area: {total_parsed:.2f} m²")

    return all_segments


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os

    # Default to the SampleHouse roof if no argument given
    default_ifc = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "00_data", "ifc_models", "Ifc4_SampleHouse_1_Roof.ifc",
    )
    ifc_path = sys.argv[1] if len(sys.argv) > 1 else default_ifc

    print("=" * 62)
    print("  IFC Roof Parser — standalone test")
    print("=" * 62)
    segments = parse_roof_segments(ifc_path)

    if segments:
        print(f"\n  {'ID':>15}  {'Area':>8}  {'Tilt':>6}  {'Azimuth':>8}  Faces")
        print("  " + "-" * 55)
        for s in segments:
            print(
                f"  {s['id']:>15}  "
                f"{s['area']:>7.2f}m²  "
                f"{s['tilt']:>5.1f}°  "
                f"{s['azimuth']:>7.1f}°  "
                f"{s['face_count']}"
            )
    else:
        print("\n  No segments extracted.")
