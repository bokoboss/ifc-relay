from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ifc_geometry_service import extract_ifc_geometry
from ifc_semantic_service import build_semantic_model, write_semantic_model
from ifc_service import audit_ifc, ifcopenshell_version
from revision_service import compare_revisions, report_messages
from project_paths import base_network_path, engine_path, project_root
from state_store import ProjectStateStore
from gate_service import evaluate_gate, gate_message_th, record_ack
from vissim_build_service import build_preflight, build_vissim_model, validate_engine_input


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = project_root()
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_DIR = APP_DIR / "static"
RUNTIME_DIR = APP_DIR / "runtime"
UPLOAD_DIR = RUNTIME_DIR / "uploads"
CACHE_DIR = RUNTIME_DIR / "cache"
SEMANTIC_DIR = RUNTIME_DIR / "semantic"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)

store = ProjectStateStore(RUNTIME_DIR / "project_state.json")

app = FastAPI(
    title="Viswalk AI Model Builder",
    version="0.4.1",
    description=(
        "Large-model IFC Explorer, consolidated semantic geometry generation, "
        "validation, and Vissim/Viswalk COM build workflow."
    ),
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")




class GeometryRequest(BaseModel):
    mode: Literal["simulation_relevant", "full"] = "simulation_relevant"
    storey_ids: list[int] = Field(default_factory=list)
    append: bool = False
    # "core" = everything except review-rule elements (proxies, furniture...), which
    # the browser loads afterwards with "review"; "all" = both at once.
    tier: Literal["all", "core", "review"] = "all"

class ManualEdit(BaseModel):
    kind: Literal["walkable", "obstacle", "passage"]
    level_key: int
    polygon: list[list[float]]
    note: str = ""


class GateAck(BaseModel):
    id: str
    acknowledged: bool = True
    reason: str = ""


class SelectionUpdate(BaseModel):
    global_id: str
    status: Literal["auto", "include", "exclude", "review"]


class BulkSelectionUpdate(BaseModel):
    global_ids: list[str]
    status: Literal["auto", "include", "exclude", "review"]


def safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "upload"


def current_upload_or_404() -> Path:
    state = store.read()
    upload = state.get("upload")
    if not upload:
        raise HTTPException(status_code=404, detail="ยังไม่ได้นำเข้าไฟล์")

    path = Path(upload["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Imported file is missing: {path}")
    return path


# Tessellation (IfcOpenShell geometry iterator) holds the Python GIL for long
# stretches, so running it in the server process stalls every other request
# (e.g. "prepare pedestrian model" waited minutes behind the background
# furniture/proxy load). It runs in worker processes instead.
_GEOMETRY_POOL = None


def extract_geometry_isolated(path: Path, **kwargs: Any) -> dict[str, Any]:
    global _GEOMETRY_POOL
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    if os.environ.get("VBB_GEOMETRY_IN_PROCESS") == "1":
        return extract_ifc_geometry(path, **kwargs)
    for attempt in range(2):
        if _GEOMETRY_POOL is None:
            import multiprocessing

            # "spawn" (the Windows default) everywhere: a forked copy of the running
            # server would inherit uvicorn's state.
            _GEOMETRY_POOL = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"))
        try:
            return _GEOMETRY_POOL.submit(extract_ifc_geometry, path, **kwargs).result()
        except BrokenProcessPool:
            _GEOMETRY_POOL = None
            if attempt:
                raise
    raise RuntimeError("geometry worker unavailable")


def ifc_cache_path(
    path: Path,
    mode: str = "simulation_relevant",
    storey_ids: list[int] | None = None,
    tier: str = "all",
    extra_guids: list[str] | None = None,
) -> Path:
    import hashlib

    token = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)
    storey_token = "all" if not storey_ids else "s" + "-".join(str(int(v)) for v in sorted(set(storey_ids)))
    mode_token = "sim" if mode == "simulation_relevant" else "full"
    tier_token = "" if tier == "all" else f"_{tier}"
    if extra_guids:
        tier_token += "_x" + hashlib.sha1("|".join(sorted(extra_guids)).encode()).hexdigest()[:8]
    return CACHE_DIR / f"{token}_geometry_v041_{mode_token}_{storey_token}{tier_token}.json"


def ifc_semantic_path(path: Path) -> Path:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)
    return SEMANTIC_DIR / f"{token}_geometry_v03.json"


