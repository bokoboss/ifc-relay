"""Real-IFC dry run: everything up to Engine validation, without Vissim.

    verify_vissim.bat -Ifc "D:\\Models\\building.ifc" -SkipBuild [-Redact] [-StairsReviewOnly]

Steps: environment -> import (read-only) -> IFC audit -> geometry extraction
-> semantic conversion -> Geometry Engine validation -> report.md / report.json.

Guarantees
* The source IFC is opened read-only. Its SHA-256 is taken before and after the
  run and the report fails if it changed. No cache or output is written next to
  the IFC.
* Vissim and base_empty.inpx are NOT required. Python packages and the Geometry
  Engine are.
* Passing the Geometry check is not a Viswalk check: the report says so.
* --redact removes the file name, folder paths, project / site / building /
  storey names and element names from report.md / report.json so the report
  can be shared. Unredacted intermediate files (semantic JSON, engine
  validation JSON) are written only to the report's ``_private`` folder.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import re
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from project_paths import BASE_NETWORK_FILE, engine_path, project_root  # noqa: E402

VISWALK_DISCLAIMER = (
    "ผ่านการตรวจ Geometry (Geometry Engine validation) ไม่ได้หมายความว่าผ่านการตรวจความถูกต้องใน Viswalk "
    "ต้องสร้างไฟล์ .inpx และตรวจใน Vissim/Viswalk โดยวิศวกรก่อนนำไปใช้งาน"
)
VISWALK_DISCLAIMER_EN = (
    "Passing the Geometry Engine validation does NOT mean the model is correct in Viswalk. "
    "Build the .inpx and have an engineer check it in Vissim/Viswalk before use."
)

COUNT_TYPES = {
    "storeys": "IfcBuildingStorey",
    "slabs": "IfcSlab",
    "walls": "IfcWall",
    "doors": "IfcDoor",
    "windows": "IfcWindow",
    "openings": "IfcOpeningElement",
    "columns": "IfcColumn",
    "beams": "IfcBeam",
    "stairs": "IfcStair",
    "stair_flights": "IfcStairFlight",
    "ramps": "IfcRamp",
    "ramp_flights": "IfcRampFlight",
    "railings": "IfcRailing",
    "transport_elements": "IfcTransportElement",
    "spaces": "IfcSpace",
    "proxies": "IfcBuildingElementProxy",
}

# Semantic warnings -> category, reason (used for "skipped / not converted").
WARNING_RULES: list[tuple[str, str, str]] = [
    (r"has no cached mesh", "skipped", "ไม่มี mesh จากการแปลง Geometry"),
    (r"produced no (valid 2D )?footprint|produced no usable flight footprint|no usable geometry",
     "skipped", "สร้าง footprint 2D ไม่ได้"),
    (r"not assigned to a building storey|has no storey", "skipped", "ไม่ได้อยู่ในชั้นอาคาร (IfcBuildingStorey)"),
    (r"no semantic mapping", "skipped", "ประเภทนี้ยังไม่มีการแปลงสำหรับการจำลอง"),
    (r"no remaining physical segment", "skipped", "ผนังหายทั้งชิ้นหลังเจาะช่องเปิด"),
    (r"could not be consolidated", "skipped", "รวมพื้นที่เดินไม่ได้"),
    (r"starts and ends on the same level|rises only|ends between levels and the model has no other level",
     "skipped", "บันได/ทางลาดเชื่อมระดับไม่ได้"),
    (r"neither it nor its flights have meshable geometry", "skipped", "บันไดไม่มี Geometry ทั้งตัวแม่และ flight"),
    (r"no IfcRelFillsElement|not hosted by an IfcWall|no usable opening or mesh geometry",
     "skipped", "ประตูไม่มีความสัมพันธ์กับช่องเปิด/ผนัง"),
    (r"look walkable", "review", "ช่องเปิดไม่มีประตูที่ดูเหมือนทางเดิน (ยังปิดไว้)"),
    (r"matches no storey or landing level", "review", "ปลายบันไดไม่ตรงกับระดับชั้น (ใช้ z offset)"),
    (r"is not a straight flight", "review", "บันไดไม่ใช่แนวตรง"),
    (r"differs from floor-slab tops", "review", "ระดับชั้น (Elevation) ไม่ตรงกับผิวพื้น"),
    (r"from its storey floor; merged", "review", "แผ่นพื้นสูงต่างจากระดับชั้น (รวมเข้าพื้นชั้น)"),
    (r"included as its own level \(mezzanine\)", "review", "ชั้นลอยที่ใช้ แยกเป็นระดับของตัวเอง (ต้องมีบันไดเชื่อม)"),
    (r"from its storey floor; left out of level", "review", "แผ่นพื้นต่างระดับมาก (ไม่ใช้เป็นพื้นเดินจนกว่าจะยืนยัน)"),
    (r"IfcTransportElement", "review", "ลิฟต์/บันไดเลื่อน ส่งออกเป็นสิ่งกีดขวางเท่านั้น"),
    (r"span several storeys; copied onto each storey", "info", "ผนัง/เสาสูงหลายชั้น คัดลอกไปทุกชั้นที่ผ่าน"),
    (r"exported without door gaps on the upper storeys", "review", "ผนังหลายชั้น: ชั้นบนไม่มีช่องประตู (ต้องตรวจ)"),
    (r"Connectivity.*: .* cannot be reached", "review", "พื้นที่เดินที่ไปไม่ถึงจากเครือข่ายหลัก"),
    (r"Connectivity.*: stair/ramp", "review", "ปลายบันไดไม่ถึงพื้นที่เดินว่าง"),
    (r"slab-joint gaps", "info", "ช่องว่างเล็กระหว่างแผ่นพื้น (ไม่สร้าง void)"),
    (r"suspicious width", "review", "ความกว้างประตูผิดปกติ"),
    (r"from inferred wall axis", "review", "ช่องเปิดอยู่ห่างแนวผนัง"),
    (r"is not straight and .* have no footprint", "review", "ผนังไม่ตรงและช่องเปิดไม่มี footprint (ปิดไว้)"),
    (r"interior holes; only the outer boundary", "review", "ชานพักมีรูภายใน"),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_warning(text: str) -> tuple[str, str]:
    for pattern, category, reason in WARNING_RULES:
        if re.search(pattern, text):
            return category, reason
    return "other", "อื่น ๆ"


class Step:
    def __init__(self, name: str):
        self.name = name
        self.status = "PASS"
        self.detail = ""
        self.seconds = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.name, "status": self.status, "detail": self.detail, "seconds": round(self.seconds, 2)}


class DryRun:
    def __init__(self, ifc: Path, out_dir: Path, include_stairs: bool, redact: bool):
        self.ifc = ifc
        self.out_dir = out_dir
        self.private = out_dir / "_private"
        self.include_stairs = include_stairs
        self.redact = redact
        self.steps: list[Step] = []
        self.data: dict[str, Any] = {}
        self.secrets: list[str] = []

    # -- helpers ------------------------------------------------------------
    def run_step(self, name: str, fn: Callable[[Step], Any]) -> Any:
        step = Step(name)
        self.steps.append(step)
        t0 = time.perf_counter()
        try:
            result = fn(step)
        except Exception as exc:  # report and stop dependent steps
            step.status = "FAIL"
            step.detail = f"{type(exc).__name__}: {exc}"
            (self.private / "error.log").open("a", encoding="utf-8").write(
                f"--- {name}\n{traceback.format_exc()}\n")
            result = None
        step.seconds = time.perf_counter() - t0
        print(f"[{step.status}] {name} ({step.seconds:.1f} s){' - ' + step.detail if step.detail else ''}")
        return result

    def overall(self) -> str:
        statuses = [s.status for s in self.steps]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"

    # -- steps --------------------------------------------------------------
    def environment(self, step: Step) -> None:
        env: dict[str, Any] = {"python": sys.version.split()[0], "platform": platform.platform()}
        missing = []
        for mod in ("ifcopenshell", "shapely", "numpy"):
            try:
                m = importlib.import_module(mod)
                env[mod] = str(getattr(m, "__version__", getattr(m, "version", "ok")))
            except Exception:
                missing.append(mod)
        engine = engine_path()
        env["engine_found"] = engine.exists()
        env["engine"] = f"{engine.parent.name}/{engine.name}"
        env["base_network_required"] = False
        env["base_network_found"] = (project_root() / BASE_NETWORK_FILE).exists()
        env["vissim_required"] = False
        self.data["environment"] = env
        problems = []
        if missing:
            problems.append("missing packages: " + ", ".join(missing))
        if not engine.exists():
            problems.append(f"Geometry Engine not found: {engine}")
        if problems:
            step.status = "FAIL"
            step.detail = "; ".join(problems)
            raise RuntimeError(step.detail)
        step.detail = f"Python {env['python']}, ifcopenshell {env.get('ifcopenshell')}, engine found"

    def source(self, step: Step) -> None:
        if not self.ifc.exists():
            raise FileNotFoundError(str(self.ifc))
        if self.ifc.suffix.lower() != ".ifc":
            raise ValueError("only .ifc files are supported by the dry run")
        size = self.ifc.stat().st_size
        self.data["source"] = {
            "file_name": self.ifc.name,
            "folder": str(self.ifc.parent),
            "size_mb": round(size / 1_048_576, 2),
            "sha256_before": sha256_of(self.ifc),
        }
        self.secrets += [str(self.ifc.parent), self.ifc.name, self.ifc.stem]
        step.detail = f"{size / 1_048_576:.1f} MB, opened read-only"

    def audit(self, step: Step) -> dict[str, Any]:
        import ifcopenshell
        from ifc_service import audit_ifc

        audit = audit_ifc(self.ifc)
        model = ifcopenshell.open(str(self.ifc))
        counts = {key: len(model.by_type(cls)) for key, cls in COUNT_TYPES.items()}
        for entity in model.by_type("IfcProject") + model.by_type("IfcSite") + model.by_type("IfcBuilding") \
                + model.by_type("IfcBuildingStorey"):
            name = getattr(entity, "Name", None)
            if name and str(name).strip():
                self.secrets.append(str(name).strip())
            long_name = getattr(entity, "LongName", None)
            if long_name and str(long_name).strip():
                self.secrets.append(str(long_name).strip())
        storeys = sorted(
            ({"name": s.get("name"), "elevation_m": s.get("elevation_m"),
              "simulation_meshes": s.get("simulation_mesh_count")}
             for s in audit.get("spatial", {}).get("storeys", [])),
            key=lambda r: (r["elevation_m"] is None, r["elevation_m"] or 0.0),
        )
        self.data["ifc"] = {
            "schema": audit.get("schema"),
            "units": audit.get("units"),
            "counts": counts,
            "products": audit.get("counts", {}).get("products"),
            "rule_counts": {k: audit.get("counts", {}).get(k) for k in ("include", "review", "exclude")},
            "opening_fill_breakdown": audit.get("opening_fill_breakdown"),
            "large_model": {k: audit.get("large_model", {}).get(k) for k in ("detected", "reasons", "structural_like")},
            "audit_warnings": audit.get("warnings", []),
            "storeys": storeys,
        }
        step.detail = (f"{counts['storeys']} storeys, {counts['walls']} walls, {counts['slabs']} slabs, "
                       f"{counts['stairs']} stairs / {counts['stair_flights']} flights")
        return audit

    def geometry(self, step: Step) -> dict[str, Any]:
        from ifc_geometry_service import extract_ifc_geometry

        geom = extract_ifc_geometry(self.ifc, cache_path=None, mode="simulation_relevant")
        failures = geom.get("mesh_failures", [])
        self.data["geometry"] = {
            "mode": "simulation_relevant",
            "candidate_elements": geom.get("candidate_element_count"),
            "meshed_elements": geom.get("element_count"),
            "mesh_failures": len(failures),
            "mesh_failure_samples": [f.get("error") for f in failures[:10]],
            "triangles": geom.get("triangle_count"),
            "categories": geom.get("categories"),
        }
        if failures:
            step.status = "WARN"
        step.detail = (f"{geom.get('element_count')} of {geom.get('candidate_element_count')} elements meshed, "
                       f"{len(failures)} failures, {geom.get('triangle_count')} triangles")
        return geom

    def semantic(self, step: Step, geom: dict[str, Any]) -> Path:
        import ifcopenshell

        from ifc_semantic_service import build_semantic_model, write_semantic_model

        overrides: dict[str, str] = {}
        if self.include_stairs:
            model = ifcopenshell.open(str(self.ifc))
            for cls in ("IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight"):
                for e in model.by_type(cls):
                    if getattr(e, "GlobalId", None):
                        overrides[e.GlobalId] = "include"
        sem = build_semantic_model(self.ifc, geom, overrides)
        path = self.private / "semantic_geometry.json"
        write_semantic_model(path, sem)
        info = sem["ifc_semantic"]
        summary = info["summary"]
        warnings = info["warnings"]
        by_category: dict[str, Counter] = {"skipped": Counter(), "review": Counter(), "info": Counter(), "other": Counter()}
        for w in warnings:
            category, reason = classify_warning(w)
            by_category[category][reason] += 1
        vc = sem.get("vertical_connections", [])
        self.data["semantic"] = {
            "stairs_policy": "include all IfcStair/IfcStairFlight/IfcRamp/IfcRampFlight (dry-run default)"
            if self.include_stairs else "app default: stairs stay review-only",
            "summary": summary,
            "converted": {
                "levels": summary.get("levels"),
                "generated_landing_levels": summary.get("generated_landing_levels", 0),
                "walkable_areas": summary.get("walkable_areas"),
                "obstacles_total": summary.get("physical_wall_segments", 0) + summary.get("columns", 0)
                + summary.get("obstacles", 0),
                "wall_segments": summary.get("physical_wall_segments"),
                "polygon_walls": summary.get("polygon_walls", 0),
                "columns": summary.get("columns"),
                "other_obstacles": summary.get("obstacles"),
                "void_masks": summary.get("walkable_void_masks"),
                "vertical_connections": summary.get("vertical_connections"),
                "vertical_ends_with_offset": summary.get("vertical_ends_with_offset", 0),
                "multi_storey_elements": summary.get("multi_storey_elements", 0),
                "multi_storey_copies": summary.get("multi_storey_copies", 0),
                "door_openings_applied": summary.get("door_openings_applied"),
                "unfilled_openings": summary.get("unfilled_openings", 0),
                "unfilled_passage_candidates": summary.get("unfilled_passage_candidates", 0),
                "off_level_slabs_left_out": summary.get("off_level_slabs_excluded", 0),
                "isolated_walking_zones": summary.get("isolated_zones", 0),
                "stairs_not_linked": summary.get("stairs_not_linked", 0),
            },
            "not_converted_by_reason": dict(by_category["skipped"]),
            "review_items_by_reason": dict(by_category["review"]),
            "info_by_reason": dict(by_category["info"]),
            "other_warnings": dict(by_category["other"]),
            "warnings": warnings,
            "vertical_connections": [
                {k: v.get(k) for k in ("key", "type", "start_level", "end_level", "start_z_offset",
                                       "end_z_offset", "rise", "steps", "level_match")}
                for v in vc
            ],
            "key_ranges": info.get("key_ranges"),
        }
        skipped = sum(by_category["skipped"].values())
        if warnings:
            step.status = "WARN"
        step.detail = (f"{summary.get('walkable_areas')} areas, {summary.get('physical_wall_segments')} wall segments, "
                       f"{summary.get('vertical_connections')} vertical connections, {skipped} not converted, "
                       f"{len(warnings)} warnings")
        return path

    def engine(self, step: Step, sem_path: Path) -> None:
        from vissim_build_service import validate_engine_input

        result = validate_engine_input(APP_DIR, project_root(), sem_path)
        (self.private / "engine_validation.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        counts = result.get("severity_counts", {})
        issues = [i for i in result.get("issues", [])]
        by_type = Counter((i.get("severity"), i.get("type")) for i in issues)
        self.data["engine_validation"] = {
            "engine_version": result.get("engine_version"),
            "build_allowed": result.get("build_allowed"),
            "summary": result.get("summary"),
            "severity_counts": counts,
            "issues_by_type": [{"severity": s, "type": t, "count": n} for (s, t), n in by_type.most_common()],
            "issue_samples": issues[:30],
        }
        try:
            sem = json.loads(sem_path.read_text(encoding="utf-8"))
            self.data["engine_validation"]["breakdown"] = engine_issue_breakdown(issues, sem)
        except Exception as exc:  # noqa: BLE001 - report must still be written
            self.data["engine_validation"]["breakdown_error"] = str(exc)
        if not result.get("build_allowed", False) or counts.get("error", 0):
            step.status = "FAIL"
        elif counts.get("warning", 0):
            step.status = "WARN"
        step.detail = (f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} "
                       f"info={counts.get('info', 0)}; {result.get('summary', {}).get('vissim_obstacles')} Vissim obstacles")

    def unchanged(self, step: Step) -> None:
        after = sha256_of(self.ifc)
        before = self.data["source"]["sha256_before"]
        self.data["source"]["sha256_after"] = after
        self.data["source"]["unchanged"] = after == before
        if after != before:
            step.status = "FAIL"
            step.detail = "SOURCE IFC CHANGED DURING THE RUN"
        else:
            step.detail = "SHA-256 identical before and after"

    # -- run ----------------------------------------------------------------
    def run(self) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.private.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()

        def stopped() -> bool:
            return bool(self.steps) and self.steps[-1].status == "FAIL"

        self.run_step("Environment (Python packages, Geometry Engine)", self.environment)
        if not stopped():
            self.run_step("Import source IFC (read-only)", self.source)
        if not stopped():
            self.run_step("IFC audit", self.audit)
        geom = None
        if not stopped():
            geom = self.run_step("Geometry extraction (simulation-relevant)", self.geometry)
        sem_path = None
        if geom is not None and not stopped():
            sem_path = self.run_step("Semantic conversion (pedestrian model)", lambda s: self.semantic(s, geom))
        if sem_path is not None and not stopped():
            self.run_step("Geometry Engine validation", lambda s: self.engine(s, sem_path))
        if "source" in self.data:
            self.run_step("Source IFC unchanged", self.unchanged)
        self.data["total_seconds"] = round(time.perf_counter() - started, 2)
        return self.overall()

    # -- report -------------------------------------------------------------
    def _scrub(self, obj: Any) -> Any:
        if not self.redact:
            return obj
        secrets = sorted({s for s in self.secrets if s and len(s) >= 3}, key=len, reverse=True)

        def scrub_text(text: str) -> str:
            # Keep IFC class names intact (a building called "Building" must not turn
            # IfcBuildingStorey into Ifc[redacted]Storey).
            kept: list[str] = []

            def keep(m: re.Match) -> str:
                kept.append(m.group(0))
                return f"\x00{len(kept) - 1}\x00"

            text = re.sub(r"\bIfc[A-Z][A-Za-z]*", keep, text)
            for secret in secrets:
                text = text.replace(secret, "[redacted]")
            return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)

        if isinstance(obj, str):
            return scrub_text(obj)
        if isinstance(obj, list):
            return [self._scrub(v) for v in obj]
        if isinstance(obj, dict):
            return {k: self._scrub(v) for k, v in obj.items()}
        return obj

    def report(self, overall: str) -> Path:
        data = json.loads(json.dumps(self.data, default=str))
        if self.redact:
            src = data.get("source", {})
            src["file_name"] = f"IFC-{src.get('sha256_before', '')[:8]}.ifc"
            src["folder"] = "[redacted]"
            for i, storey in enumerate(data.get("ifc", {}).get("storeys", []), start=1):
                storey["name"] = f"Storey {i}"
            data = self._scrub(data)
        payload = {
            "tool": "IFC Relay - real IFC dry run",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "overall": overall,
            "redacted": self.redact,
            "disclaimer": VISWALK_DISCLAIMER,
            "disclaimer_en": VISWALK_DISCLAIMER_EN,
            "steps": [s.as_dict() for s in self.steps],
            **data,
        }
        if self.redact:
            payload["steps"] = self._scrub(payload["steps"])
        (self.out_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md = self.out_dir / "report.md"
        md.write_text(render_markdown(payload), encoding="utf-8")
        (self.private / "README.txt").write_text(
            "Unredacted intermediate files. Do not share: they may contain project names.\n", encoding="utf-8")
        return md


def _table(rows: list[tuple[Any, ...]], header: tuple[str, ...]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |")
    return out


OUTSIDE_BANDS = ((0.10, "< 10 % (edge contact)"), (0.90, "10-90 % (straddles floor edge)"),
                 (1.01, "> 90 % (outside floor / no slab)"))
SLAB_OFFSET_RE = re.compile(r"Floor slab \S+ top \(([-\d.]+) m\) is ([-+\d.]+) m from its storey floor; (merged into|left out of) level (\d+)")


def _obstacle_index(sem: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """key -> {kind, global_id, level, area} for every obstacle the engine sees (no names: safe to redact)."""
    import math

    from shapely.geometry import Polygon

    index: dict[int, dict[str, Any]] = {}
    for kind, items in (("wall", sem.get("walls", [])), ("column", sem.get("columns", [])),
                        ("obstacle", sem.get("obstacles", []))):
        for rec in items:
            area = None
            try:
                if rec.get("polygon"):
                    area = Polygon(rec["polygon"]).area
                elif rec.get("start") and rec.get("end"):
                    area = math.dist(rec["start"], rec["end"]) * float(rec.get("thickness") or 0)
                elif rec.get("shape") == "circle":
                    area = math.pi * (float(rec.get("diameter") or 0) / 2) ** 2
                elif rec.get("width") is not None:
                    area = float(rec["width"]) * float(rec.get("depth") or 0)
            except Exception:  # noqa: BLE001 - diagnostics only
                area = None
            label = rec.get("type") if kind == "obstacle" else kind
            index[int(rec["key"])] = {"kind": label, "global_id": rec.get("ifc_global_id"),
                                      "level": rec.get("level_key"), "area": area}
    return index


def engine_issue_breakdown(issues: list[dict[str, Any]], sem: dict[str, Any], samples: int = 25) -> dict[str, Any]:
    """Group engine warnings by obstacle kind, level and how much lies outside the walkable floor."""
    idx = _obstacle_index(sem)
    outside = [i for i in issues if i.get("type") == "obstacle_outside_walkable"]
    by_band: Counter = Counter()
    by_kind_band: Counter = Counter()
    by_level: Counter = Counter()
    rows = []
    for i in outside:
        o = idx.get(int(i.get("key", -1)), {})
        area = o.get("area") or 0.0
        frac = min(1.0, float(i.get("outside_area_m2") or 0) / area) if area > 0 else None
        band = next((b for lim, b in OUTSIDE_BANDS if frac is not None and frac < lim), "unknown")
        by_band[band] += 1
        by_kind_band[(o.get("kind", "?"), band)] += 1
        by_level[i.get("level_key")] += 1
        rows.append({"severity": i.get("severity"), "kind": o.get("kind"), "global_id": o.get("global_id"),
                     "level": i.get("level_key"), "outside_m2": round(float(i.get("outside_area_m2") or 0), 3),
                     "outside_pct": None if frac is None else round(frac * 100)})
    rows.sort(key=lambda r: (-(r["outside_pct"] or 0), -r["outside_m2"]))
    overlaps = [i for i in issues if i.get("type") == "obstacle_overlap"]
    by_pair: Counter = Counter()
    pair_rows = []
    for i in overlaps:
        objs = [idx.get(int(k), {}) for k in i.get("objects", [])]
        pair = " + ".join(sorted(str(o.get("kind", "?")) for o in objs))
        by_pair[pair] += 1
        pair_rows.append({"pair": pair, "level": i.get("level_key"),
                          "global_ids": [o.get("global_id") for o in objs],
                          "overlap_m2": round(float(i.get("overlap_area_m2") or i.get("area_m2") or 0), 3)})
    return {
        "outside_by_band": dict(by_band),
        "outside_by_kind": [{"kind": k, "band": b, "count": n} for (k, b), n in sorted(by_kind_band.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))],
        "outside_by_level": dict(sorted(by_level.items(), key=lambda kv: (kv[0] is None, kv[0]))),
        "outside_samples": rows[:samples],
        "overlap_by_pair": dict(by_pair.most_common()),
        "overlap_samples": pair_rows[:samples],
    }


def group_semantic_warnings(warnings: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Collapse repeated slab-offset warnings into one row per level/offset; return (groups, remaining)."""
    groups: dict[tuple[int, str], dict[str, Any]] = {}
    rest = []
    for w in warnings:
        m = SLAB_OFFSET_RE.search(w)
        if not m:
            rest.append(w)
            continue
        action = "merged" if m.group(3) == "merged into" else "left out"
        key = (int(m.group(4)), m.group(2), action)
        g = groups.setdefault(key, {"level": key[0], "offset_m": float(m.group(2)), "slab_top_m": float(m.group(1)),
                                    "action": action, "slabs": 0})
        g["slabs"] += 1
    return sorted(groups.values(), key=lambda g: (g["level"], g["offset_m"], g["action"])), rest


