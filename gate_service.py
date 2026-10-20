"""Engineering gate before building the Viswalk file (P0-01).

The Geometry Engine only refuses geometry it cannot build. Many problems that
make a model wrong for pedestrians are warnings there. This gate sorts them
into three policies:

* ``block``  - the build is refused until the model is fixed.
* ``ack``    - the engineer must acknowledge the item (optionally with a reason)
               before building; acknowledgements are written to the build manifest.
* ``info``   - shown, no action needed.

An acknowledgement is tied to the item's count: if a regenerated model changes
the count, the item has to be acknowledged again.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from connectivity_service import _footprint

# Share of an obstacle's footprint outside its level's walkable area above which
# the obstacle is treated as standing where that level has no floor.
NO_FLOOR_SHARE = 0.9

POLICY_VERSION = "2026-10-20"


def _count_warnings(warnings: list[str], pattern: str) -> int:
    rx = re.compile(pattern)
    return sum(1 for w in warnings if rx.search(w))


def _item(item_id: str, policy: str, count: int, title: str, detail: str) -> dict[str, Any]:
    return {"id": item_id, "policy": policy, "count": int(count), "title": title, "detail": detail}


def gate_items(semantic: dict[str, Any], validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    info = semantic.get("ifc_semantic", {})
    summary = info.get("summary", {})
    warnings = info.get("warnings", [])
    con = info.get("connectivity") or {}
    vcs = semantic.get("vertical_connections", [])
    items: list[dict[str, Any]] = []

    if validation is None:
        items.append(_item("not_validated", "block", 1, "ยังไม่ได้ตรวจสอบโมเดล",
                           'กด "ตรวจสอบโมเดล" ก่อนสร้างไฟล์'))
        issues: list[dict[str, Any]] = []
    else:
        issues = validation.get("issues", [])
        errors = (validation.get("severity_counts") or {}).get("error", 0)
        if errors or not validation.get("build_allowed", False):
            items.append(_item("engine_errors", "block", max(errors, 1), "Geometry Engine พบข้อผิดพลาด",
                               "แก้ข้อผิดพลาดของ Engine ก่อน (ดูรายการด้านล่าง)"))

    off_area = sum(1 for i in issues if i.get("type") in (
        "vertical_connection_not_on_start_area", "vertical_connection_not_on_end_area"))
    if off_area:
        items.append(_item("ramp_not_on_area", "block", off_area, "ปลายบันได/ทางลาดไม่แตะพื้นที่เดิน",
                           "Viswalk จะใช้บันไดตัวนี้ไม่ได้ · ตรวจระดับชั้นและพื้นที่เดินที่ปลายบันได"))

    n = len(con.get("stairs_not_linked", []))
    if n:
        items.append(_item("stairs_not_linked", "ack", n, "ปลายบันไดไม่ถึงพื้นที่เดินว่าง",
                           "ปลายบันไดชนผนัง/สิ่งกีดขวาง หรือไม่มีพื้นรองรับ · คนจะใช้บันไดนี้ไม่ได้"))
    n = len(con.get("isolated_zones", []))
    if n:
        items.append(_item("isolated_zones", "ack", n,
                           f"พื้นที่ที่เดินไปไม่ถึง ({con.get('isolated_area_m2', 0):.1f} ตร.ม.)",
                           "พื้นที่สีแดงใน 3D · ตรวจประตู/ช่องเปิดหรือบันไดที่ขาด หรือยืนยันว่าเป็นห้องปิด/ช่องท่อ"))
    n = sum(1 for v in vcs if v.get("direction_status") == "needs_review")
    if n:
        items.append(_item("stair_direction_review", "ack", n, "ทิศบันไดหาจาก Geometry ไม่ได้",
                           "ลูกศรสีส้มใน 3D · ตรวจทิศขึ้นของบันไดเหล่านี้ใน Vissim หลังสร้างไฟล์"))
    n = sum(1 for v in vcs for end in ("start", "end") if (v.get("level_match") or {}).get(end) != "exact")
    if n:
        items.append(_item("stair_end_offset", "ack", n, "ปลายบันไดใช้ z offset",
                           "ปลายบันไดไม่ตรงระดับชั้นใด · ตรวจการเชื่อมต่อใน Vissim"))
    n = sum(1 for s in info.get("off_level_slabs", []) if s.get("decision") != "include")
    if n:
        items.append(_item("off_level_left_out", "ack", n, "แผ่นพื้นต่างระดับมากที่ยังไม่ใช้เป็นพื้นเดิน",
                           "ยืนยันว่าไม่ใช่พื้นเดิน (เช่นแผงบังแดด กันสาด) หรือติ๊กใช้ในรายการแผ่นพื้นต่างระดับ"))
    n = _count_warnings(warnings, r"no IfcRelFillsElement|not hosted by an IfcWall|no usable opening or mesh geometry")
    if n:
        items.append(_item("doors_not_converted", "ack", n, "ประตูที่แปลงเป็นช่องเปิดไม่ได้",
                           "ประตูไม่ผูกกับช่องเปิด/ผนังใน IFC · ผนังตรงนั้นยังปิดอยู่"))
    n = int(summary.get("unfilled_passage_candidates", 0)) - int(summary.get("unfilled_openings_applied", 0))
    if n > 0:
        items.append(_item("passages_closed", "ack", n, "ช่องเปิดที่ดูเหมือนทางเดินแต่ยังปิดไว้",
                           "ติ๊กเปิดช่องที่เป็นทางเดินจริง หรือยืนยันว่าปิดไว้ถูกต้อง"))
    n = sum(int(m.group(1)) for w in warnings
            for m in [re.match(r"(\d+) multi-storey wall copies are exported without door gaps", w)] if m)
    if n:
        items.append(_item("multi_storey_no_doors", "ack", n, "ผนังหลายชั้น: ชั้นบนไม่มีช่องประตู",
                           "ผนังที่คัดลอกขึ้นชั้นบนปิดทึบ · ตรวจว่าชั้นบนมีประตูในแนวผนังนี้หรือไม่"))

    if issues:
        by_key = {int(r["key"]): r for k in ("walls", "columns", "obstacles") for r in semantic.get(k, [])}
        no_floor = edge = 0
        for i in issues:
            if i.get("type") != "obstacle_outside_walkable":
                continue
            rec = by_key.get(int(i.get("key", -1)))
            geom = _footprint(rec) if rec else None
            share = float(i.get("outside_area_m2") or 0) / geom.area if geom is not None and geom.area > 0 else 0
            if share > NO_FLOOR_SHARE:
                no_floor += 1
            else:
                edge += 1
        if no_floor:
            items.append(_item("obstacles_no_floor", "ack", no_floor, "สิ่งกีดขวางที่ไม่มีพื้นรองรับ",
                               "อยู่นอกพื้นที่เดินของชั้นตัวเองเกือบทั้งชิ้น · อาจอยู่ผิดชั้นหรือขาดแผ่นพื้น"))
        if edge:
            items.append(_item("obstacles_on_edge", "info", edge, "สิ่งกีดขวางคร่อมขอบพื้น",
                               "ผนัง/เสาริมพื้น · ปกติไม่ต้องแก้"))
        n = sum(1 for i in issues if i.get("type") == "obstacle_overlap")
        if n:
            items.append(_item("obstacle_overlaps", "info", n, "สิ่งกีดขวางซ้อนกัน",
                               "เช่นผนังต่อกันที่มุม · ไม่มีผลกับทางเดิน"))
    return items


def evaluate_gate(semantic: dict[str, Any], validation: dict[str, Any] | None,
                  acks: dict[str, Any] | None) -> dict[str, Any]:
    acks = acks or {}
    items = gate_items(semantic, validation)
    for item in items:
        ack = acks.get(item["id"])
        item["acknowledged"] = bool(ack) and item["policy"] == "ack" and int(ack.get("count", -1)) == item["count"]
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
        acks[item["id"]] = {"count": item["count"], "reason": reason.strip()[:500],
                            "at": datetime.now().isoformat(timespec="seconds")}
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
