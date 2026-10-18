from pathlib import Path
import math
import ezdxf


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_DIR / "sample_floorplan_realistic_mm.dxf"


def add_closed_lwpolyline(msp, points, layer):
    return msp.add_lwpolyline(
        points,
        close=True,
        dxfattribs={"layer": layer},
    )


def ensure_layer(doc, name):
    if name not in doc.layers:
        doc.layers.add(name=name)


def main():
    doc = ezdxf.new("R2010", setup=True)

    # DXF unit = millimeter
    doc.units = ezdxf.units.MM

    msp = doc.modelspace()

    layers = [
        "VW_AREA_L1",
        "VW_WALL_L1",
        "VW_DOOR_L1",
        "VW_COLUMN_L1",
        "VW_EQUIPMENT_L1",
        "VW_STAIR_L1",
        "VW_AREA_L2",
        "VW_WALL_L2",
        "VW_COLUMN_L2",
    ]

    for layer in layers:
        ensure_layer(doc, layer)

    # ========================================================
    # LEVEL 1 - 20 m x 15 m, but DXF coordinates are mm
    # ========================================================

    add_closed_lwpolyline(
        msp,
        [
            (0, 0),
            (20000, 0),
            (20000, 15000),
            (0, 15000),
        ],
        "VW_AREA_L1",
    )

    # --------------------------------------------------------
    # Double-line horizontal wall, 200 mm thickness
    # Centerline should become y = 3000 mm
    # --------------------------------------------------------

    msp.add_line(
        (2000, 2900),
        (18000, 2900),
        dxfattribs={"layer": "VW_WALL_L1"},
    )

    msp.add_line(
        (2000, 3100),
        (18000, 3100),
        dxfattribs={"layer": "VW_WALL_L1"},
    )

    # --------------------------------------------------------
    # Single centerline wall
    # --------------------------------------------------------

    msp.add_line(
        (6000, 6000),
        (6000, 13000),
        dxfattribs={"layer": "VW_WALL_L1"},
    )

    # --------------------------------------------------------
    # Curved wall ARC
    # radius 2 m
    # --------------------------------------------------------

    msp.add_arc(
        center=(15000, 8000),
        radius=2000,
        start_angle=90,
        end_angle=180,
        dxfattribs={"layer": "VW_WALL_L1"},
    )

    # --------------------------------------------------------
    # Door block
    # A simple line in layer 0, inserted on VW_DOOR_L1.
    # Block name contains DOOR => parser forces semantic.
    # Local geometry width 1800 mm.
    # --------------------------------------------------------

    door_block = doc.blocks.new(name="DOOR_SINGLE_1800")
    door_block.add_line(
        (-900, 0),
        (900, 0),
        dxfattribs={"layer": "0"},
    )

    msp.add_blockref(
        "DOOR_SINGLE_1800",
        insert=(10000, 3000),
        dxfattribs={"layer": "VW_DOOR_L1"},
    )

    # --------------------------------------------------------
    # Rotated rectangular column block
    # 600 x 400 mm, rotated 30 deg
    # --------------------------------------------------------

    col_block = doc.blocks.new(name="COLUMN_RECT_600x400")
    add_closed_lwpolyline(
        col_block,
        [
            (-300, -200),
            (300, -200),
            (300, 200),
            (-300, 200),
        ],
        "0",
    )

    msp.add_blockref(
        "COLUMN_RECT_600x400",
        insert=(4000, 9000),
        dxfattribs={
            "layer": "VW_COLUMN_L1",
            "rotation": 30.0,
        },
    )

    # Circular column
    msp.add_circle(
        center=(16000, 9000),
        radius=400,
        dxfattribs={"layer": "VW_COLUMN_L1"},
    )

    # --------------------------------------------------------
    # Equipment
    # --------------------------------------------------------

    add_closed_lwpolyline(
        msp,
        [
            (13000, 11000),
            (15000, 11000),
            (15000, 12000),
            (13000, 12000),
        ],
        "VW_EQUIPMENT_L1",
    )

    # --------------------------------------------------------
    # Stair footprint from L1 -> L2
    # --------------------------------------------------------

    add_closed_lwpolyline(
        msp,
        [
            (7000, 5000),
            (13000, 5000),
            (13000, 7000),
            (7000, 7000),
        ],
        "VW_STAIR_L1",
    )

    # ========================================================
    # LEVEL 2
    # ========================================================

    add_closed_lwpolyline(
        msp,
        [
            (0, 0),
            (20000, 0),
            (20000, 15000),
            (0, 15000),
        ],
        "VW_AREA_L2",
    )

    # L2 wall
    msp.add_line(
        (2000, 11000),
        (18000, 11000),
        dxfattribs={"layer": "VW_WALL_L2"},
    )

    # L2 rotated column represented directly as polygon
    angle = math.radians(20.0)
    cx, cy = 16000, 6000
    hw, hd = 300, 300

    corners = [
        (-hw, -hd),
        ( hw, -hd),
        ( hw,  hd),
        (-hw,  hd),
    ]

    rotated = []

    for x, y in corners:
        rx = x * math.cos(angle) - y * math.sin(angle)
        ry = x * math.sin(angle) + y * math.cos(angle)

        rotated.append(
            (cx + rx, cy + ry)
        )

    add_closed_lwpolyline(
        msp,
        rotated,
        "VW_COLUMN_L2",
    )

    doc.saveas(OUTPUT_FILE)

    print("SUCCESS")
    print("Generated realistic regression DXF:")
    print(OUTPUT_FILE)
    print()
    print("DXF units: millimeters")
    print("Contains:")
    print("  - 2 levels")
    print("  - double-line wall")
    print("  - single-line wall")
    print("  - curved ARC wall")
    print("  - DOOR block/INSERT")
    print("  - rotated COLUMN block")
    print("  - circular column")
    print("  - equipment")
    print("  - stair footprint")


if __name__ == "__main__":
    main()