def render_markdown(p: dict[str, Any]) -> str:
    src, ifc, geo, sem, eng = (p.get(k, {}) for k in ("source", "ifc", "geometry", "semantic", "engine_validation"))
    L = [
        "# IFC Relay - IFC check (dry run, no Vissim)",
        "",
        f"**Overall: {p['overall']}** · generated {p['generated']} · total {p.get('total_seconds', '?')} s"
        + (" · redacted" if p.get("redacted") else ""),
        "",
        f"> {p['disclaimer']}",
        ">",
        f"> {p['disclaimer_en']}",
        "",
        "## Steps",
        "",
    ]
    L += _table([(s["step"], f"**{s['status']}**", s["seconds"], s["detail"]) for s in p["steps"]],
                ("Step", "Result", "Seconds", "Detail"))
    if src:
        L += ["", "## Source", "",
              f"- File: `{src.get('file_name')}` ({src.get('size_mb')} MB)",
              f"- SHA-256: `{src.get('sha256_before')}`" + ("" if src.get("unchanged", True) else " **CHANGED**"),
              f"- Unchanged after run: {src.get('unchanged')}"]
    if ifc:
        c = ifc.get("counts", {})
        L += ["", "## IFC content", "",
              f"Schema {ifc.get('schema')} · length unit {(ifc.get('units') or {}).get('length_symbol')} "
              f"(x{(ifc.get('units') or {}).get('scale_to_meters')} to m) · {ifc.get('products')} products · "
              f"large model: {(ifc.get('large_model') or {}).get('detected')}", ""]
        L += _table([(k, c.get(k)) for k in COUNT_TYPES], ("Element", "Count"))
        rc = ifc.get("rule_counts", {})
        L += ["", f"Default mapping rules: include {rc.get('include')} · review {rc.get('review')} · exclude {rc.get('exclude')}"]
        if ifc.get("storeys"):
            L += ["", "### Storeys", ""]
            L += _table([(s["name"], s["elevation_m"], s["simulation_meshes"]) for s in ifc["storeys"]],
                        ("Storey", "Elevation (m)", "Simulation meshes"))
        if ifc.get("audit_warnings"):
            L += ["", "### Audit warnings", ""] + [f"- {w}" for w in ifc["audit_warnings"]]
    if geo:
        L += ["", "## Geometry extraction", "",
              f"{geo.get('meshed_elements')} of {geo.get('candidate_elements')} candidate elements meshed · "
              f"{geo.get('mesh_failures')} failures · {geo.get('triangles')} triangles"]
        if geo.get("mesh_failure_samples"):
            L += [""] + [f"- {e}" for e in geo["mesh_failure_samples"]]
    if sem:
        L += ["", "## Pedestrian model (semantic conversion)", "", f"Stairs: {sem.get('stairs_policy')}", ""]
        L += _table(list(sem.get("converted", {}).items()), ("Converted", "Count"))
        for title, key in (("Not converted / skipped", "not_converted_by_reason"),
                           ("Needs engineering review", "review_items_by_reason"),
                           ("Information", "info_by_reason"),
                           ("Other warnings", "other_warnings")):
            items = sem.get(key) or {}
            if items:
                L += ["", f"### {title}", ""]
                L += _table(sorted(items.items(), key=lambda kv: -kv[1]), ("Reason", "Count"))
        if sem.get("vertical_connections"):
            L += ["", "### Vertical connections", ""]
            L += _table([(v["key"], v["type"], f"{v['start_level']} -> {v['end_level']}",
                          f"{v['start_z_offset']:+.2f} / {v['end_z_offset']:+.2f}", v.get("rise"), v.get("steps"),
                          f"{(v.get('level_match') or {}).get('start')}/{(v.get('level_match') or {}).get('end')}")
                         for v in sem["vertical_connections"]],
                        ("Key", "Type", "Levels", "Offsets (m)", "Rise (m)", "Steps", "Level match"))
            L += ["", "Stair direction is derived from geometry and is **not certified** until checked in Vissim."]
        if sem.get("warnings"):
            try:
                from ifc_semantic_service import OFF_LEVEL_MERGE_MAX
            except Exception:  # noqa: BLE001 - report text only
                OFF_LEVEL_MERGE_MAX = 0.40
            groups, rest = group_semantic_warnings(sem["warnings"])
            L += ["", f"### All semantic warnings ({len(sem['warnings'])})", ""]
            if groups:
                L += [f"Floor slabs whose top differs from the storey floor ({sum(g['slabs'] for g in groups)} slabs). "
                      f"Within {OFF_LEVEL_MERGE_MAX:.2f} m they are merged (steps, sunken wet areas); further away they are "
                      "left out of the walkable floor until included in review (sunscreens, canopies, mezzanines):", ""]
                L += _table([(g["level"], f"{g['offset_m']:+.3f}", g["slab_top_m"], g["slabs"], g["action"]) for g in groups],
                            ("Level", "Offset (m)", "Slab top (m)", "Slabs", "Action"))
                L += [""]
            L += [f"- {w}" for w in rest]
    if eng:
        sc = eng.get("severity_counts", {})
        L += ["", "## Geometry Engine validation", "",
              f"Engine v{eng.get('engine_version')} · build allowed: {eng.get('build_allowed')} · "
              f"errors {sc.get('error', 0)} · warnings {sc.get('warning', 0)} · info {sc.get('info', 0)}", ""]
        L += _table(list((eng.get("summary") or {}).items()), ("Engine model", "Count"))
        if eng.get("issues_by_type"):
            L += ["", "### Issues by type", ""]
            L += _table([(i["severity"], i["type"], i["count"]) for i in eng["issues_by_type"]],
                        ("Severity", "Type", "Count"))
        bd = eng.get("breakdown") or {}
        if bd.get("outside_by_band"):
            L += ["", "### Obstacles outside the walkable floor", "",
                  "Share of each obstacle's footprint that lies outside the walkable area of its own level. "
                  "Small shares are usually walls/columns on the slab edge; large shares mean the obstacle "
                  "sits where that level has no floor (wrong level, shaft, or missing slab).", ""]
            L += _table([(r["kind"], r["band"], r["count"]) for r in bd["outside_by_kind"]],
                        ("Obstacle", "Outside share", "Count"))
            L += ["", "By level: " + ", ".join(f"L{k}: {v}" for k, v in bd["outside_by_level"].items()), "",
                  f"Largest {len(bd['outside_samples'])} (IFC GlobalId, for lookup in the viewer):", ""]
            L += _table([(r["kind"], r["global_id"], r["level"], r["outside_m2"],
                          "?" if r["outside_pct"] is None else f"{r['outside_pct']} %")
                         for r in bd["outside_samples"]],
                        ("Obstacle", "GlobalId", "Level", "Outside (m2)", "Outside share"))
        if bd.get("overlap_by_pair"):
            L += ["", "### Overlapping obstacles", ""]
            L += _table(list(bd["overlap_by_pair"].items()), ("Pair", "Count"))
            L += ["", f"First {len(bd['overlap_samples'])}:", ""]
            L += _table([(r["pair"], r["level"], ", ".join(str(g) for g in r["global_ids"]), r["overlap_m2"])
                         for r in bd["overlap_samples"]],
                        ("Pair", "Level", "GlobalIds", "Overlap (m2)"))
        if eng.get("breakdown_error"):
            L += ["", f"(Warning breakdown unavailable: {eng['breakdown_error']})"]
    env = p.get("environment", {})
    if env:
        L += ["", "## Environment", "",
              f"Python {env.get('python')} · ifcopenshell {env.get('ifcopenshell')} · shapely {env.get('shapely')} · "
              f"engine found {env.get('engine_found')} · Vissim required: no · base_empty.inpx required: no"]
    L += ["", "---", "Unredacted intermediate files (semantic JSON, engine validation) are in `_private/` "
          "next to this report and must not be shared.", ""]
    return "\n".join(L)


