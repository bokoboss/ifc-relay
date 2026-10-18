from pathlib import Path
from math import pi
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape

OUT = Path(__file__).resolve().parent / 'sample_floorplan_unstyled.pdf'
PAGE_W, PAGE_H = landscape(A3)
SCALE = 100.0
PT_PER_M = 1000.0 / SCALE / 25.4 * 72.0  # 1 m real -> points on paper at scale
OX = 120.0
OY = 120.0


def p(x_m, y_m):
    return OX + x_m * PT_PER_M, OY + y_m * PT_PER_M


def line(c, a, b, width=0.7):
    c.setLineWidth(width)
    c.line(*p(*a), *p(*b))


def rect_m(c, x, y, w, h, width=0.7, fill=0):
    c.setLineWidth(width)
    xx, yy = p(x, y)
    c.rect(xx, yy, w * PT_PER_M, h * PT_PER_M, stroke=1, fill=fill)


def circle_m(c, x, y, r, width=0.7):
    c.setLineWidth(width)
    xx, yy = p(x, y)
    c.circle(xx, yy, r * PT_PER_M, stroke=1, fill=0)


def arc_polyline(c, cx, cy, r, start_deg, end_deg, steps=12, width=0.55):
    from math import cos, sin, radians
    c.setLineWidth(width)
    pts = []
    for i in range(steps + 1):
        a = radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((cx + r * cos(a), cy + r * sin(a)))
    for a, b in zip(pts[:-1], pts[1:]):
        line(c, a, b, width=width)


def draw_common_header(c, level_no):
    c.setFont('Helvetica-Bold', 13)
    c.drawString(40, PAGE_H - 42, f'VECTOR FLOOR PLAN - LEVEL {level_no}')
    c.setFont('Helvetica', 9)
    c.drawString(40, PAGE_H - 58, 'SCALE 1:100')
    c.drawRightString(PAGE_W - 40, PAGE_H - 42, 'VISWALK INTERPRETER TEST')


def draw_floor_boundary(c):
    # 20 m x 15 m walkable/floor boundary
    rect_m(c, 0, 0, 20, 15, width=0.85)


def draw_level1(c):
    draw_common_header(c, 1)
    draw_floor_boundary(c)

    # Main horizontal double-line wall, 0.20 m thick, with 1.80 m door opening.
    y1, y2 = 2.90, 3.10
    for y in (y1, y2):
        line(c, (2.0, y), (9.1, y), width=1.0)
        line(c, (10.9, y), (18.0, y), width=1.0)

    # Door leaf + swing arc in the opening.
    line(c, (9.1, 3.0), (10.9, 3.0), width=0.55)
    arc_polyline(c, 9.1, 3.0, 1.8, 0, 90, steps=10, width=0.45)
    tx, ty = p(9.55, 4.45)
    c.setFont('Helvetica', 6.5)
    c.drawString(tx, ty, 'D01')

    # Vertical double-line wall, 0.20 m thick.
    for x in (5.90, 6.10):
        line(c, (x, 5.0), (x, 13.0), width=1.0)

    # Rectangular and circular columns.
    rect_m(c, 3.7, 8.7, 0.6, 0.6, width=1.0)
    circle_m(c, 16.0, 9.0, 0.40, width=1.0)

    # Equipment with a text clue.
    rect_m(c, 13.0, 11.0, 2.0, 1.0, width=0.8)
    tx, ty = p(13.65, 11.37)
    c.setFont('Helvetica', 6.5)
    c.drawString(tx, ty, 'EQ')

    # Stair bounding box, treads, and UP text.
    rect_m(c, 7.0, 5.0, 6.0, 2.0, width=0.9)
    for i in range(1, 10):
        x = 7.0 + i * 0.6
        line(c, (x, 5.0), (x, 7.0), width=0.35)
    tx, ty = p(9.4, 5.82)
    c.setFont('Helvetica-Bold', 7)
    c.drawString(tx, ty, 'UP')

    # Ambiguous furniture-like rectangle: deliberately unlabeled -> review queue.
    rect_m(c, 2.0, 12.2, 1.4, 0.7, width=0.5)

    # Room text and a dimension-like line to ensure noise is present.
    tx, ty = p(8.2, 13.7)
    c.setFont('Helvetica', 8)
    c.drawString(tx, ty, 'MAIN HALL')
    line(c, (1.0, 14.3), (19.0, 14.3), width=0.25)
    for x in (1.0, 19.0):
        line(c, (x, 14.15), (x, 14.45), width=0.25)
    tx, ty = p(9.45, 14.45)
    c.setFont('Helvetica', 6)
    c.drawString(tx, ty, '18000')


def draw_level2(c):
    draw_common_header(c, 2)
    draw_floor_boundary(c)

    # One horizontal double-line wall.
    for y in (10.90, 11.10):
        line(c, (2.0, y), (18.0, y), width=1.0)

    # One column.
    rect_m(c, 15.7, 5.7, 0.6, 0.6, width=1.0)

    # Room label.
    tx, ty = p(8.0, 7.4)
    c.setFont('Helvetica', 8)
    c.drawString(tx, ty, 'LEVEL 2 HALL')



def main():
    c = canvas.Canvas(str(OUT), pagesize=landscape(A3))
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)

    draw_level1(c)
    c.showPage()
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)
    draw_level2(c)
    c.save()

    print('SUCCESS')
    print(OUT)


if __name__ == '__main__':
    main()