def current_semantic_path_or_404() -> Path:
    state = store.read()
    semantic = state.get("semantic") or {}
    path_text = semantic.get("path")
    if not path_text:
        raise HTTPException(status_code=404, detail="ยังไม่ได้เตรียมโมเดลคนเดิน")
    path = Path(path_text)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Semantic model file is missing: {path}")
    return path


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    vendor_three = STATIC_DIR / "vendor" / "three.module.js"
    vendor_core = STATIC_DIR / "vendor" / "three.core.js"
    vendor_orbit = STATIC_DIR / "vendor" / "jsm" / "controls" / "OrbitControls.js"

    return {
        "status": "ok",
        "app_version": "0.4.1",
        "python": sys.version.split()[0],
        "ifcopenshell": ifcopenshell_version(),
        "three_vendor_ready": (
            vendor_three.exists() and vendor_core.exists() and vendor_orbit.exists()
        ),
        "project_root": str(PROJECT_ROOT),
        "vissim_engine_found": engine_path().exists(),
        "vissim_engine_path": str(engine_path()),
        "base_network_found": base_network_path().exists(),
        "build_adapter_found": (APP_DIR / "vissim_build_adapter.py").exists(),
    }


@app.get("/api/project")
def get_project() -> dict[str, Any]:
    return store.read()


@app.post("/api/project/reset")
def reset_project() -> dict[str, Any]:
    store.reset()
    return {"status": "ok", "message": "Local project state reset."}


@app.post("/api/import")
async def import_file(
    file: UploadFile = File(...),
    carry_selection: bool = Form(True),
) -> dict[str, Any]:
    original = safe_filename(file.filename or "upload")
    suffix = Path(original).suffix.lower()

    if suffix != ".ifc":
        raise HTTPException(
            status_code=400,
            detail="รองรับเฉพาะไฟล์ .ifc ในเวอร์ชันนี้ (การนำเข้า PDF/DXF ยังอยู่ระหว่างพัฒนา)",
        )

    token = uuid.uuid4().hex[:10]
    target = UPLOAD_DIR / f"{token}_{original}"
    limit = int(float(os.environ.get("VBB_MAX_UPLOAD_MB", "2048")) * 1024 * 1024)
    size = 0
    try:
        with open(target, "wb") as fh:
            while chunk := await file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413,
                                        detail=f"ไฟล์ใหญ่เกิน {limit // (1024 * 1024)} MB (ตั้งค่า VBB_MAX_UPLOAD_MB ได้)")
                fh.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="ไฟล์ที่นำเข้าว่างเปล่า")
    content_size = size

    # Carry review decisions from the previous IFC import (matched by GlobalId
    # during Analyze). The previous upload file is kept for the revision diff.
    previous = store.read()
    previous_upload = previous.get("upload") or {}
    previous_overrides = dict(((previous.get("selection") or {}).get("overrides")) or {})
    carry = (
        carry_selection
        and suffix == ".ifc"
        and previous_upload.get("extension") == ".ifc"
        and bool(previous_overrides)
    )

    state = {
        "schema_version": "0.4.1",
        "upload": {
            "original_name": original,
            "path": str(target),
            "extension": suffix,
            "size_bytes": content_size,
        },
        "analysis": None,
        "geometry": None,
        "selection": {"mode": "auto", "overrides": previous_overrides if carry else {}},
        "revision": (
            {
                "status": "pending",
                "previous_upload": previous_upload,
                "previous_decisions": len(previous_overrides),
            }
            if carry
            else None
        ),
        "semantic": None,
        "build": {"status": "not_ready"},
        # Plan edits follow the selection: kept for a new revision of the same model.
        "manual_edits": (previous.get("manual_edits") or [])
        if carry_selection and suffix == ".ifc" and previous_upload.get("extension") == ".ifc" else [],
    }
    store.write(state)
    return {
        "status": "ok",
        "upload": state["upload"],
        "carried_decisions_pending": len(previous_overrides) if carry else 0,
    }


