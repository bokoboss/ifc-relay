import json
import re
from pathlib import Path

import fitz


PROJECT_DIR = Path(__file__).resolve().parent
PDF_FILE = PROJECT_DIR / "sample_floorplan_vector.pdf"
REPORT_FILE = PROJECT_DIR / "output" / "pdf_vector_audit_report.json"

SCALE_PATTERN = re.compile(r"SCALE\s*1\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
LEVEL_PATTERN = re.compile(r"LEVEL\s+(\d+)", re.IGNORECASE)


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_FILE}")

    doc = fitz.open(PDF_FILE)
    pages = []

    total_drawings = 0
    total_images = 0

    for page_index, page in enumerate(doc):
        text = page.get_text("text")
        drawings = page.get_drawings()
        images = page.get_images(full=True)

        total_drawings += len(drawings)
        total_images += len(images)

        scale_match = SCALE_PATTERN.search(text)
        level_match = LEVEL_PATTERN.search(text)

        page_record = {
            "page": page_index + 1,
            "width_pt": float(page.rect.width),
            "height_pt": float(page.rect.height),
            "text_chars": len(text),
            "vector_drawings": len(drawings),
            "embedded_images": len(images),
            "scale_denominator": (
                float(scale_match.group(1))
                if scale_match
                else None
            ),
            "level_hint": (
                int(level_match.group(1))
                if level_match
                else None
            ),
            "drawing_types": {},
        }

        drawing_types = {}
        for drawing in drawings:
            for item in drawing.get("items", []):
                code = item[0]
                drawing_types[code] = drawing_types.get(code, 0) + 1

        page_record["drawing_types"] = drawing_types
        pages.append(page_record)

    classification = "vector"
    if total_drawings == 0 and total_images > 0:
        classification = "raster"
    elif total_drawings > 0 and total_images > 0:
        classification = "mixed"
    elif total_drawings == 0 and total_images == 0:
        classification = "text_or_empty"

    report = {
        "source_file": str(PDF_FILE),
        "page_count": len(doc),
        "classification": classification,
        "total_vector_drawings": total_drawings,
        "total_embedded_images": total_images,
        "pages": pages,
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Viswalk PDF Vector Audit v0.1")
    print("=" * 60)
    print("Source:", PDF_FILE)
    print("Pages:", len(doc))
    print("Classification:", classification)
    print("Vector drawings:", total_drawings)
    print("Embedded images:", total_images)

    for page in pages:
        print()
        print(
            f"Page {page['page']}: "
            f"level={page['level_hint']} "
            f"scale=1:{page['scale_denominator']} "
            f"drawings={page['vector_drawings']} "
            f"images={page['embedded_images']}"
        )

    print()
    print("Report:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()
