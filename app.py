from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ifc_geometry_service import EXTRACTOR_VERSION, VIEW_MAX_TRIANGLES, GeometryFailed
import model_jobs
from model_jobs import JobCancelled, JobFailed
from ifc_service import ifcopenshell_version
from revision_service import report_messages
from project_paths import base_network_path, engine_path, project_root
from state_store import ProjectStateStore
from vissim_com import describe as vissim_describe
from version import APP_VERSION, PROJECT_STATE_VERSION, versions
from gate_service import checklist_ids, checklist_markdown, evaluate_gate, gate_message_th
from vissim_build_service import (build_preflight, build_progress, build_vissim_model, progress_finish,
                                  progress_start, validate_engine_input)


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
    title="IFC Relay",
    version=APP_VERSION,
    description=(
        "IFC → INPX Model Builder: review IFC geometry, refine pedestrian areas and build "
        "an INPX network for PTV Viswalk through Vissim COM (independent tool, not a PTV product)."
    ),
)


# ---- Local API hardening (SEC-01) --------------------------------------------
# The app listens on 127.0.0.1, but any web page open in the same browser can
# still send requests to it. Accept only requests addressed to this machine
# (blocks DNS rebinding) and refuse state changes coming from another site.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"} | {
    h.strip() for h in os.environ.get("VBB_ALLOWED_HOSTS", "").split(",") if h.strip()}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