@app.post("/api/analyze")
def analyze() -> dict[str, Any]:
    path = current_upload_or_404()
    suffix = path.suffix.lower()
    state = store.read()

    if suffix == ".ifc":
        try:
            result = audit_ifc(path)
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"IfcOpenShell is not installed. Run install.bat first. Details: {exc}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"IFC audit failed: {type(exc).__name__}: {exc}",
            )

        revision = state.get("revision") or {}
        if revision.get("status") == "pending":
            previous_path_text = (revision.get("previous_upload") or {}).get("path")
            try:
                carried, report = compare_revisions(
                    Path(previous_path_text) if previous_path_text else None,
                    path,
                    (state.get("selection") or {}).get("overrides", {}),
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Revision carry-over failed: {type(exc).__name__}: {exc}",
                )
            state.setdefault("selection", {"mode": "auto"})["overrides"] = carried
            state["revision"] = report
        if (state.get("revision") or {}).get("status") == "applied":
            result = dict(result)
            result["revision"] = state["revision"]
            result["warnings"] = report_messages(state["revision"]) + list(result.get("warnings") or [])

        state["analysis"] = result
        state["build"] = {
            "status": "ifc_audited",
            "message": "IFC audit complete. Load 3D geometry and review selection.",
        }
        store.write(state)
        return result

    result = {
        "kind": suffix.replace(".", ""),
        "status": "adapter_reserved",
        "message": (
            "PDF/DXF are recognized, but v0.4.1 focuses on large IFC semantic extraction. "
            "Existing POC parsers remain unchanged."
        ),
    }
    state["analysis"] = result
    store.write(state)
    return result


@app.post("/api/ifc/geometry")
def load_ifc_geometry(request: GeometryRequest) -> dict[str, Any]:
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")

    state = store.read()
    if not state.get("analysis"):
        raise HTTPException(status_code=400, detail="ต้องตรวจ IFC ก่อนโหลดโมเดล 3D")

    try:
        result = extract_geometry_isolated(
            path,
            cache_path=ifc_cache_path(path, request.mode, request.storey_ids, request.tier),
            mode=request.mode,
            storey_ids=request.storey_ids,
            tier=request.tier,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"IFC geometry extraction failed: {type(exc).__name__}: {exc}",
        )

    state = reread_state_for(path)
    previous_loaded = set((state.get("geometry") or {}).get("loaded_storey_ids", []))
    requested = {int(v) for v in request.storey_ids}
    loaded_storeys = sorted(previous_loaded | requested) if request.append else sorted(requested)

    state["geometry"] = {
        "status": "loaded",
        "mode": request.mode,
        "append": request.append,
        "loaded_storey_ids": loaded_storeys,
        "element_count": result["element_count"],
        "triangle_count": result.get("triangle_count", 0),
        "mesh_failures": len(result["mesh_failures"]),
    }
    # Loading or adding storeys to the 3D view is viewing only: keep an existing
    # pedestrian model, its validation and any build result (e.g. after a page reload).
    if (state.get("semantic") or {}).get("status") != "ready":
        state["build"] = {
            "status": "ifc_3d_review",
            "message": "Filtered 3D IFC loaded. Review selection before semantic extraction.",
        }
    store.write(state)
    return result


@app.get("/api/revision")
def get_revision() -> dict[str, Any]:
    state = store.read()
    revision = state.get("revision")
    if not revision:
        raise HTTPException(status_code=404, detail="No revision carry-over for the current import.")
    return revision


@app.get("/api/selection")
def get_selection() -> dict[str, Any]:
    state = store.read()
    return state.get("selection") or {"mode": "auto", "overrides": {}}


@app.post("/api/selection")
def update_selection(update: SelectionUpdate) -> dict[str, Any]:
    state = store.read()
    selection = state.setdefault("selection", {"mode": "auto", "overrides": {}})
    overrides = selection.setdefault("overrides", {})

    if update.status == "auto":
        overrides.pop(update.global_id, None)
    else:
        overrides[update.global_id] = update.status

    # Any semantic model generated before this edit is now stale.
    if state.get("semantic"):
        state["semantic"]["stale"] = True
        state["build"] = {
            "status": "selection_changed",
            "message": "Selection changed. Regenerate semantic model before build.",
        }

    store.write(state)
    return {"status": "ok", "selection": selection}


