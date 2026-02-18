"""Convert IFC to GLB with highlighted failed elements."""

import ifcopenshell
import ifcopenshell.geom
import trimesh
from trimesh.visual.material import PBRMaterial
import numpy as np
import os
import tempfile

# PBR materials for better lighting response
MAT_FAILED = PBRMaterial(
    baseColorFactor=[0.9, 0.15, 0.12, 1.0],
    metallicFactor=0.0,
    roughnessFactor=0.55,
)
MAT_PASSED = PBRMaterial(
    baseColorFactor=[0.82, 0.84, 0.86, 0.3],
    metallicFactor=0.0,
    roughnessFactor=0.7,
    alphaMode="BLEND",
)


def create_highlighted_glb(ifc_path, failed_ids, output_dir=None):
    """Create a GLB file with failed elements in red, passed in gray.

    Returns:
        (glb_path, processed_count, error_count)
    """
    model = ifcopenshell.open(ifc_path)

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    scene = trimesh.Scene()
    processed = 0
    errors = 0

    skip_types = (
        "IfcSite", "IfcBuilding", "IfcBuildingStorey",
        "IfcSpace", "IfcOpeningElement",
    )

    for product in model.by_type("IfcProduct"):
        if any(product.is_a(t) for t in skip_types):
            continue

        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)

            if len(verts) == 0 or len(faces) == 0:
                continue

            mesh = trimesh.Trimesh(vertices=verts, faces=faces)

            if product.GlobalId in failed_ids:
                mesh.visual = trimesh.visual.TextureVisuals(material=MAT_FAILED)
            else:
                mesh.visual = trimesh.visual.TextureVisuals(material=MAT_PASSED)

            scene.add_geometry(mesh, node_name=product.GlobalId)
            processed += 1
        except Exception:
            errors += 1

    if output_dir is None:
        output_dir = tempfile.mkdtemp()

    basename = os.path.splitext(os.path.basename(ifc_path))[0]
    output_path = os.path.join(output_dir, f"{basename}_result.glb")
    scene.export(output_path)

    return output_path, processed, errors
