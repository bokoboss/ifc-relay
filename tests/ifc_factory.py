"""Build small synthetic IFC4 models for regression tests.

All fixtures are generated in code, so they are redistributable and can run in
CI without project BIM files. Coordinates are in metres.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.util.unit


class Building:
    def __init__(self, storey_elevations: Iterable[float]):
        self.f = ifcopenshell.file(schema="IFC4")
        self.project = self._run("root.create_entity", ifc_class="IfcProject", name="Synthetic")
        self._run("unit.assign_unit")
        self.scale = ifcopenshell.util.unit.calculate_unit_scale(self.f)
        model = self._run("context.add_context", context_type="Model")
        self.body = self._run(
            "context.add_context",
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model,
        )
        site = self._run("root.create_entity", ifc_class="IfcSite", name="Site")
        building = self._run("root.create_entity", ifc_class="IfcBuilding", name="Building")
        self._run("aggregate.assign_object", relating_object=self.project, products=[site])
        self._run("aggregate.assign_object", relating_object=site, products=[building])
        self.storeys = []
        for i, z in enumerate(storey_elevations, start=1):
            storey = self._run("root.create_entity", ifc_class="IfcBuildingStorey", name=f"L{i}")
            storey.Elevation = z / self.scale
            self._run("aggregate.assign_object", relating_object=building, products=[storey])
            self.storeys.append(storey)

    def _run(self, usecase: str, **kwargs: Any) -> Any:
        return api.run(usecase, self.f, **kwargs)

    def _place(self, element: Any, rep: Any, z: float = 0.0, storey: Any | None = None) -> Any:
        self._run("geometry.assign_representation", product=element, representation=rep)
        matrix = np.eye(4)
        matrix[2, 3] = z
        self._run("geometry.edit_object_placement", product=element, matrix=matrix)
        if storey is not None:
            self._run("spatial.assign_container", relating_structure=storey, products=[element])
        return element

    def slab(self, polygon, top_z: float, storey: Any | None, predefined: str = "FLOOR",
             depth: float = 0.2, parent: Any | None = None) -> Any:
        slab = self._run("root.create_entity", ifc_class="IfcSlab", predefined_type=predefined)
        rep = self._run("geometry.add_slab_representation", context=self.body, depth=depth, polyline=polygon)
        self._place(slab, rep, z=top_z - depth, storey=storey if parent is None else None)
        if parent is not None:
            self._run("aggregate.assign_object", relating_object=parent, products=[slab])
        return slab

    def mesh_element(self, ifc_class: str, vertices, faces, storey: Any | None = None,
                     parent: Any | None = None, **attrs: Any) -> Any:
        element = self._run("root.create_entity", ifc_class=ifc_class)
        for key, value in attrs.items():
            setattr(element, key, value)
        rep = self._run(
            "geometry.add_mesh_representation",
            context=self.body,
            vertices=[vertices],
            faces=[faces],
        )
        self._place(element, rep, storey=storey if parent is None else None)
        if parent is not None:
            self._run("aggregate.assign_object", relating_object=parent, products=[element])
        return element

    def stair(self, storey: Any, name: str = "Stair") -> Any:
        stair = self._run("root.create_entity", ifc_class="IfcStair", name=name)
        self._run("spatial.assign_container", relating_structure=storey, products=[stair])
        return stair

    def flight(self, x0: float, x1: float, y0: float, y1: float, z_low: float, z_high: float,
               storey: Any | None = None, parent: Any | None = None, **attrs: Any) -> Any:
        """Wedge from (x0, z_low) rising to (x1, z_high); x1 may be < x0."""
        verts = [
            (x0, y0, z_low), (x1, y0, z_low), (x1, y0, z_high),
            (x0, y1, z_low), (x1, y1, z_low), (x1, y1, z_high),
        ]
        faces = [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (0, 2, 5, 3)]
        return self.mesh_element("IfcStairFlight", verts, faces, storey=storey, parent=parent, **attrs)

    def box(self, ifc_class: str, x0, y0, x1, y1, z0, z1, storey: Any | None) -> Any:
        verts = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        return self.mesh_element(ifc_class, verts, faces, storey=storey)

    def write(self, path: Path) -> Path:
        self.f.write(str(path))
        return path


def semantic_for(path: Path, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model

    geometry = extract_ifc_geometry(path)
    assert not geometry["mesh_failures"], geometry["mesh_failures"]
    return build_semantic_model(path, geometry, overrides or {})


def add_wall(b: "Building", x0: float, y: float, length: float, storey: Any,
             height: float = 3.0, thickness: float = 0.2) -> Any:
    """Straight wall along +X from (x0, y), centred on y."""
    wall = b.box("IfcWall", x0, y - thickness / 2, x0 + length, y + thickness / 2, 0.0, height, storey)
    return wall


def add_opening(b: "Building", wall: Any, x0: float, x1: float, y: float,
                z0: float, z1: float, depth: float = 0.4) -> Any:
    """Unfilled IfcOpeningElement cutting ``wall`` between x0..x1, z0..z1."""
    opening = b.box("IfcOpeningElement", x0, y - depth / 2, x1, y + depth / 2, z0, z1, None)
    b._run("feature.add_feature", feature=opening, element=wall)
    return opening