@app.post("/api/selection/bulk")
def bulk_update_selection(update: BulkSelectionUpdate) -> dict[str, Any]:
    state = store.read()
    selection = state.setdefault("selection", {"mode": "auto", "overrides": {}})
    overrides = selection.setdefault("overrides", {})

    for guid in update.global_ids:
        if update.status == "auto":
            overrides.pop(guid, None)
        else:
            overrides[guid] = update.status

    if state.get("semantic"):
        state["semantic"]["stale"] = True
        state["build"] = {
            "status": "selection_changed",
            "message": "Selection changed. Regenerate semantic model before build.",
        }

    store.write(state)
    return {"status": "ok", "selection": selection}


class StairBulkUpdate(BaseModel):
    status: Literal["include", "auto"]


def _stair_overview_for(path: Path, overrides: dict[str, str]) -> dict[str, Any]:
    import ifcopenshell

    from ifc_semantic_service import _parent_map
    from ifc_vertical_service import children_map, stair_overview

    model = ifcopenshell.open(str(path))
    return stair_overview(model, overrides, _parent_map(model), children_map(model))


@app.get("/api/stairs")
def get_stairs() -> dict[str, Any]:
    """Stair/ramp units (parent stairs and stand-alone flights) and their review state."""
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")
    overrides = (store.read().get("selection") or {}).get("overrides", {})
    return _stair_overview_for(path, overrides)


@app.post("/api/stairs/bulk")
def bulk_update_stairs(update: StairBulkUpdate) -> dict[str, Any]:
    """Include all stair/ramp units, or return them to review (auto).

    Units are parent IfcStair/IfcRamp (with their flights) and flights without
    a parent. The semantic builder decomposes a parent into its flights once,
    so a stair is never converted twice. A flight that was excluded
    explicitly stays excluded.
    """
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")
    state = store.read()
    selection = state.setdefault("selection", {"mode": "auto", "overrides": {}})
    overrides = selection.setdefault("overrides", {})
    overview = _stair_overview_for(path, overrides)
    changed = 0
    for unit in overview["units"]:
        guid = unit.get("global_id")
        if not guid or unit["state"] == "exclude":
            continue
        if update.status == "include":
            # Driver plus its flights, so the 3D view and selection summary show
            # them as included. Explicitly excluded flights stay excluded; the
            # semantic builder decomposes a parent once, so nothing is duplicated.
            for g in [guid, *unit.get("flight_global_ids", [])]:
                if overrides.get(g) not in ("include", "exclude"):
                    overrides[g] = "include"
                    changed += 1
        elif update.status == "auto":
            for g in [guid, *unit.get("flight_global_ids", [])]:
                if overrides.get(g) == "include":
                    overrides.pop(g, None)
                    changed += 1
    if changed and state.get("semantic"):
        state["semantic"]["stale"] = True
        state["build"] = {
            "status": "selection_changed",
            "message": "Selection changed. Regenerate semantic model before build.",
        }
    store.write(state)
    return {
        "status": "ok",
        "changed": changed,
        "selection": selection,
        "overview": _stair_overview_for(path, overrides),
    }


