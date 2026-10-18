from pathlib import Path
import ezdxf


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_DIR / "sample_floorplan.dxf"


LAYERS = {
    "area": "VW_AREA_L1",
    "wall": "VW_WALL_L1",
    "door": "VW_DOOR_L1",
    "column": "VW_COLUMN_L1",
    "equipment": "VW_EQUIPMENT_L1",
}


def add_closed_polyline(msp, points, layer):
    msp.add_lwpolyline(
        points,
        close=True,
        dxfattribs={"layer": layer},
    )


def main():
    doc = ezdxf.new("R2000", setup=True)
    msp = doc.modelspace()

    # Define layers
    for layer_name in LAYERS.values():
        if layer_name not in doc.layers:
            doc.layers.add(name=layer_name)

    # --------------------------------------------------------
    # Walkable area: 20 x 15 m
    # --------------------------------------------------------
    add_closed_polyline(
        msp,
        [
            (0.0, 0.0),
            (20.0, 0.0),
            (20.0, 15.0),
            (0.0, 15.0),
        ],
        LAYERS["area"],
    )

    # --------------------------------------------------------
    # Walls: centerlines
    # Door opening is represented separately on VW_DOOR_L1.
    # --------------------------------------------------------
    msp.add_line(
        (2.0, 3.0),
        (18.0, 3.0),
        dxfattribs={"layer": LAYERS["wall"]},
    )

    msp.add_line(
        (6.0, 6.0),
        (6.0, 13.0),
        dxfattribs={"layer": LAYERS["wall"]},
    )

    # Door line: its midpoint = opening center, length = width.
    msp.add_line(
        (9.1, 3.0),
        (10.9, 3.0),
        dxfattribs={"layer": LAYERS["door"]},
    )

    # --------------------------------------------------------
    # Columns
    # --------------------------------------------------------

    # Rectangular column 0.60 x 0.60 m
    add_closed_polyline(
        msp,
        [
            (3.7, 8.7),
            (4.3, 8.7),
            (4.3, 9.3),
            (3.7, 9.3),
        ],
        LAYERS["column"],
    )

    # Circular column dia. 0.80 m
    msp.add_circle(
        center=(16.0, 9.0),
        radius=0.40,
        dxfattribs={"layer": LAYERS["column"]},
    )

    # --------------------------------------------------------
    # Fixed equipment
    # --------------------------------------------------------
    add_closed_polyline(
        msp,
        [
            (13.0, 11.0),
            (15.0, 11.0),
            (15.0, 12.0),
            (13.0, 12.0),
        ],
        LAYERS["equipment"],
    )

    # Optional labels, ignored by the parser
    msp.add_text(
        "DXF INGESTION TEST",
        height=0.35,
        dxfattribs={"layer": "0"},
    ).set_placement((0.5, 14.2))

    doc.saveas(OUTPUT_FILE)

    print("SUCCESS")
    print("Generated DXF:")
    print(OUTPUT_FILE)

    print()
    print("Layer convention:")
    for key, value in LAYERS.items():
        print(f"  {key:<10} -> {value}")


if __name__ == "__main__":
    main()
