"""Engineering gate before building the Viswalk file (P0-01).

The Geometry Engine only refuses geometry it cannot build. Many problems that
make a model wrong for pedestrians are warnings there. This gate sorts them
into three policies:

* ``block``  - the build is refused until the model is fixed.
* ``ack``    - the engineer must acknowledge the item before building (some
               items require a written reason); acknowledgements are written to
               the build manifest.
* ``info``   - shown, no action needed.

An acknowledgement is tied to the *identity* of the problems it covers: every
item carries a fingerprint of the objects/places involved (IFC GlobalIds, zone
location, edit ids...) plus the policy version. If a regenerated model has a
different set of problems - even with the same count - the item must be
acknowledged again. Diagnostics that fail are never treated as "no problem".
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from connectivity_service import _footprint

# Share of an obstacle's footprint outside its level's walkable area above which
# the obstacle is treated as standing where that level has no floor.
NO_FLOOR_SHARE = 0.9

POLICY_VERSION = "2026-10-20.2"

# Acknowledging these needs a written reason (the problem makes part of the
# model unusable for pedestrians).
REASON_REQUIRED = {"stairs_not_linked", "isolated_zones"}


def fingerprint(item_id: str, identities: list[str]) -> str:
    payload = json.dumps([POLICY_VERSION, item_id, sorted(identities)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _item(item_id: str, policy: str, identities: list[str], title: str, detail: str,
          count: int | None = None) -> dict[str, Any]:
    ids = sorted({str(i) for i in identities})
    return {
        "id": item_id,
        "policy": policy,
        "count": int(count if count is not None else len(ids)),
        "title": title,
        "detail": detail,
        "fingerprint": fingerprint(item_id, ids),
        "identities": ids[:200],
        "reason_required": item_id in REASON_REQUIRED and policy == "ack",
    }


def _matching(warnings: list[str], pattern: str) -> list[str]:
    rx = re.compile(pattern)
    return [w for w in warnings if rx.search(w)]


def _zone_id(z: dict[str, Any]) -> str:
    c = z.get("centroid") or [0, 0]
    return f"L{z.get('level_key')}@{float(c[0]):.1f},{float(c[1]):.1f}~{round(float(z.get('area_m2', 0)) * 2) / 2}"


def gate_items(semantic: dict[str, Any], validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    info = semantic.get("ifc_semantic", {})
    warnings = info.get("warnings", [])
    con = info.get("connectivity")
    vcs = semantic.get("vertical_connections", [])
    vc_by_key = {int(v["key"]): v for v in vcs if "key" in v}
    items: list[dict[str, Any]] = []

    if validation is None:
        items.append(_item("not_validated", "block", ["not_validated"], "ยังไม่ได้ตรวจสอบโมเดล",
                           'กด "ตรวจสอบโมเดล" ก่อนสร้างไฟล์'))
        issues: list[dict[str, Any]] = []
    else:
        issues = validation.get("issues", [])
        errors = (validation.get("severity_counts") or {}).get("error", 0)
        if errors or not validation.get("build_allowed", False):
            err_ids = [f"{i.get('type')}:{i.get('key', i.get('objects'))}" for i in issues if i.get("severity") == "error"]
            items.append(_item("engine_errors", "block", err_ids or ["build_not_allowed"], "Geometry Engine พบข้อผิดพลาด",
                               "แก้ข้อผิดพลาดของ Engine ก่อน (ดูรายการด้านล่าง)", count=max(errors, 1)))

    off_area = [f"{(vc_by_key.get(int(i.get('key', -1))) or {}).get('ifc_global_id') or i.get('key')}:"
                f"{'start' if 'start' in i.get('type', '') else 'end'}"
                for i in issues if i.get("type") in ("vertical_connection_not_on_start_area",
                                                     "vertical_connection_not_on_end_area")]
    if off_area:
        items.append(_item("ramp_not_on_area", "block", off_area, "ปลายบันได/ทางลาดไม่แตะพื้นที่เดิน",
                           "Viswalk จะใช้บันไดตัวนี้ไม่ได้ · ตรวจระดับชั้นและพื้นที่เดินที่ปลายบันได"))

    # Connectivity: a failed or missing analysis is never read as "all connected".
    if not isinstance(con, dict) or con.get("error") or "zones" not in con:
        reason = con.get("error") if isinstance(con, dict) else "connectivity result missing"
        items.append(_item("connectivity_failed", "block", [str(reason)], "ตรวจการเชื่อมต่อไม่สำเร็จ",
                           f"ระบบวิเคราะห์ทางเดินไม่ได้ ({reason}) · เตรียมโมเดลคนเดินใหม่ หรือแจ้งผู้พัฒนา"))
        con = {}
    loose = [f"{d.get('ifc_global_id') or d.get('key')}:{'bottom' if not d.get('bottom_connected') else 'top'}"
             for d in con.get("stairs_not_linked", [])]
    if loose:
        items.append(_item("stairs_not_linked", "ack", loose, "ปลายบันไดไม่ถึงพื้นที่เดินว่าง",
                           "ปลายบันไดชนผนัง/สิ่งกีดขวาง หรือไม่มีพื้นรองรับ · คนจะใช้บันไดนี้ไม่ได้ · ต้องระบุเหตุผล"))
    zones = [_zone_id(z) for z in con.get("isolated_zones", [])]
    if zones:
        items.append(_item("isolated_zones", "ack", zones,
                           f"พื้นที่ที่เดินไปไม่ถึง ({con.get('isolated_area_m2', 0):.1f} ตร.ม.)",
                           "พื้นที่สีแดงใน 3D · ตรวจประตู/ช่องเปิดหรือบันไดที่ขาด หรือยืนยันว่าเป็นห้องปิด/ช่องท่อ · ต้องระบุเหตุผล"))

    review_dir = [str(v.get("ifc_global_id") or v.get("key")) for v in vcs if v.get("direction_status") == "needs_review"]
    if review_dir:
        items.append(_item("stair_direction_review", "ack", review_dir, "ทิศบันไดหาจาก Geometry ไม่ได้",
                           "ลูกศรสีส้มใน 3D · ตรวจทิศขึ้นของบันไดเหล่านี้ใน Vissim หลังสร้างไฟล์"))
    offsets = [f"{v.get('ifc_global_id') or v.get('key')}:{end}" for v in vcs for end in ("start", "end")
               if (v.get("level_match") or {}).get(end) != "exact"]
    if offsets:
        items.append(_item("stair_end_offset", "ack", offsets, "ปลายบันไดใช้ z offset",
                           "ปลายบันไดไม่ตรงระดับชั้นใด · ตรวจการเชื่อมต่อใน Vissim"))
    left_out = [str(s.get("global_id")) for s in info.get("off_level_slabs", []) if s.get("decision") != "include"]
    if left_out:
        items.append(_item("off_level_left_out", "ack", left_out, "แผ่นพื้นต่างระดับมากที่ยังไม่ใช้เป็นพื้นเดิน",
                           "ยืนยันว่าไม่ใช่พื้นเดิน (เช่นแผงบังแดด กันสาด) หรือติ๊กใช้ในรายการแผ่นพื้นต่างระดับ"))
    doors = [re.search(r"Door (\S+)", w).group(1) if re.search(r"Door (\S+)", w) else w for w in
             _matching(warnings, r"no IfcRelFillsElement|not hosted by an IfcWall|no usable opening or mesh geometry")]
    if doors:
        items.append(_item("doors_not_converted", "ack", doors, "ประตูที่แปลงเป็นช่องเปิดไม่ได้",
                           "ประตูไม่ผูกกับช่องเปิด/ผนังใน IFC · ผนังตรงนั้นยังปิดอยู่ · ใช้ \"เปิดทางผ่าน\" ในแปลน 2D ได้"))
    closed = [str(c.get("global_id")) for c in info.get("opening_candidates", [])
              if c.get("classification") == "passage_candidate" and c.get("decision") != "include"]
    if closed:
        items.append(_item("passages_closed", "ack", closed, "ช่องเปิดที่ดูเหมือนทางเดินแต่ยังปิดไว้",
                           "ติ๊กเปิดช่องที่เป็นทางเดินจริง หรือยืนยันว่าปิดไว้ถูกต้อง"))
    legacy = _matching(warnings, r"multi-storey wall copies are exported without door gaps")
    if legacy:
        n = sum(int(re.match(r"(\d+)", w).group(1)) for w in legacy if re.match(r"(\d+)", w))
        items.append(_item("multi_storey_no_doors", "ack", legacy, "ผนังหลายชั้น: ชั้นบนไม่มีช่องประตู",
                           "ผนังที่คัดลอกขึ้นชั้นบนปิดทึบ · ตรวจว่าชั้นบนมีประตูในแนวผนังนี้หรือไม่", count=n))

    # Manual plan edits: one that could not be applied blocks the build - the
    # engineer drew it on purpose and the model does not contain it.
    edits = info.get("manual_edits") or []
    status = info.get("manual_edits_status") or {}
    skipped = [eid for eid, st in status.items() if st.get("applied") is False]
    if skipped:
        items.append(_item("manual_edits_skipped", "block", skipped, "แก้ไขบนแปลนที่ใช้ไม่ได้",
                           "ระดับของรายการแก้ไขไม่มีในโมเดลนี้ (เช่นหลังนำเข้า IFC ฉบับใหม่) · ลบแล้ววาดใหม่ในระดับที่ถูกต้อง"))
    if edits:
        kinds = {k: sum(1 for e in edits if e.get("kind") == k) for k in ("walkable", "obstacle", "passage")}
        items.append(_item("manual_edits", "info", [str(e.get("id")) for e in edits], "แก้ไขบนแปลนโดยวิศวกร",
                           f"พื้นที่เดินเพิ่ม {kinds['walkable']} · สิ่งกีดขวางเพิ่ม {kinds['obstacle']} · "
                           f"ทางผ่าน {kinds['passage']} · บันทึกใน build manifest"))

    if issues:
        by_key = {int(r["key"]): r for k in ("walls", "columns", "obstacles") for r in semantic.get(k, [])}
        no_floor, edge = [], []
        for i in issues:
            if i.get("type") != "obstacle_outside_walkable":
                continue
            rec = by_key.get(int(i.get("key", -1)))
            geom = _footprint(rec) if rec else None
            share = float(i.get("outside_area_m2") or 0) / geom.area if geom is not None and geom.area > 0 else 0
            ident = f"{(rec or {}).get('ifc_global_id') or (rec or {}).get('manual_edit_id') or i.get('key')}@L{i.get('level_key')}"
            (no_floor if share > NO_FLOOR_SHARE else edge).append(ident)
        if no_floor:
            items.append(_item("obstacles_no_floor", "ack", no_floor, "สิ่งกีดขวางที่ไม่มีพื้นรองรับ",
                               "อยู่นอกพื้นที่เดินของชั้นตัวเองเกือบทั้งชิ้น · อาจอยู่ผิดชั้นหรือขาดแผ่นพื้น",
                               count=len(no_floor)))
        if edge:
            items.append(_item("obstacles_on_edge", "info", edge, "สิ่งกีดขวางคร่อมขอบพื้น",
                               "ผนัง/เสาริมพื้นส่วนใหญ่เป็นแบบนี้ · ตรวจรายการที่ไม่ได้อยู่ริมอาคาร", count=len(edge)))
        overlaps = [",".join(str(o) for o in i.get("objects", [])) for i in issues if i.get("type") == "obstacle_overlap"]
        if overlaps:
            items.append(_item("obstacle_overlaps", "info", overlaps, "สิ่งกีดขวางซ้อนกัน",
                               "มักเป็นผนังที่ต่อกันที่มุม · ถ้าซ้อนกันมากอาจเป็นวัตถุซ้ำหรือการแปลงผิด ให้ตรวจในแปลน 2D",
                               count=len(overlaps)))
    return items


def evaluate_gate(semantic: dict[str, Any], validation: dict[str, Any] | None,
                  acks: dict[str, Any] | None) -> dict[str, Any]:
    acks = acks or {}
    items = gate_items(semantic, validation)
    for item in items:
        ack = acks.get(item["id"])
        item["acknowledged"] = bool(ack) and item["policy"] == "ack" and ack.get("fingerprint") == item["fingerprint"]
        if item["acknowledged"]:
            item["reason"] = ack.get("reason", "")
            item["acknowledged_at"] = ack.get("at")
    blocked = [i["id"] for i in items if i["policy"] == "block"]
    pending = [i["id"] for i in items if i["policy"] == "ack" and not i["acknowledged"]]
    return {
        "policy_version": POLICY_VERSION,
        "items": items,
        "blocked": blocked,
        "pending_acknowledgement": pending,
        "passed": not blocked and not pending,
    }


def record_ack(acks: dict[str, Any], item: dict[str, Any], acknowledged: bool, reason: str = "") -> dict[str, Any]:
    acks = dict(acks or {})
    if acknowledged:
        if item.get("reason_required") and not reason.strip():
            raise ValueError("reason required")
        acks[item["id"]] = {"fingerprint": item["fingerprint"], "count": item["count"],
                            "reason": reason.strip()[:500], "at": datetime.now().isoformat(timespec="seconds")}
    else:
        acks.pop(item["id"], None)
    return acks


def gate_message_th(gate: dict[str, Any]) -> str:
    titles = {i["id"]: i["title"] for i in gate["items"]}
    parts = []
    if gate["blocked"]:
        parts.append("ต้องแก้ก่อน: " + ", ".join(titles[i] for i in gate["blocked"]))
    if gate["pending_acknowledgement"]:
        parts.append("ต้องกดรับทราบ: " + ", ".join(titles[i] for i in gate["pending_acknowledgement"]))
    return " | ".join(parts)