@app.post("/api/ifc/semantic")
def generate_ifc_semantic() -> dict[str, Any]:
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")

    state = store.read()
    if (state.get("geometry") or {}).get("status") != "loaded":
        raise HTTPException(status_code=400, detail="ต้องโหลดโมเดล 3D ก่อนเตรียมโมเดลคนเดิน")

    overrides = (state.get("selection") or {}).get("overrides", {})

    try:
        # Semantic generation is authoritative and independent from the browser's
        # lazy-loaded storey subset. Build/cache all simulation-relevant geometry.
        # Review-rule elements (proxies, furniture...) are slow to tessellate and
        # only matter when the engineer included them, so mesh just those.
        included = sorted(g for g, status in overrides.items() if status == "include")
        geometry = extract_geometry_isolated(
            path,
            cache_path=ifc_cache_path(path, "simulation_relevant", [], "core", included),
            mode="simulation_relevant",
            storey_ids=[],
            tier="core",
            extra_guids=included,
        )
        semantic = build_semantic_model(path, geometry, overrides, state.get("manual_edits") or [])
        output_path = ifc_semantic_path(path)
        write_semantic_model(output_path, semantic)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"IFC semantic extraction failed: {type(exc).__name__}: {exc}",
        )

    summary = semantic["ifc_semantic"]["summary"]
    warnings = semantic["ifc_semantic"]["warnings"]

    used_overrides, used_edits = dict(overrides), list(state.get("manual_edits") or [])
    state = reread_state_for(path)
    changed_meanwhile = (dict((state.get("selection") or {}).get("overrides", {})) != used_overrides
                         or list(state.get("manual_edits") or []) != used_edits)

    state["semantic"] = {
        "status": "ready",
        # Selection or plan edits changed while this model was being generated.
        "stale": changed_meanwhile,
        "path": str(output_path),
        "summary": summary,
        "warnings": warnings,
    }
    state["build"] = {
        "status": "semantic_ready",
        "message": (
            "Semantic model ready. Validate, then Build Viswalk through Vissim COM."
        ),
    }
    store.write(state)

    return {
        "status": "ok",
        "summary": summary,
        "warnings": warnings,
        "download_url": "/api/ifc/semantic/download",
        "engine_export_url": "/api/ifc/semantic/export-engine-input",
        "model": semantic,
    }


def current_semantic_path_not_stale() -> Path:
    """Engine-facing exports never hand out a model that no longer matches the
    selection or plan edits (F-03)."""
    path = current_semantic_path_or_404()
    if (store.read().get("semantic") or {}).get("stale", False):
        raise HTTPException(
            status_code=409,
            detail="โมเดลคนเดินไม่ตรงกับการเลือก/การแก้ไขล่าสุด · กด \"เตรียมโมเดลคนเดิน\" อีกครั้งก่อนดาวน์โหลดหรือส่งออก",
        )
    return path


@app.get("/api/ifc/semantic")
def get_ifc_semantic(draft: bool = False) -> dict[str, Any]:
    """The current pedestrian model. A stale model is returned only with
    ``draft=1`` (the UI showing what is on screen) and is then marked stale."""
    path = current_semantic_path_or_404() if draft else current_semantic_path_not_stale()
    model = json.loads(path.read_text(encoding="utf-8"))
    if draft and (store.read().get("semantic") or {}).get("stale", False):
        model["stale"] = True
    return model


@app.get("/api/ifc/semantic/download")
def download_ifc_semantic() -> FileResponse:
    path = current_semantic_path_not_stale()
    return FileResponse(
        path,
        media_type="application/json",
        filename=path.name,
    )


@app.get("/api/ifc/semantic/engine-download")
def download_engine_input() -> FileResponse:
    source = current_semantic_path_not_stale()
    return FileResponse(
        source,
        media_type="application/json",
        filename="geometry_ifc_v03.json",
    )


@app.post("/api/ifc/semantic/export-engine-input")
def export_engine_input() -> dict[str, Any]:
    source = current_semantic_path_not_stale()
    target = PROJECT_ROOT / "geometry_ifc_v03.json"
    shutil.copyfile(source, target)

    state = store.read()
    semantic = state.setdefault("semantic", {})
    semantic["engine_input_path"] = str(target)
    store.write(state)

    return {
        "status": "ok",
        "path": str(target),
        "note": (
            "Existing geometry_v03.json was not overwritten. "
            "This file is ready for validation / Vissim integration in the next milestone."
        ),
    }




def current_build_result_or_404() -> dict[str, Any]:
    state = store.read()
    build = state.get("build") or {}
    result = build.get("result") or {}
    if build.get("status") != "success" or not result:
        raise HTTPException(status_code=404, detail="ยังไม่มีไฟล์ Viswalk ที่สร้างสำเร็จ")
    return result


