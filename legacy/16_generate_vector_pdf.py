from pathlib import Path
import math

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_DIR / "sample_floorplan_vector.pdf"

SCALE_DENOMINATOR = 100.0
PAGE_SIZE = landscape(A3)

# Real-world metre -> plotted PDF point at 1:SCALE_DENOMINATOR.
M_TO_PT = (1000.0 / SCALE_DENOMINATOR) * mm

ORIGIN_X = 35.0 * mm
ORIGIN_Y = 35.0 * mm

COLORS = {
    "area": (0.0, 0.55, 0.0),
    "wall": (0.0, 0.0, 0.0),
    "door": (0.10, 0.30, 0.90),
    "column": (0.25, 0.25, 0.25),
    "equipment": (0.95, 0.55, 0.05),
    "vertical_connection": (0.55, 0.20, 0.70),
}


def xy(x_m, y_m):
    return (
        ORIGIN_X + x_m * M_TO_PT,
        ORIGIN_Y + y_m * M_TO_PT,
    )


def draw_area(c, x0, y0, x1, y1):
    r, g, b = COLORS["area"]
    c.setStrokeColorRGB(r, g, b)
    c.setFillColorRGB(1, 1, 1)
    c.setLineWidth(0.8)
    px, py = xy(x0, y0)
    c.rect(
        px,
        py,
        (x1 - x0) * M_TO_PT,
        (y1 - y0) * M_TO_PT,
        stroke=1,
        fill=0,
    )


def draw_wall(c, x1, y1, x2, y2):
    r, g, b = COLORS["wall"]
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(2.0)
    a = xy(x1, y1)
    bpt = xy(x2, y2)
    c.line(a[0], a[1], bpt[0], bpt[1])


def draw_door(c, x1, y1, x2, y2):
    r, g, b = COLORS["door"]
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(2.0)
    a = xy(x1, y1)
    bpt = xy(x2, y2)
    c.line(a[0], a[1], bpt[0], bpt[1])


def draw_rect_fill(c, semantic, cx, cy, width, depth, rotation=0.0):
    r, g, b = COLORS[semantic]
    c.saveState()
    px, py = xy(cx, cy)
    c.translate(px, py)
    c.rotate(rotation)
    c.setFillColorRGB(r, g, b)
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(0.5)
    c.rect(
        -width * M_TO_PT / 2.0,
        -depth * M_TO_PT / 2.0,
        width * M_TO_PT,
        depth * M_TO_PT,
        stroke=1,
        fill=1,
    )
    c.restoreState()


def draw_circle_column(c, cx, cy, diameter):
    r, g, b = COLORS["column"]
    px, py = xy(cx, cy)
    radius = diameter * M_TO_PT / 2.0
    c.setFillColorRGB(r, g, b)
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(0.5)
    c.circle(px, py, radius, stroke=1, fill=1)


def draw_page_header(c, level_no, title):
    page_w, page_h = PAGE_SIZE
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, page_h - 18 * mm, f"LEVEL {level_no} - {title}")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, page_h - 25 * mm, "SCALE 1:100")
    c.drawString(20 * mm, page_h - 31 * mm, "VECTOR PDF INGESTION TEST")



def main():
    c = canvas.Canvas(str(OUTPUT_FILE), pagesize=PAGE_SIZE)
    c.setTitle("Viswalk Vector PDF Ingestion Test")
    c.setAuthor("OpenAI / TR POC")

    # ========================================================
    # PAGE 1 - GROUND FLOOR
    # ========================================================
    draw_page_header(c, 1, "GROUND FLOOR")

    draw_area(c, 0.0, 0.0, 20.0, 15.0)

    draw_wall(c, 2.0, 3.0, 18.0, 3.0)
    draw_wall(c, 6.0, 6.0, 6.0, 13.0)
    draw_door(c, 9.1, 3.0, 10.9, 3.0)

    draw_rect_fill(
        c,
        "column",
        4.0,
        9.0,
        0.60,
        0.40,
        rotation=30.0,
    )
    draw_circle_column(c, 16.0, 9.0, 0.80)

    draw_rect_fill(
        c,
        "equipment",
        14.0,
        11.5,
        2.0,
        1.0,
    )

    draw_rect_fill(
        c,
        "vertical_connection",
        10.0,
        6.0,
        6.0,
        2.0,
    )

    c.showPage()

    # ========================================================
    # PAGE 2 - LEVEL 2
    # ========================================================
    draw_page_header(c, 2, "LEVEL 2")

    draw_area(c, 0.0, 0.0, 20.0, 15.0)
    draw_wall(c, 2.0, 11.0, 18.0, 11.0)
    draw_rect_fill(
        c,
        "column",
        16.0,
        6.0,
        0.60,
        0.60,
        rotation=20.0,
    )

    c.save()

    print("SUCCESS")
    print("Generated vector PDF:")
    print(OUTPUT_FILE)
    print("Pages: 2")
    print("Drawing scale: 1:100")


if __name__ == "__main__":
    main()