def run_ifc_check(ifc: Path, out_dir: Path | None = None, include_stairs: bool = True,
                  redact: bool = False) -> tuple[str, Path]:
    ifc = Path(ifc).expanduser().resolve()
    if out_dir is None:
        label = "redacted" if redact else re.sub(r"[^A-Za-z0-9._-]+", "_", ifc.stem)[:40] or "ifc"
        out_dir = project_root() / "output" / f"ifc_check_{label}_{datetime.now():%Y%m%d_%H%M%S}"
    run = DryRun(ifc, Path(out_dir), include_stairs=include_stairs, redact=redact)
    print("IFC Relay - real IFC check (no Vissim)")
    print("=" * 64)
    overall = run.run()
    md = run.report(overall)
    print("=" * 64)
    print("RESULT:", overall)
    print("Report:", md)
    print(VISWALK_DISCLAIMER_EN)
    return overall, md


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Real IFC dry run (no Vissim)")
    ap.add_argument("ifc")
    ap.add_argument("--out")
    ap.add_argument("--redact", action="store_true")
    ap.add_argument("--stairs-review-only", action="store_true")
    a = ap.parse_args()
    result, _ = run_ifc_check(Path(a.ifc), Path(a.out) if a.out else None, not a.stairs_review_only, a.redact)
    raise SystemExit(1 if result == "FAIL" else 0)