@app.post("/api/validate")
def validate_current_semantic() -> dict[str, Any]:
    semantic_path = current_semantic_path_or_404()
    state = store.read()
    semantic = state.get("semantic") or {}
    if semantic.get("stale", False):
        raise HTTPException(
            status_code=400,
            detail="โมเดลคนเดินไม่ตรงกับการเลือกล่าสุด · กด \"เตรียมโมเดลคนเดิน\" อีกครั้งก่อนตรวจหรือสร้างไฟล์",
        )

    try:
        result = validate_engine_input(APP_DIR, PROJECT_ROOT, semantic_path)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Geometry Engine validation failed: {type(exc).__name__}: {exc}",
        )

    state["build"] = {
        "status": "validated",
        "validation": result,
        "message": "Geometry Engine validation complete. Build Viswalk is ready.",
    }
    store.write(state)
    return result


def reread_state_for(path: Path) -> dict[str, Any]:
    """Fresh project state after a long job, refusing to write results for a file
    that is no longer the current upload (another import happened meanwhile)."""
    state = store.read()
    if str((state.get("upload") or {}).get("path")) != str(path):
        raise HTTPException(status_code=409, detail="ไฟล์ IFC ถูกเปลี่ยนระหว่างประมวลผล · ผลนี้ถูกยกเลิก")
    return state


def _mark_semantic_stale(state: dict[str, Any], message: str) -> None:
    if state.get("semantic"):
        state["semantic"]["stale"] = True
        state["build"] = {"status": "selection_changed", "message": message}


@app.get("/api/edits")
def list_manual_edits() -> dict[str, Any]:
    return {"edits": store.read().get("manual_edits") or []}


@app.post("/api/edits")
def add_manual_edit(edit: ManualEdit) -> dict[str, Any]:
    from datetime import datetime as _dt

    from manual_edits import validate_edit

    data = edit.model_dump()
    problem = validate_edit(data)
    if problem:
        raise HTTPException(status_code=400, detail=f"แก้ไขบนแปลนไม่ได้: {problem}")
    state = store.read()
    try:
        levels = json.loads(current_semantic_path_or_404().read_text(encoding="utf-8")).get("levels", [])
    except HTTPException:
        levels = []
    level = next((lv for lv in levels if int(lv["key"]) == int(data["level_key"])), None)
    if level is None:
        raise HTTPException(status_code=400, detail="ไม่พบระดับนี้ในโมเดลคนเดินปัจจุบัน · เตรียมโมเดลคนเดินก่อน")
    data["level_z"] = float(level["z"])
    data["level_name"] = level.get("name")
    edits = state.setdefault("manual_edits", [])
    next_no = max([int(str(e.get("id", "E0"))[1:] or 0) for e in edits] + [0]) + 1
    data["id"] = f"E{next_no}"
    data["created_at"] = _dt.now().isoformat(timespec="seconds")
    edits.append(data)
    _mark_semantic_stale(state, "Plan edit added. Regenerate the pedestrian model.")
    store.write(state)
    return {"edit": data, "edits": edits}


@app.delete("/api/edits/{edit_id}")
def delete_manual_edit(edit_id: str) -> dict[str, Any]:
    state = store.read()
    edits = state.get("manual_edits") or []
    kept = [e for e in edits if e.get("id") != edit_id]
    if len(kept) == len(edits):
        raise HTTPException(status_code=404, detail="ไม่พบรายการแก้ไขนี้")
    state["manual_edits"] = kept
    _mark_semantic_stale(state, "Plan edit removed. Regenerate the pedestrian model.")
    store.write(state)
    return {"edits": kept}


class GateNotPassed(Exception):
    def __init__(self, gate: dict[str, Any]):
        super().__init__("engineering gate not passed")
        self.gate = gate