@app.middleware("http")
async def revalidate_static(request, call_next):
    """The UI files change with every update of the app: the browser must check
    them (cheap 304 when unchanged) instead of running a cached older viewer."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def local_only(request, call_next):
    from fastapi.responses import JSONResponse
    from urllib.parse import urlsplit

    host = _host_only(request.headers.get("host", ""))
    if host not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "IFC Relay accepts requests to this computer only."}, status_code=403)
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin != "null" and _host_only(urlsplit(origin).netloc) not in _LOCAL_HOSTS:
            return JSONResponse({"detail": "Request from another site refused."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Request from another site refused."}, status_code=403)
    return await call_next(request)

def state_transaction(func):
    """Run a short state-changing endpoint as one read-modify-write (F-07)."""
    import functools

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with store.lock:
            return func(*args, **kwargs)
    return wrapper


# One Vissim build at a time: two COM builds would fight over the same Vissim.
BUILD_LOCK = threading.Lock()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")




class GeometryRequest(BaseModel):
    mode: Literal["simulation_relevant", "full"] = "simulation_relevant"
    storey_ids: list[int] = Field(default_factory=list)
    append: bool = False
    # "core" = everything except review-rule elements (proxies, furniture...), which
    # the browser loads afterwards with "review"; "all" = both at once.
    tier: Literal["all", "core", "review"] = "all"

class ManualEdit(BaseModel):
    kind: Literal["walkable", "obstacle", "passage", "exit"]
    level_key: int
    polygon: list[list[float]]
    note: str = ""


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


# Heavy IFC work (audit, tessellation, pedestrian model, stairs) runs as jobs in
# fresh worker processes scheduled against the computer's memory (model_jobs.py):
# the server process never holds a large IFC, and a job that dies is reported.
_perf_log = os.environ.get("VBB_PERF_LOG")          # "" turns the log off (tests)
model_jobs.LOG_PATH = (Path(_perf_log) if _perf_log else None) if _perf_log is not None \
    else RUNTIME_DIR / "logs" / "performance.jsonl"


# The 12,000-element guard protects the browser, which receives every mesh.
# Preparing the pedestrian model runs in a worker process and never sends the
# meshes to the browser, so it gets a much higher, configurable ceiling (PERF-01).
SEMANTIC_MAX_ELEMENTS = int(os.environ.get("VBB_SEMANTIC_MAX_ELEMENTS", "80000"))
# Per request to the 3D view. One storey of a large test model has ~17k
# simulation-relevant elements (818k triangles): 0.9 s to parse and 0.4 s to build
# in the browser, so 12,000 refused a storey the browser handles. Frame rate on a
# real GPU with that many meshes is still to be measured (batching is next).
VIEW_MAX_ELEMENTS = int(os.environ.get("VBB_VIEW_MAX_ELEMENTS", "25000"))

# Cached geometry is keyed by file content, so it is kept across re-imports;
# the oldest files go when the folder grows past this.
CACHE_MAX_MB = int(float(os.environ.get("VBB_CACHE_MAX_GB", "4")) * 1024)


def job_http_error(exc: Exception, what: str) -> HTTPException:
    """409 when the engineer cancelled the job, 500 otherwise."""
    if isinstance(exc, JobCancelled):
        return HTTPException(status_code=409, detail=f"{what}: ยกเลิกแล้ว")
    return HTTPException(status_code=500, detail=job_error_detail(exc, what))


def job_error_detail(exc: Exception, what: str) -> str:
    """Message for a failed heavy job: plain for known causes, technical otherwise."""
    if isinstance(exc, (JobFailed, GeometryFailed)):
        return f"{what}: {exc}"
    return f"{what}: {type(exc).__name__}: {exc}"


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


_SHA_MEMO: dict[tuple[str, int, float], str] = {}


def upload_sha256(path: Path) -> str:
    """SHA-256 of the imported IFC (recorded at import; computed once otherwise)."""
    upload = store.read().get("upload") or {}
    if upload.get("path") == str(path) and upload.get("sha256"):
        return str(upload["sha256"])
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime)
    if key not in _SHA_MEMO:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        _SHA_MEMO[key] = digest.hexdigest()
    return _SHA_MEMO[key]


def prune_geometry_cache(keep: Path | None = None) -> None:
    """Drop the least recently used cached geometry beyond CACHE_MAX_MB."""
    try:
        files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    total = 0
    for p in files:
        try:
            total += p.stat().st_size
        except OSError:
            continue
        if total > CACHE_MAX_MB * 1024 * 1024 and p != keep:
            p.unlink(missing_ok=True)


def ifc_cache_path(
    path: Path,
    mode: str = "simulation_relevant",
    storey_ids: list[int] | None = None,
    tier: str = "all",
    extra_guids: list[str] | None = None,
) -> Path:
    """Cached geometry for one request, keyed by the IFC's content (not the
    upload name), the extractor version and every request condition."""
    sha = upload_sha256(path)
    storey_token = "all" if not storey_ids else "s" + "-".join(str(int(v)) for v in sorted(set(storey_ids)))
    mode_token = "sim" if mode == "simulation_relevant" else "full"
    tier_token = "" if tier == "all" else f"_{tier}"
    if extra_guids:
        tier_token += "_x" + hashlib.sha1("|".join(sorted(extra_guids)).encode()).hexdigest()[:8]
    return CACHE_DIR / f"geo_{sha[:24]}_{EXTRACTOR_VERSION}_{mode_token}_{storey_token}{tier_token}.json"


def ifc_semantic_path(path: Path) -> Path:
    """A new file per generation (ENG-03): a validation or build that started on
    one generation can never be recorded for, or hash, a later one - the
    state's semantic path changes and commit_build_status refuses."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)
    return SEMANTIC_DIR / f"{token}_geometry_v03.{uuid.uuid4().hex[:12]}.json"


SEMANTIC_GENERATIONS_KEPT = 4


