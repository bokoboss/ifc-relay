"""Rotated stairs: Vissim refuses a ramp that is not exactly a rectangle
("Ramp has to be a rectangle"). After writing with 4 decimals the corners of
every stair must still be exactly perpendicular."""
from __future__ import annotations

from decimal import Decimal

import pytest
from shapely.geometry import Polygon

from tests.engine_contract import ENGINE, requires_engine


def _engine():
    from vissim_build_adapter import load_engine
    return load_engine(ENGINE, validate_only=True)


def _exact_corners(text):
    # parse the WKT numbers as decimals: exact, like Vissim reading the string
    body = text[text.rindex("(") + 1:text.index(")")]
    nums = body.replace(",", " ").split()
    pts = [(Decimal(nums[i]), Decimal(nums[i + 1])) for i in range(0, len(nums), 2)][:4]
    return pts


@requires_engine
@pytest.mark.parametrize("deg", [0, 12.3, 30, 42.47, 47.6, 90, 133.1, 200.9, 311.7])
def test_rotated_stair_is_an_exact_rectangle_after_writing(deg):
    import math
    eng = _engine()
    a = math.radians(deg)
    L, W = 3.99538, 1.4125
    x0, y0 = 99.45834, 38.40957
    u = (math.cos(a), math.sin(a)); w = (-math.sin(a), math.cos(a))
    poly = [(x0, y0), (x0 + L * u[0], y0 + L * u[1]),
            (x0 + L * u[0] + W * w[0], y0 + L * u[1] + W * w[1]), (x0 + W * w[0], y0 + W * w[1])]
    rect = eng.exact_rectangle(Polygon(poly))
    pts = _exact_corners(eng.vissim_wkt(rect))
    for i in range(4):
        a_, b_, c_ = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        dot = (b_[0] - a_[0]) * (c_[0] - b_[0]) + (b_[1] - a_[1]) * (c_[1] - b_[1])
        assert dot == 0
    # stays where it was: corners within a few millimetres
    for (px, py), (qx, qy) in zip(poly, list(rect.exterior.coords)[:4]):
        assert math.hypot(px - qx, py - qy) < 0.02


@requires_engine
def test_axis_aligned_stair_is_unchanged():
    eng = _engine()
    poly = Polygon([(-47.35, -4.64), (-46.35, -4.64), (-46.35, -8.1025), (-47.35, -8.1025)])
    rect = eng.exact_rectangle(poly)
    assert rect.symmetric_difference(poly).area < 1e-8