def write_build_manifest(result: dict[str, Any], gate: dict[str, Any], validation: dict[str, Any],
                         upload: dict[str, Any]) -> None:
    """Record what was built, under which gate decisions, next to the .inpx."""
    import hashlib
    from datetime import datetime as _dt

    out = Path(result["output_path"])
    source = Path(upload.get("path", ""))
    sha = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    def _sha(p: Path | None) -> str | None:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p is not None and p.is_file() else None

    semantic_file = current_semantic_path_or_404()
    semantic_model = json.loads(semantic_file.read_text(encoding="utf-8"))
    info = semantic_model.get("ifc_semantic", {})
    manifest = {
        "built_at": _dt.now().isoformat(timespec="seconds"),
        "semantic_model": {"file": semantic_file.name, "sha256": _sha(semantic_file),
                           "schema_version": info.get("schema_version") or semantic_model.get("schema_version")},
        "output_inpx_sha256": _sha(out),
        "geometry_engine": {"file": engine_path().name, "sha256": _sha(engine_path())},
        "manual_edits": [{**e, "status": (info.get("manual_edits_status") or {}).get(str(e.get("id")))}
                         for e in info.get("manual_edits", [])],
        "app_version": "0.4.1",
        "source_ifc": {"name": upload.get("original_name"), "sha256": sha},
        "output_inpx": out.name,
        "engine_severity_counts": validation.get("severity_counts"),
        "engineering_gate": gate,
        "viswalk_verified": False,
        "note": "Geometry checks passed and listed items were acknowledged; the model is not verified "
                "in Viswalk until an engineer checks it there.",
    }
    path = out.with_name(out.stem.replace("_viswalk", "") + "_build_manifest.json")
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    result["manifest_path"] = str(path)


def _gate_passed_quiet(state: dict[str, Any]) -> bool:
    try:
        return bool(_current_gate(state)["passed"])
    except Exception:
        return False


def _current_gate(state: dict[str, Any], validation: dict[str, Any] | None = None) -> dict[str, Any]:
    semantic_path = current_semantic_path_or_404()
    semantic_model = json.loads(semantic_path.read_text(encoding="utf-8"))
    if validation is None:
        build = state.get("build") or {}
        validation = build.get("validation") if build.get("status") in ("validated", "success") else None
    return evaluate_gate(semantic_model, validation, state.get("gate_acks"))


@app.get("/api/gate")
def get_engineering_gate() -> dict[str, Any]:
    state = store.read()
    if (state.get("semantic") or {}).get("stale", False):
        raise HTTPException(status_code=400, detail="โมเดลคนเดินไม่ตรงกับการเลือกล่าสุด · เตรียมโมเดลคนเดินอีกครั้ง")
    return _current_gate(state)


@app.post("/api/gate/ack")
def acknowledge_gate_item(update: GateAck) -> dict[str, Any]:
    state = store.read()
    gate = _current_gate(state)
    item = next((i for i in gate["items"] if i["id"] == update.id), None)
    if item is None or item["policy"] != "ack":
        raise HTTPException(status_code=404, detail="ไม่พบรายการที่ต้องรับทราบนี้ในโมเดลปัจจุบัน")
    try:
        state["gate_acks"] = record_ack(state.get("gate_acks") or {}, item, update.acknowledged, update.reason)
    except ValueError:
        raise HTTPException(status_code=400, detail="รายการนี้ต้องระบุเหตุผลก่อนกดรับทราบ")
    store.write(state)
    return _current_gate(state)