def prune_semantic_generations(current: Path) -> None:
    """Keep the newest few generations of this IFC (a build may still read one)."""
    stem = current.name.split("_geometry_v03.")[0]
    older = sorted((p for p in current.parent.glob(f"{stem}_geometry_v03.*.json") if p != current),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in older[SEMANTIC_GENERATIONS_KEPT - 1:]:
        p.unlink(missing_ok=True)


def semantic_download_name(path: Path) -> str:
    return path.name.split("_geometry_v03.")[0] + "_geometry_v03.json"


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


# ---- Vissim release choice (engineer's, kept across projects) -----------------
SETTINGS_FILE = RUNTIME_DIR / "settings.json"
_LAUNCH_PROGID = os.environ.get("VBB_VISSIM_PROGID", "").strip()   # set outside the app wins


def _read_settings() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _apply_vissim_choice(release: int | None) -> None:
    """The adapter reads VBB_VISSIM_PROGID; the build subprocess inherits it."""
    if _LAUNCH_PROGID:
        return
    if release:
        os.environ["VBB_VISSIM_PROGID"] = f"Vissim.Vissim.{int(release)}"
    else:
        os.environ.pop("VBB_VISSIM_PROGID", None)


_apply_vissim_choice(_read_settings().get("vissim_release"))


class VissimChoice(BaseModel):
    release: int | None = None


@app.get("/api/vissim")
def get_vissim() -> dict[str, Any]:
    from vissim_com import registered_releases

    return {**vissim_describe(), "choice": _read_settings().get("vissim_release"),
            "registered": registered_releases(), "fixed_by_environment": bool(_LAUNCH_PROGID)}


@app.post("/api/vissim")
def set_vissim(choice: VissimChoice) -> dict[str, Any]:
    from vissim_com import registered_releases

    if _LAUNCH_PROGID:
        raise HTTPException(status_code=409, detail=f"รุ่น Vissim ถูกกำหนดไว้ตอนเปิดแอป (VBB_VISSIM_PROGID={_LAUNCH_PROGID})")
    if choice.release is not None and choice.release not in registered_releases():
        raise HTTPException(status_code=400, detail=f"ไม่พบ Vissim {choice.release} ที่ลงทะเบียน COM ในเครื่องนี้")
    settings = _read_settings()
    settings["vissim_release"] = choice.release
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    _apply_vissim_choice(choice.release)
    return get_vissim()


@app.get("/api/health")
def health() -> dict[str, Any]:
    vendor_three = STATIC_DIR / "vendor" / "three.module.js"
    vendor_core = STATIC_DIR / "vendor" / "three.core.js"
    vendor_orbit = STATIC_DIR / "vendor" / "jsm" / "controls" / "OrbitControls.js"

    return {
        "status": "ok",
        **versions(),
        **vissim_describe(),
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
@state_transaction
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
    digest = hashlib.sha256()
    try:
        with open(target, "wb") as fh:
            while chunk := await file.read(4 * 1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
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
    with store.lock:
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
            "schema_version": PROJECT_STATE_VERSION,
            "upload": {
                "original_name": original,
                "path": str(target),
                "extension": suffix,
                "size_bytes": content_size,
                "sha256": digest.hexdigest(),
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
            # The audit of the same file content is reused (re-imports, revisions).
            audit_cache = CACHE_DIR / f"audit_{upload_sha256(path)[:24]}_{APP_VERSION}.json"
            if audit_cache.exists():
                result = json.loads(audit_cache.read_text(encoding="utf-8"))
                result["source_file"] = str(path)
            else:
                result, stairs = model_jobs.run("audit", "ifc_vertical_service:audit_with_stairs", path,
                                                files=[path], kind="open")
                write_json_atomic(audit_cache, result)
                write_json_atomic(stair_structure_cache(path), stairs)
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"IfcOpenShell is not installed. Run install.bat first. Details: {exc}",
            )
        except Exception as exc:
            raise job_http_error(exc, "IFC audit failed")

        revision = state.get("revision") or {}
        if revision.get("status") == "pending":
            previous_path_text = (revision.get("previous_upload") or {}).get("path")
            try:
                previous_path = Path(previous_path_text) if previous_path_text else None
                carried, report = model_jobs.run(
                    "revision", "revision_service:compare_revisions",
                    previous_path, path, (state.get("selection") or {}).get("overrides", {}),
                    files=[p for p in (previous_path, path) if p is not None], kind="open",
                )
            except Exception as exc:
                raise job_http_error(exc, "Revision carry-over failed")
            state.setdefault("selection", {"mode": "auto"})["overrides"] = carried
            state["revision"] = report
        if (state.get("revision") or {}).get("status") == "applied":
            result = dict(result)
            result["revision"] = state["revision"]
            result["warnings"] = report_messages(state["revision"]) + list(result.get("warnings") or [])

        with store.lock:
            fresh = reread_state_for(path)
            if revision.get("status") == "pending":       # carry-over computed above
                fresh["revision"] = state["revision"]
                fresh.setdefault("selection", {"mode": "auto"})["overrides"] = state["selection"]["overrides"]
            fresh["analysis"] = result
            fresh["build"] = {
                "status": "ifc_audited",
                "message": "IFC audit complete. Load 3D geometry and review selection.",
            }
            store.write(fresh)
        return result

    result = {
        "kind": suffix.replace(".", ""),
        "status": "adapter_reserved",
        "message": (
            "PDF/DXF are not converted in this version; only IFC is supported. "
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

    cache_path = ifc_cache_path(path, request.mode, request.storey_ids, request.tier)
    # The browser gets a lighter copy (heavy meshes as footprint prisms); the full
    # meshes stay in cache_path for the pedestrian model.
    view_path = cache_path.with_name(cache_path.stem + f"_view{VIEW_MAX_TRIANGLES}.json")
    try:
        result = model_jobs.run(
            "geometry", "ifc_geometry_service:extract_to_cache", path, cache_path, view_path,
            files=[path], kind="geometry",
            title=("โหลด 3D · ชิ้นส่วนรอตรวจ (พื้นหลัง)" if request.tier == "review" else "โหลด 3D")
            + (f" · {len(request.storey_ids)} ชั้น" if request.storey_ids else " · ทั้งอาคาร"),
            mode=request.mode, storey_ids=request.storey_ids, tier=request.tier,
            source_sha256=upload_sha256(path), max_elements=VIEW_MAX_ELEMENTS,
        )
    except ValueError as exc:
        if "safety limit" not in str(exc):
            raise job_http_error(exc, "IFC geometry extraction failed")
        count = re.search(r"contains (\d+)", str(exc))
        raise HTTPException(status_code=413, detail=(
            f"ส่วนที่ขอเปิดมีชิ้นส่วน {count.group(1) if count else 'เกิน'} ชิ้น เกินที่จอ 3D รับได้ต่อครั้ง "
            f"({VIEW_MAX_ELEMENTS:,} ชิ้น) · เลือกเปิดทีละชั้น หรือตั้ง VBB_VIEW_MAX_ELEMENTS ให้สูงขึ้นถ้าเครื่องแรงพอ · "
            "การเตรียมโมเดลคนเดินไม่ได้ใช้ขีดจำกัดนี้"))
    except Exception as exc:
        raise job_http_error(exc, "IFC geometry extraction failed")
    prune_geometry_cache(keep=view_path)

    with store.lock:
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
    # The meshes go to the browser straight from the cache file: the server
    # process never parses them (a 371 MB IFC gives about 140 MB of meshes).
    return FileResponse(view_path, media_type="application/json")


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    """Heavy jobs waiting for memory or running, for the progress panel."""
    return {"jobs": model_jobs.active_jobs()}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not model_jobs.cancel(job_id):
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้ หรืองานจบไปแล้ว")
    return {"status": "cancelling"}


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
@state_transaction
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
@state_transaction
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


def stair_structure_cache(path: Path) -> Path:
    return CACHE_DIR / f"stairs_{upload_sha256(path)[:24]}_{APP_VERSION}.json"


def _stair_overview_for(path: Path, overrides: dict[str, str]) -> dict[str, Any]:
    """Stair/ramp units with the current decisions. The units come from the
    audit's read of the IFC (cached by content), so counting and bulk changes
    do not read the IFC again."""
    from ifc_vertical_service import stair_overview_from_structure

    cache = stair_structure_cache(path)
    try:
        structure = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    except (OSError, ValueError):
        structure = None
    if structure is None:
        try:
            structure = model_jobs.run("stairs", "ifc_vertical_service:stair_structure_for_file", path,
                                       files=[path], kind="open")
        except Exception as exc:
            raise job_http_error(exc, "อ่านรายการบันไดไม่สำเร็จ")
        write_json_atomic(cache, structure)
    return stair_overview_from_structure(structure, overrides)


@app.get("/api/stairs")
def get_stairs() -> dict[str, Any]:
    """Stair/ramp units (parent stairs and stand-alone flights) and their review state."""
    path = current_upload_or_404()
    if path.suffix.lower() != ".ifc":
        raise HTTPException(status_code=400, detail="Current input is not IFC.")
    overrides = (store.read().get("selection") or {}).get("overrides", {})
    return _stair_overview_for(path, overrides)


@app.post("/api/stairs/bulk")
@state_transaction
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
        output_path = ifc_semantic_path(path)
        geometry_cache = ifc_cache_path(path, "simulation_relevant", [], "core", included)
        model_jobs.run(
            "semantic", "ifc_semantic_service:build_semantic_to_file",
            path, output_path, overrides, state.get("manual_edits") or [],
            files=[path], kind="geometry",
            geometry_cache_path=geometry_cache,
            geometry_kwargs={"mode": "simulation_relevant", "storey_ids": [], "tier": "core",
                             "extra_guids": included, "max_elements": SEMANTIC_MAX_ELEMENTS,
                             "source_sha256": upload_sha256(path)},
        )
        semantic = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise job_http_error(exc, "IFC semantic extraction failed")
    prune_geometry_cache(keep=geometry_cache)

    summary = semantic["ifc_semantic"]["summary"]
    warnings = semantic["ifc_semantic"]["warnings"]

    with store.lock:
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
        prune_semantic_generations(output_path)

    return {
        "status": "ok",
        "summary": summary,
        "warnings": warnings,
        "download_url": "/api/ifc/semantic/download",
        "engine_export_url": "/api/ifc/semantic/export-engine-input",
        "model": semantic,
        # UX-25: the selection or plan edits changed while this ran.
        "stale": changed_meanwhile,
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
        filename=semantic_download_name(path),
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
@state_transaction
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

    commit_build_status(semantic_path, {
        "status": "validated",
        "validation": result,
        "message": "Geometry Engine validation complete. Build Viswalk is ready.",
    })
    return result


def reread_state_for(path: Path) -> dict[str, Any]:
    """Fresh project state after a long job, refusing to write results for a file
    that is no longer the current upload (another import happened meanwhile)."""
    state = store.read()
    if str((state.get("upload") or {}).get("path")) != str(path):
        raise HTTPException(status_code=409, detail="ไฟล์ IFC ถูกเปลี่ยนระหว่างประมวลผล · ผลนี้ถูกยกเลิก")
    return state


def commit_build_status(semantic_path: Path, build: dict[str, Any]) -> None:
    """Record a validation/build result on a fresh state, only if it is still about
    the current, non-stale pedestrian model (F-07: no lost update, no result for a
    model that changed while Vissim / the engine ran)."""
    with store.lock:
        state = store.read()
        semantic = state.get("semantic") or {}
        if str(semantic.get("path")) != str(semantic_path) or semantic.get("stale", False):
            raise HTTPException(status_code=409,
                                detail="โมเดลคนเดินถูกเปลี่ยนระหว่างตรวจ/สร้างไฟล์ · ผลนี้ไม่ถูกบันทึก · ตรวจหรือสร้างใหม่อีกครั้ง")
        state["build"] = build
        store.write(state)


def _mark_semantic_stale(state: dict[str, Any], message: str) -> None:
    if state.get("semantic"):
        state["semantic"]["stale"] = True
        state["build"] = {"status": "selection_changed", "message": message}


def edits_with_review(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Plan edits, each with what the last pedestrian-model run did with it."""
    from manual_edits import edit_review_state

    edits = state.get("manual_edits") or []
    semantic = state.get("semantic") or {}
    status: dict[str, Any] = {}
    used: set[tuple[str, str]] = set()
    if semantic.get("path") and Path(semantic["path"]).exists():
        try:
            info = json.loads(Path(semantic["path"]).read_text(encoding="utf-8")).get("ifc_semantic") or {}
            status = info.get("manual_edits_status") or {}
            # id + uid: an id freed by a delete can be given to a new edit
            used = {(str(e.get("id")), str(e.get("uid") or e.get("created_at"))) for e in info.get("manual_edits") or []}
        except (OSError, ValueError):
            status = {}
    out = []
    for edit in edits:
        eid = str(edit.get("id"))
        st = status.get(eid) if (eid, str(edit.get("uid") or edit.get("created_at"))) in used else None
        out.append({**edit, "review": edit_review_state(edit, st)})
    return out


@app.get("/api/edits")
def list_manual_edits() -> dict[str, Any]:
    return {"edits": edits_with_review(store.read())}


@app.post("/api/edits")
@state_transaction
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
    data["uid"] = uuid.uuid4().hex     # ids are reused after a delete; uid is not
    edits.append(data)
    _mark_semantic_stale(state, "Plan edit added. Regenerate the pedestrian model.")
    store.write(state)
    return {"edit": data, "edits": edits_with_review(state)}


@app.delete("/api/edits/{edit_id}")
@state_transaction
def delete_manual_edit(edit_id: str) -> dict[str, Any]:
    state = store.read()
    edits = state.get("manual_edits") or []
    kept = [e for e in edits if e.get("id") != edit_id]
    if len(kept) == len(edits):
        raise HTTPException(status_code=404, detail="ไม่พบรายการแก้ไขนี้")
    state["manual_edits"] = kept
    _mark_semantic_stale(state, "Plan edit removed. Regenerate the pedestrian model.")
    store.write(state)
    return {"edits": edits_with_review(state)}


class GateNotPassed(Exception):
    def __init__(self, gate: dict[str, Any]):
        super().__init__("engineering gate not passed")
        self.gate = gate


def write_build_manifest(result: dict[str, Any], gate: dict[str, Any], validation: dict[str, Any],
                         upload: dict[str, Any], semantic_file: Path) -> None:
    """Record what was built, under which gate decisions, next to the .inpx."""
    import hashlib
    from datetime import datetime as _dt

    out = Path(result["output_path"])
    source = Path(upload.get("path", ""))
    sha = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    def _sha(p: Path | None) -> str | None:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p is not None and p.is_file() else None

    semantic_model = json.loads(semantic_file.read_text(encoding="utf-8"))
    info = semantic_model.get("ifc_semantic", {})
    manifest = {
        "built_at": _dt.now().isoformat(timespec="seconds"),
        "semantic_model": {"file": semantic_file.name, "sha256": _sha(semantic_file),
                           "schema_version": info.get("schema_version") or semantic_model.get("schema_version")},
        "output_inpx_sha256": _sha(out),
        "geometry_engine": {"file": engine_path().name, "sha256": _sha(engine_path())},
        "vissim": vissim_describe(),
        "manual_edits": [{**e, "status": (info.get("manual_edits_status") or {}).get(str(e.get("id")))}
                         for e in info.get("manual_edits", [])],
        **versions(),
        "source_ifc": {"name": upload.get("original_name"), "sha256": sha},
        "output_inpx": out.name,
        "engine_severity_counts": validation.get("severity_counts"),
        "engineering_gate": gate,
        "check_in_viswalk": [{"id": i["id"], "title": i["title"], "count": i["count"]}
                             for i in gate["items"] if i["policy"] == "check"],
        "viswalk_verified": False,
        "note": "The converter built this file; items in check_in_viswalk were known at build time. "
                "The model is not verified until an engineer checks it in Viswalk.",
    }
    stem = out.stem.replace("_viswalk", "")
    path = out.with_name(stem + "_build_manifest.json")
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    result["manifest_path"] = str(path)
    checklist = out.with_name(stem + "_viswalk_checklist.md")
    checklist.write_text(checklist_markdown(gate, str(upload.get("original_name")), out.name, manifest["built_at"]),
                         encoding="utf-8")
    result["checklist_path"] = str(checklist)
    ids = out.with_name(stem + "_checklist_ids.json")
    ids.write_text(json.dumps(checklist_ids(gate), indent=2, ensure_ascii=False), encoding="utf-8")
    result["checklist_ids_path"] = str(ids)


def _gate_passed_quiet(state: dict[str, Any]) -> bool:
    try:
        return bool(_current_gate(state)["passed"])
    except Exception:
        return False


def _current_gate(state: dict[str, Any], validation: dict[str, Any] | None = None,
                  semantic_path: Path | None = None) -> dict[str, Any]:
    semantic_path = semantic_path or current_semantic_path_or_404()
    semantic_model = json.loads(semantic_path.read_text(encoding="utf-8"))
    if validation is None:
        build = state.get("build") or {}
        validation = build.get("validation") if build.get("status") in ("validated", "success") else None
    return evaluate_gate(semantic_model, validation)


@app.get("/api/gate")
def get_engineering_gate() -> dict[str, Any]:
    state = store.read()
    if (state.get("semantic") or {}).get("stale", False):
        raise HTTPException(status_code=400, detail="โมเดลคนเดินไม่ตรงกับการเลือกล่าสุด · เตรียมโมเดลคนเดินอีกครั้ง")
    return _current_gate(state)


@app.post("/api/build-vissim")
def build_current_semantic_in_vissim() -> dict[str, Any]:
    if not BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="กำลังสร้างไฟล์ Viswalk อยู่แล้ว · รอให้เสร็จก่อน")
    progress_start()
    try:
        result = _build_current_semantic_in_vissim()
        progress_finish(True)
        return result
    except HTTPException as exc:
        progress_finish(False, str(exc.detail))
        raise
    except Exception as exc:
        progress_finish(False, str(exc))
        raise
    finally:
        BUILD_LOCK.release()


@app.get("/api/build/progress")
def get_build_progress() -> dict[str, Any]:
    """Where a running build is (stage, items done / total, elapsed time)."""
    return build_progress()


def _build_current_semantic_in_vissim() -> dict[str, Any]:
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
        gate = _current_gate(state, validation, semantic_path)
        if not gate["passed"]:
            commit_build_status(semantic_path, {"status": "validated", "validation": validation,
                                                "message": "Engineering gate not passed."})
            raise GateNotPassed(gate)
        result = build_vissim_model(APP_DIR, PROJECT_ROOT, semantic_path, source_name)
        write_build_manifest(result, gate, validation, upload, semantic_path)
    except GateNotPassed as exc:
        raise HTTPException(status_code=409, detail="ยังสร้างไฟล์ไม่ได้ · " + gate_message_th(exc.gate))
    except HTTPException:
        raise
    except Exception as exc:
        try:
            commit_build_status(semantic_path, {"status": "failed", "message": str(exc)})
        except HTTPException:
            pass            # the model changed meanwhile; the error below still reports it
        raise HTTPException(
            status_code=500,
            detail=f"Vissim build failed: {type(exc).__name__}: {exc}",
        )

    commit_build_status(semantic_path, {
        "status": "success",
        "validation": validation,
        "result": result,
        "message": "Vissim/Viswalk .inpx build completed successfully.",
    })

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


@app.get("/api/build/latest/package")
def download_latest_build_package() -> FileResponse:
    """The .inpx with everything needed to check it in Viswalk, as one ZIP:
    checklist (+ full id list), manifest, validation, engine report, build log."""
    import zipfile

    result = current_build_result_or_404()
    out = Path(result["output_path"])
    if not out.exists():
        raise HTTPException(status_code=404, detail=f"ไม่พบไฟล์ .inpx: {out}")
    keys = ("output_path", "checklist_path", "checklist_ids_path", "manifest_path", "validation_path",
            "report_path", "log_path")
    files = [Path(result[k]) for k in keys if result.get(k) and Path(result[k]).exists()]
    package = out.with_name(out.stem.replace("_viswalk", "") + "_package.zip")
    tmp = package.with_name(package.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    os.replace(tmp, package)
    return FileResponse(package, media_type="application/zip", filename=package.name)


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
            "Validate semantic geometry, then Build Viswalk through Vissim COM."
        ),
    }
