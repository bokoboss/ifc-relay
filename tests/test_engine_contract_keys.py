from __future__ import annotations

from tests.engine_contract import engine_validate, requires_engine
from tests.ifc_factory import Building, semantic_for


@requires_engine
def test_engine_accepts_more_than_200_wall_segments_plus_columns(tmp_path):
    # v0.4.1a keys: walls 1101+ collided with columns 1301+ beyond 200 walls,
    # which the engine rejects as "Duplicate semantic obstacle key".
    b = Building([0.0])
    b.slab([(0, 0), (60, 0), (60, 60), (0, 60)], 0.0, b.storeys[0])
    for i in range(210):
        x, y = 1 + (i % 15) * 3.8, 1 + (i // 15) * 4.0
        b.box("IfcWall", x, y, x + 3.0, y + 0.2, 0.0, 3.0, b.storeys[0])
    for i in range(5):
        b.box("IfcColumn", 2 + i * 10, 58, 2.4 + i * 10, 58.4, 0.0, 3.0, b.storeys[0])
    sem = semantic_for(b.write(tmp_path / "many.ifc"))
    assert sem["ifc_semantic"]["summary"]["physical_wall_segments"] == 210
    v = engine_validate(sem, tmp_path)
    assert v["summary"]["semantic_obstacles"] == 215
