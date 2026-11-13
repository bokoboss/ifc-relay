"""P1-A safety boundary until real generic landing evidence is available."""
import pytest

from ifc_semantic_service import effective_status
from tests.ifc_factory import Building, semantic_for


@pytest.mark.parametrize("kind", ["undefined_slab", "proxy", "stringer"])
@pytest.mark.parametrize("relationship", ["aggregate", "nest"])
def test_ambiguous_stair_child_does_not_duplicate_walkable_geometry(tmp_path, kind, relationship):
    b = Building([0, 4])
    b.slab([(0, 0), (8, 0), (8, 4), (0, 4)], 0, b.storeys[0])
    stair = b.stair(b.storeys[0])
    b.flight(1, 4, 1, 2, 0, 2, parent=stair)
    b.slab([(4, 1), (6, 1), (6, 3), (4, 3)], 2, None,
           predefined="LANDING", parent=stair)
    overrides = {stair.GlobalId: "include"}
    before = semantic_for(b.write(tmp_path / "before.ifc"), overrides)
    # Overlap both the floor and the explicit landing in separate cases.
    z = 0 if relationship == "nest" else 2
    if kind == "undefined_slab":
        child = b.slab([(4, 1), (6, 1), (6, 3), (4, 3)], z, None,
                       predefined="NOTDEFINED")
    else:
        child = b.box("IfcBuildingElementProxy" if kind == "proxy" else "IfcMember",
                      4, 1, 6, 3, z - .2, z, None)
        if kind == "stringer":
            child.PredefinedType = "STRINGER"
    if relationship == "nest":
        b._run("nest.assign_object", relating_object=stair, related_objects=[child])
    else:
        b._run("aggregate.assign_object", relating_object=stair, products=[child])
    assert effective_status(child, {}) == "review"
    after = semantic_for(b.write(tmp_path / "after.ifc"), overrides)
    for key in ("areas", "levels", "vertical_connections", "obstacles"):
        assert after[key] == before[key], key
    assert not any(child.GlobalId in a.get("ifc_source_global_ids", []) for a in after["areas"])
    if kind == "undefined_slab" and relationship == "aggregate":
        row = next(r for r in after["ifc_semantic"]["landing_ledger"]
                   if r["source_global_id"] == child.GlobalId)
        assert row["outcome"] == "unresolved"
        assert row["reason"] == "selection_review"