@app.post("/api/build-vissim")
def build_current_semantic_in_vissim() -> dict[str, Any]:
    semantic_path = current_semantic_path_or_404()
    state = store.read()
    semantic = state.get("semantic") or {}
    if semantic.get("stale", False):
        raise HTTPException(
            status_code=400,
            detail="โมเดลคนเดินไม่ตรงกับการเลือกล่าสุด · กด \"เตรียมโมเดลคนเดิน\" อีกครั้งก่อนตรวจหรือสร้างไฟล์",
        )

    upload = state.get("upload") or {}
    source_name = upload.get("original_name", "model.ifc")

    problems = build_preflight(base_network_path())
    if problems:
        raise HTTPException(status_code=409, detail="ยังสร้างไฟล์ไม่ได้: " + " | ".join(problems))

    # Always validate immediately before build; do not trust an older validation state.
    try:
        validation = validate_engine_input(APP_DIR, PROJECT_ROOT, semantic_path)
        gate = _current_gate(state, validation)
        if not gate["passed"]:
            state["build"] = {"status": "validated", "validation": validation,
                              "message": "Engineering gate not passed."}
            store.write(state)
            raise GateNotPassed(gate)
        result = build_vissim_model(APP_DIR, PROJECT_ROOT, semantic_path, source_name)
        write_build_manifest(result, gate, validation, upload)
    except GateNotPassed as exc:
        raise HTTPException(status_code=409, detail="ยังสร้างไฟล์ไม่ได้ · " + gate_message_th(exc.gate))
    except Exception as exc:
        state["build"] = {
            "status": "failed",
            "message": str(exc),
        }
        store.write(state)
        raise HTTPException(
            status_code=500,
            detail=f"Vissim build failed: {type(exc).__name__}: {exc}",
        )

    state["build"] = {
        "status": "success",
        "validation": validation,
        "result": result,
        "message": "Vissim/Viswalk .inpx build completed successfully.",
    }
    store.write(state)

    return {
        "status": "success",
        "validation": validation,
        "result": result,
        "download_url": "/api/build/latest/download",
        "report_url": "/api/build/latest/report",
        "validation_url": "/api/build/latest/validation",
        "log_url": "/api/build/latest/log",
    }


@app.get("/api/build/latest/download")
def download_latest_inpx() -> FileResponse:
    result = current_build_result_or_404()
    path = Path(result["output_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Build output is missing: {path}")
    source_name = (store.read().get("upload") or {}).get("original_name", "model.ifc")
    friendly = f"{Path(source_name).stem}_viswalk.inpx"
    return FileResponse(path, media_type="application/octet-stream", filename=friendly)


@app.get("/api/build/latest/report")
def download_latest_build_report() -> FileResponse:
    result = current_build_result_or_404()
    path = Path(result["report_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Build report is missing: {path}")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/build/latest/validation")
def download_latest_validation() -> FileResponse:
    result = current_build_result_or_404()
    path = Path(result["validation_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Validation report is missing: {path}")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/build/latest/log")
def download_latest_build_log() -> FileResponse:
    result = current_build_result_or_404()
    path = Path(result["log_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Build log is missing: {path}")
    return FileResponse(path, media_type="text/plain", filename=path.name)


@app.post("/api/build/latest/open-folder")
def open_latest_build_folder() -> dict[str, Any]:
    result = current_build_result_or_404()
    folder = Path(result["output_path"]).parent
    if os.name != "nt":
        raise HTTPException(status_code=400, detail="เปิดโฟลเดอร์ผลลัพธ์ได้เฉพาะบน Windows")
    try:
        os.startfile(str(folder))  # type: ignore[attr-defined]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open output folder: {exc}")
    return {"status": "ok", "folder": str(folder)}


@app.get("/api/build-readiness")
def build_readiness() -> dict[str, Any]:
    state = store.read()
    analysis = state.get("analysis") or {}
    geometry = state.get("geometry") or {}
    semantic = state.get("semantic") or {}
    overrides = (state.get("selection") or {}).get("overrides", {})

    semantic_ready = semantic.get("status") == "ready" and not semantic.get("stale", False)

    return {
        "current_input_kind": analysis.get("kind"),
        "ifc_audited": analysis.get("kind") == "ifc" and analysis.get("status") == "audited",
        "ifc_3d_loaded": geometry.get("status") == "loaded",
        "manual_overrides": len(overrides),
        "ifc_semantic_mapping_ready": semantic_ready,
        "semantic_summary": semantic.get("summary"),
        # Prerequisites only. Whether a build is allowed is decided by
        # engineering_gate_passed + build preflight at build time.
        "build_prerequisites_found": semantic_ready and engine_path().exists() and base_network_path().exists(),
        "validation_done": (state.get("build") or {}).get("status") in ("validated", "success"),
        "engineering_gate_passed": _gate_passed_quiet(state) if semantic_ready else False,
        "can_build_current_ifc": (semantic_ready and engine_path().exists() and base_network_path().exists()
                                  and _gate_passed_quiet(state)),
        "next_gate": (
            "Validate semantic geometry, then Build Viswalk through Vissim COM 2025."
        ),
    }
