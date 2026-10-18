from __future__ import annotations

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
from state_store import ProjectStateStore
from vissim_build_service import build_vissim_model, validate_engine_input


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
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
        raise HTTPException(status_code=404, detail="No file has been imported.")

    path = Path(upload["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Imported file is missing: {path}")
    return path


def ifc_cache_path(
    path: Path,
    mode: str = "simulation_relevant",
    storey_ids: list[int] | None = None,
) -> Path:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)
    storey_token = "all" if not storey_ids else "s" + "-".join(str(int(v)) for v in sorted(set(storey_ids)))
    mode_token = "sim" if mode == "simulation_relevant" else "full"
    return CACHE_DIR / f"{token}_geometry_v041_{mode_token}_{storey_token}.json"


def ifc_semantic_path(path: Path) -> Path:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)
    return SEMANTIC_DIR / f"{token}_geometry_v03.json"


def current_semantic_path_or_404() -> Path:
    state = store.read()
    semantic = state.get("semantic") or {}
    path_text = semantic.get("path")
    if not path_text:
        raise HTTPException(status_code=404, detail="Semantic model has not been generated.")
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
        "vissim_engine_found": (PROJECT_ROOT / "05_geometry_engine_v03.py").exists(),
        "base_network_found": (PROJECT_ROOT / "base_empty.inpx").exists(),
        "build_adapter_found": (APP_DIR / "40_vissim_build_adapter_v04.py").exists(),
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

    if suffix not in {".ifc", ".pdf", ".dxf"}:
        raise HTTPException(
            status_code=400,
            detail="Supported inputs in MVP v0.4.1: .ifc, .pdf, .dxf",
        )

    token = uuid.uuid4().hex[:10]
    target = UPLOAD_DIR / f"{token}_{original}"
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    target.write_bytes(content)

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
            "size_bytes": len(content),
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
                detail=f"IfcOpenShell is not installed. Run setup_app.ps1 first. Details: {exc}",
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
        raise HTTPException(status_code=400, detail="Run IFC Analyze before loading 3D geometry.")

    try:
        result = extract_ifc_geometry(
            path,
            cache_path=ifc_cache_path(path, request.mode, request.storey_ids),
            mode=request.mode,
            storey_ids=request.storey_ids,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"IFC geometry extraction failed: {type(exc).__name__}: {exc}",
        )

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


@app.post("/api/ifc/semantic")
def generate_ifc_semantic() -> dict[str, Any]:
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")

    state = store.read()
    if (state.get("geometry") or {}).get("status") != "loaded":
        raise HTTPException(status_code=400, detail="Load IFC 3D geometry before semantic extraction.")

    overrides = (state.get("selection") or {}).get("overrides", {})

    try:
        # Semantic generation is authoritative and independent from the browser's
        # lazy-loaded storey subset. Build/cache all simulation-relevant geometry.
        geometry = extract_ifc_geometry(
            path,
            cache_path=ifc_cache_path(path, "simulation_relevant", []),
            mode="simulation_relevant",
            storey_ids=[],
        )
        semantic = build_semantic_model(path, geometry, overrides)
        output_path = ifc_semantic_path(path)
        write_semantic_model(output_path, semantic)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"IFC semantic extraction failed: {type(exc).__name__}: {exc}",
        )

    summary = semantic["ifc_semantic"]["summary"]
    warnings = semantic["ifc_semantic"]["warnings"]

    state["semantic"] = {
        "status": "ready",
        "stale": False,
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


@app.get("/api/ifc/semantic")
def get_ifc_semantic() -> dict[str, Any]:
    path = current_semantic_path_or_404()
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/ifc/semantic/download")
def download_ifc_semantic() -> FileResponse:
    path = current_semantic_path_or_404()
    return FileResponse(
        path,
        media_type="application/json",
        filename=path.name,
    )


@app.get("/api/ifc/semantic/engine-download")
def download_engine_input() -> FileResponse:
    source = current_semantic_path_or_404()
    return FileResponse(
        source,
        media_type="application/json",
        filename="geometry_ifc_v03.json",
    )


@app.post("/api/ifc/semantic/export-engine-input")
def export_engine_input() -> dict[str, Any]:
    source = current_semantic_path_or_404()
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
        raise HTTPException(status_code=404, detail="No successful Viswalk build is available.")
    return result


@app.post("/api/validate")
def validate_current_semantic() -> dict[str, Any]:
    semantic_path = current_semantic_path_or_404()
    state = store.read()
    semantic = state.get("semantic") or {}
    if semantic.get("stale", False):
        raise HTTPException(
            status_code=400,
            detail="Semantic model is stale because selection changed. Generate Semantic Model again.",
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


@app.post("/api/build-vissim")
def build_current_semantic_in_vissim() -> dict[str, Any]:
    semantic_path = current_semantic_path_or_404()
    state = store.read()
    semantic = state.get("semantic") or {}
    if semantic.get("stale", False):
        raise HTTPException(
            status_code=400,
            detail="Semantic model is stale because selection changed. Generate Semantic Model again.",
        )

    upload = state.get("upload") or {}
    source_name = upload.get("original_name", "model.ifc")

    # Always validate immediately before build; do not trust an older validation state.
    try:
        validation = validate_engine_input(APP_DIR, PROJECT_ROOT, semantic_path)
        if not validation.get("build_allowed", False):
            raise RuntimeError("Validation reported blocking errors.")
        result = build_vissim_model(APP_DIR, PROJECT_ROOT, semantic_path, source_name)
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
        raise HTTPException(status_code=400, detail="Open output folder is available only on Windows.")
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
        "can_build_current_ifc": semantic_ready and (PROJECT_ROOT / "05_geometry_engine_v03.py").exists() and (PROJECT_ROOT / "base_empty.inpx").exists(),
        "next_gate": (
            "Validate semantic geometry, then Build Viswalk through Vissim COM 2025."
        ),
    }
