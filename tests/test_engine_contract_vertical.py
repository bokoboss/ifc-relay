from __future__ import annotations

from tests.engine_contract import engine_validate, issue_types, requires_engine
from tests.ifc_factory import Building, semantic_for

H = 3.4


def _floors(b, hole=None):
    b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], 0.0, b.storeys[0])
    if hole is None:
        b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], H, b.storeys[1])
        return
    hx0, hy0, hx1, hy1 = hole
    for poly in ([(0, 0), (12, 0), (12, hy0), (0, hy0)], [(0, hy1), (12, hy1), (12, 8), (0, 8)],
                 [(0, hy0), (hx0, hy0), (hx0, hy1), (0, hy1)], [(hx1, hy0), (12, hy0), (12, hy1), (hx1, hy1)]):
        b.slab(poly, H, b.storeys[1])


@requires_engine
def test_engine_accepts_u_stair_with_landing_level(tmp_path):
    b = Building([0.0, H])
    _floors(b, hole=(2, 1, 7.5, 3.6))
    st = b.stair(b.storeys[0])
    b.flight(2.0, 6.0, 1.0, 2.2, 0.0, H / 2, parent=st)
    b.flight(6.0, 2.0, 2.4, 3.6, H / 2, H, parent=st)
    b.slab([(6, 1), (7.5, 1), (7.5, 3.6), (6, 3.6)], H / 2, None, predefined="LANDING", parent=st)
    v = engine_validate(semantic_for(b.write(tmp_path / "u.ifc"), {st.GlobalId: "include"}), tmp_path)
    assert v["build_allowed"]
    assert v["summary"]["vertical_connections"] == 2
    assert not [t for t in issue_types(v) if t.startswith("vertical_connection")]


@requires_engine
def test_engine_accepts_flight_ending_between_levels(tmp_path):
    b = Building([0.0, H])
    _floors(b)
    fl = b.flight(2.0, 5.0, 1.0, 2.2, 0.0, 1.2, storey=b.storeys[0])
    v = engine_validate(semantic_for(b.write(tmp_path / "p.ifc"), {fl.GlobalId: "include"}), tmp_path)
    assert v["build_allowed"]
    assert v["summary"]["vertical_connections"] == 1
