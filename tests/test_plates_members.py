"""ENG-01: curtain-wall glazing (IfcPlate) and its frame (IfcMember) block
walking like PTV's own BIM import does; plates that are floors or overhead do not."""
from __future__ import annotations

from tests.ifc_factory import Building, semantic_for


def _box(b, ifc_class, x0, y0, x1, y1, z0, z1, parent):
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return b.mesh_element(ifc_class, verts, faces, parent=parent)


def test_curtain_wall_plates_and_members_become_obstacles(tmp_path):
    b = Building([0.0, 4.0])
    l1 = b.storeys[0]
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    cw = b._run("root.create_entity", ifc_class="IfcCurtainWall", name="Glass partition")
    b._run("spatial.assign_container", relating_structure=l1, products=[cw])
    glass = _box(b, "IfcPlate", 10.0, 0.0, 10.02, 10.0, 0.0, 3.0, cw)          # full-height glazing
    mullion = _box(b, "IfcMember", 9.97, 4.9, 10.05, 5.1, 0.0, 3.0, cw)         # frame
    deck = _box(b, "IfcPlate", 2.0, 2.0, 4.0, 4.0, -0.01, 0.0, None)            # plate lying in the floor
    canopy = _box(b, "IfcPlate", 2.0, 6.0, 4.0, 8.0, 2.8, 2.82, None)           # overhead
    for el in (deck, canopy):
        b._run("spatial.assign_container", relating_structure=l1, products=[el])
    sem = semantic_for(b.write(tmp_path / "cw.ifc"), {})
    ids = {o.get("ifc_global_id") for o in sem.get("obstacles", [])}
    assert glass.GlobalId in ids and mullion.GlobalId in ids
    assert deck.GlobalId not in ids and canopy.GlobalId not in ids
    assert any("not at walking height" in w for w in sem["ifc_semantic"]["warnings"])


def test_member_outside_curtain_wall_is_review():
    from ifc_service import recommendation
    import ifcopenshell
    f = ifcopenshell.file(schema="IFC4")
    member = f.createIfcMember(ifcopenshell.guid.new())
    plate = f.createIfcPlate(ifcopenshell.guid.new())
    assert recommendation(plate)[0] == "include" and recommendation(plate)[2] == "obstacle"
    assert recommendation(member)[0] == "review"


def test_panels_of_a_multi_storey_curtain_wall_go_to_their_own_storey(tmp_path):
    b = Building([0.0, 4.0])
    l1, l2 = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 4.0, l2)
    cw = b._run("root.create_entity", ifc_class="IfcCurtainWall", name="Facade")
    b._run("spatial.assign_container", relating_structure=l1, products=[cw])      # whole facade on L1
    low = _box(b, "IfcPlate", 10.0, 0.0, 10.02, 10.0, 0.0, 3.0, cw)
    high = _box(b, "IfcPlate", 10.0, 0.0, 10.02, 10.0, 4.0, 7.0, cw)               # stands on L2
    sem = semantic_for(b.write(tmp_path / "f.ifc"), {})
    level = {o["ifc_global_id"]: o["level_key"] for o in sem["obstacles"] if o.get("ifc_global_id")}
    assert level[low.GlobalId] != level[high.GlobalId]
    assert level[high.GlobalId] == max(level.values())


def test_rails_stacked_on_one_footprint_become_one_obstacle(tmp_path):
    b = Building([0.0, 4.0])
    l1 = b.storeys[0]
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    cw = b._run("root.create_entity", ifc_class="IfcCurtainWall", name="Louvres")
    b._run("spatial.assign_container", relating_structure=l1, products=[cw])
    rails = [_box(b, "IfcMember", 10.0, 0.0, 10.05, 10.0, z, z + 0.05, cw) for z in (0.4, 0.5, 0.6, 0.7, 0.8)]
    sem = semantic_for(b.write(tmp_path / "rails.ifc"), {})
    merged = [o for o in sem["obstacles"] if o.get("type") == "IfcMember"]
    assert len(merged) == 1
    assert abs(merged[0]["z_offset"] - 0.4) < 1e-6 and abs(merged[0]["height"] - 0.45) < 1e-6
    assert sorted(merged[0]["ifc_source_global_ids"]) == sorted(r.GlobalId for r in rails)
