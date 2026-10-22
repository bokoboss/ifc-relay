"""What to check before / after building the Viswalk file.

This app turns IFC into a Viswalk model; it is not a BIM checker. Anything the
engineer can fix in Viswalk after the build is listed, not enforced:

* ``block`` - only what makes the build itself impossible (Geometry Engine
              errors). The build is refused.
* ``check`` - things to check or fix in Viswalk (unreachable areas, doors that
              did not become openings, stair ends, plan edits not applied...).
              The build asks for one confirmation and writes the list to the
              build manifest and a checklist next to the .inpx.
* ``info``  - shown, no action needed.

Every item carries a fingerprint of the objects/places involved, so the
manifest records exactly which problems were known at build time.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from connectivity_service import _footprint

# Share of an obstacle's footprint outside its level's walkable area above which
# the obstacle is treated as standing where that level has no floor.
NO_FLOOR_SHARE = 0.9

POLICY_VERSION = "2026-10-22.3"

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
        "identities": ids[:200],          # the UI pages through these
        "identities_all": ids,            # the checklist annex keeps all
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

    if validation is None:          # the build validates again right before Vissim runs
        issues: list[dict[str, Any]] = []
    else:
        issues = validation.get("issues", [])
        errors = (validation.get("severity_counts") or {}).get("error", 0)
        if errors or not validation.get("build_allowed", False):
            err_ids = [f"{i.get('type')}:{i.get('key', i.get('objects'))}" for i in issues if i.get("severity") == "error"]
            items.append(_item("engine_errors", "block", err_ids or ["build_not_allowed"], "Geometry Engine พบข้อผิดพลาด",
                               "Engine สร้างไฟล์จากโมเดลนี้ไม่ได้ · ดูรายการด้านล่าง", count=max(errors, 1)))

    off_area = [f"{(vc_by_key.get(int(i.get('key', -1))) or {}).get('ifc_global_id') or i.get('key')}:"
                f"{'start' if 'start' in i.get('type', '') else 'end'}"
                for i in issues if i.get("type") in ("vertical_connection_not_on_start_area",
                                                     "vertical_connection_not_on_end_area")]
    if off_area:
        items.append(_item("ramp_not_on_area", "check", off_area, "ปลายบันได/ทางลาดไม่แตะพื้นที่เดิน",
                           "Viswalk จะ error ที่บันไดตัวนี้ตอนรัน · ต่อปลายบันไดกับ Area ใน Viswalk"))

    # Connectivity: a failed or missing analysis is never read as "all connected".
    if not isinstance(con, dict) or con.get("error") or "zones" not in con:
        reason = con.get("error") if isinstance(con, dict) else "connectivity result missing"
        items.append(_item("connectivity_failed", "check", [str(reason)], "ตรวจการเชื่อมต่อไม่สำเร็จ",
                           f"แอปวิเคราะห์ทางเดินไม่ได้ ({reason}) · ไม่กระทบไฟล์ · ตรวจทางเดินใน Viswalk เอง"))
        con = {}
    loose = [f"{d.get('ifc_global_id') or d.get('key')}:{'bottom' if not d.get('bottom_connected') else 'top'}"
             for d in con.get("stairs_not_linked", [])]
    if loose:
        items.append(_item("stairs_not_linked", "check", loose, "ปลายบันไดไม่ถึงพื้นที่เดินว่าง",
                           "ปลายบันไดชนผนัง/สิ่งกีดขวาง หรือไม่มีพื้นรองรับ · คนจะใช้บันไดนี้ไม่ได้"))
    zones = [_zone_id(z) for z in con.get("isolated_zones", [])]
    if zones and con.get("basis") == "anchors":
        items.append(_item("isolated_zones", "check", zones,
                           f"พื้นที่ที่เดินไปไม่ถึงทางออกที่กำหนด ({con.get('isolated_area_m2', 0):.1f} ตร.ม.)",
                           f"วัดจากทางออก/จุดหลัก {len(con.get('anchors') or {})} จุดที่วาดบนแปลน · พื้นที่สีแดงใน 3D · "
                           "ประตู/ช่องเปิดหรือบันไดที่ขาด หรือเป็นห้องปิด/ช่องท่อ"))
    elif zones:
        items.append(_item("isolated_zones", "check", zones,
                           f"พื้นที่ที่เดินไปไม่ถึง ({con.get('isolated_area_m2', 0):.1f} ตร.ม.)",
                           "พื้นที่สีแดงใน 3D · วัดจากโครงข่ายใหญ่ที่สุด (ยังไม่ได้กำหนดทางออก) · "
                           "ประตู/ช่องเปิดหรือบันไดที่ขาด หรือเป็นห้องปิด/ช่องท่อ"))

    stairs = info.get("stair_decisions") or {}
    if stairs.get("review"):
        n, total = int(stairs["review"]), int(stairs.get("units") or 0)
        items.append(_item("stairs_pending", "check", stairs.get("pending_global_ids") or [f"stairs_pending:{n}"],
                           f"บันได/ทางลาดที่ยังไม่ได้นำเข้า ({n} จาก {total} ชุด)",
                           "โมเดลนี้ไม่มีบันได/ทางลาดเหล่านี้ · นำเข้าในแผงซ้าย \"บันไดและทางลาด\" แล้วเตรียมใหม่ "
                           "หรือสร้างเองใน Viswalk", count=n))
    if con and con.get("basis") == "largest":
        items.append(_item("exit_anchor_missing", "info", ["exit_anchor_missing"],
                           "ยังไม่ได้กำหนดจุดอ้างอิงทางออก",
                           "การตรวจการเชื่อมต่อวัดจากโครงข่ายใหญ่ที่สุด (เบื้องต้น) · วาด \"อ้างอิงทางออก\" บนแปลนเพื่อวัดจากทางออกจริง "
                           "· จุดนี้ไม่สร้าง Exit ใน INPX", count=1))
    review_dir = [str(v.get("ifc_global_id") or v.get("key")) for v in vcs if v.get("direction_status") == "needs_review"]
    if review_dir:
        items.append(_item("stair_direction_review", "check", review_dir, "ทิศบันไดหาจาก Geometry ไม่ได้",
                           "ลูกศรสีส้มใน 3D · ตรวจทิศขึ้นของบันไดเหล่านี้ใน Vissim หลังสร้างไฟล์"))
    offsets = [f"{v.get('ifc_global_id') or v.get('key')}:{end}" for v in vcs for end in ("start", "end")
               if (v.get("level_match") or {}).get(end) != "exact"]
    if offsets:
        items.append(_item("stair_end_offset", "check", offsets, "ปลายบันไดใช้ z offset",
                           "ปลายบันไดไม่ตรงระดับชั้นใด · ตรวจการเชื่อมต่อใน Vissim"))
    left_out = [str(s.get("global_id")) for s in info.get("off_level_slabs", []) if s.get("decision") != "include"]
    if left_out:
        items.append(_item("off_level_left_out", "check", left_out, "แผ่นพื้นต่างระดับมากที่ยังไม่ใช้เป็นพื้นเดิน",
                           "ส่วนใหญ่เป็นแผงบังแดด/กันสาด · ถ้าเป็นพื้นเดิน ติ๊กใช้ในรายการแผ่นพื้นต่างระดับ"))
    diagnostics = info.get("diagnostics")
    if diagnostics is not None:
        doors = [i for d in diagnostics if d.get("code") == "door_not_converted" for i in d.get("ids", [])]
    else:   # pedestrian model written before structured diagnostics (v0.6.0)
        doors = [re.search(r"Door (\S+)", w).group(1) if re.search(r"Door (\S+)", w) else w for w in
                 _matching(warnings, r"no IfcRelFillsElement|not hosted by an IfcWall|no usable opening or mesh geometry")]
    if doors:
        items.append(_item("doors_not_converted", "check", doors, "ประตูที่แปลงเป็นช่องเปิดไม่ได้",
                           "ประตูไม่ผูกกับช่องเปิด/ผนังใน IFC · ผนังตรงนั้นยังปิดอยู่ · ใช้ \"เปิดทางผ่าน\" ในแปลน 2D ได้"))
    unmeshed = [i for d in (diagnostics or []) if d.get("code") == "mesh_failed" for i in d.get("ids", [])]
    if unmeshed:
        items.append(_item("mesh_failed", "check", unmeshed, "ชิ้นส่วนที่สร้างรูปทรงไม่ได้",
                           "IfcOpenShell อ่านรูปทรงชิ้นเหล่านี้ไม่ได้ · ไม่อยู่ในโมเดลคนเดิน · ตรวจใน BIM viewer แล้วเพิ่มใน Viswalk ถ้าจำเป็น"))
    closed = [str(c.get("global_id")) for c in info.get("opening_candidates", [])
              if c.get("classification") == "passage_candidate" and c.get("decision") != "include"]
    if closed:
        items.append(_item("passages_closed", "check", closed, "ช่องเปิดที่ดูเหมือนทางเดินแต่ยังปิดไว้",
                           "ถ้าเป็นทางเดินจริง ติ๊กเปิดในรายการช่องเปิด หรือเปิดใน Viswalk"))
    if diagnostics is not None:
        n = sum(int(d.get("count", 0)) for d in diagnostics if d.get("code") == "multi_storey_no_doors")
        multi_ids = [f"multi_storey_no_doors:{n}"] if n else []
    else:
        legacy = _matching(warnings, r"multi-storey wall copies are exported without door gaps")
        n = sum(int(re.match(r"(\d+)", w).group(1)) for w in legacy if re.match(r"(\d+)", w))
        multi_ids = legacy
    if n:
        items.append(_item("multi_storey_no_doors", "check", multi_ids, "ผนังหลายชั้น: ชั้นบนไม่มีช่องประตู",
                           "ผนังที่คัดลอกขึ้นชั้นบนปิดทึบ · ตรวจว่าชั้นบนมีประตูในแนวผนังนี้หรือไม่", count=n))
    steps = [str(st.get("global_id")) for st in info.get("flattened_steps", []) if st.get("global_id")]
    if steps:
        items.append(_item("floor_step_flattened", "check", steps, "พื้นต่างระดับที่ถูกปรับรวมเป็นพื้นชั้น",
                           "แผ่นพื้นสูงหรือต่ำกว่าพื้นชั้น 0.25–0.40 ม. ถูกรวมเป็นพื้นเรียบ · ถ้าเป็นขั้นที่เดินข้ามไม่ได้ ให้ใส่สิ่งกีดขวางหรือทางลาดใน Viswalk"))

    # Manual plan edits that could not be applied: the file will not contain them.
    edits = info.get("manual_edits") or []
    status = info.get("manual_edits_status") or {}
    skipped = [eid for eid, st in status.items() if st.get("applied") is False]
    if skipped:
        items.append(_item("manual_edits_skipped", "check", skipped, "แก้ไขบนแปลนที่ใช้ไม่ได้",
                           "ไฟล์จะไม่มีรายการเหล่านี้ (ระดับไม่มีในโมเดลนี้) · วาดใหม่ในแปลน 2D หรือแก้ใน Viswalk"))
    no_effect = [eid for eid, st in status.items()
                 if st.get("applied") and st.get("walls_cut") == 0
                 and any(str(e.get("id")) == eid and e.get("kind") == "passage" for e in edits)]
    if no_effect:
        items.append(_item("manual_passage_no_effect", "check", no_effect, "ทางผ่านที่วาดแล้วไม่ได้ตัดผนัง",
                           "ทางผ่านเหล่านี้ไม่คร่อมผนังใดเลย · ไฟล์ไม่มีช่องทางเดินตรงนั้น · วาดใหม่ให้คร่อมผนัง หรือเปิดใน Viswalk"))
    stray_exits = [eid for eid, st in status.items()
                   if st.get("applied") and st.get("zones_touched") == 0
                   and any(str(e.get("id")) == eid and e.get("kind") == "exit" for e in edits)]
    if stray_exits:
        items.append(_item("manual_exit_no_effect", "check", stray_exits, "ทางออกที่วาดไม่แตะพื้นที่เดิน",
                           "จุดเหล่านี้ไม่ถูกใช้ในการตรวจการเชื่อมต่อ · วาดใหม่ให้ทับพื้นที่เดินว่าง"))
    if edits:
        kinds = {k: sum(1 for e in edits if e.get("kind") == k) for k in ("walkable", "obstacle", "passage", "exit")}
        items.append(_item("manual_edits", "info", [str(e.get("id")) for e in edits], "แก้ไขบนแปลนโดยวิศวกร",
                           f"พื้นที่เดินเพิ่ม {kinds['walkable']} · สิ่งกีดขวางเพิ่ม {kinds['obstacle']} · "
                           f"ทางผ่าน {kinds['passage']} · ทางออก {kinds['exit']} · บันทึกใน build manifest"))

    repairs = info.get("gap_repairs") or []
    if repairs:
        ids = [f"L{r['level_key']}@{r['centroid'][0]:.1f},{r['centroid'][1]:.1f}~{max(round(r['area_m2'] * 2) / 2, 0.5)}"
               for r in repairs]
        items.append(_item("gap_repairs", "info", ids, "รอยต่อพื้นที่ระบบปิดให้อัตโนมัติ",
                           f"ช่องว่างระหว่างแผ่นพื้นแคบกว่า 50 มม. ถูกเติมให้พื้นเดินต่อกัน (Viswalk ต้องให้พื้นที่แตะกัน) · "
                           f"กด \"ดูตำแหน่ง\" เพื่อดูว่าไม่ใช่ช่องที่ตั้งใจเว้นไว้", count=len(repairs)))

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
            items.append(_item("obstacles_no_floor", "check", no_floor, "สิ่งกีดขวางที่ไม่มีพื้นรองรับ",
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


def evaluate_gate(semantic: dict[str, Any], validation: dict[str, Any] | None) -> dict[str, Any]:
    items = gate_items(semantic, validation)
    blocked = [i["id"] for i in items if i["policy"] == "block"]
    to_check = [i["id"] for i in items if i["policy"] == "check"]
    return {
        "policy_version": POLICY_VERSION,
        "items": items,
        "blocked": blocked,
        "to_check": to_check,
        "check_count": sum(i["count"] for i in items if i["policy"] == "check"),
        "passed": not blocked,
    }


def gate_message_th(gate: dict[str, Any]) -> str:
    titles = {i["id"]: i["title"] for i in gate["items"]}
    return "ต้องแก้ก่อน: " + ", ".join(titles[i] for i in gate["blocked"]) if gate["blocked"] else ""


def checklist_markdown(gate: dict[str, Any], source_name: str, output_name: str, built_at: str) -> str:
    """The 'check in Viswalk' list written next to the .inpx."""
    lines = [f"# Check in Viswalk: {output_name}", "",
             f"Source IFC: {source_name}  ", f"Built: {built_at}", ""]
    checks = [i for i in gate["items"] if i["policy"] == "check"]
    if not checks:
        lines.append("Nothing flagged by the converter. Still review the model in Viswalk before use.")
    for item in checks:
        lines.append(f"- [ ] **{item['title']}** ({item['count']}) - {item['detail']}")
        ids = item.get("identities_all") or item.get("identities", [])
        shown = ids[:30]
        if shown:
            more = f" ... (showing {len(shown)} of {len(ids)}; full list in the _checklist_ids.json file)" \
                if len(ids) > len(shown) else ""
            lines.append("  - " + ", ".join(f"`{x}`" for x in shown) + more)
    lines += ["", "## Not made by the converter (set up in Viswalk)", "",
              "- [ ] Pedestrian inputs, routes and exits for the scenario being simulated "
              "(exit marks drawn in the app only check connectivity; they are not exits in the .inpx)",
              "- [ ] Open the model, check levels, stairs and their directions, then run a short simulation"]
    return "\n".join(lines) + "\n"


def checklist_ids(gate: dict[str, Any]) -> dict[str, Any]:
    """Every object id of every item (the Markdown list shows the first 30)."""
    return {"policy_version": gate.get("policy_version"),
            "items": [{"id": i["id"], "policy": i["policy"], "title": i["title"], "count": i["count"],
                       "identities": i.get("identities_all") or i.get("identities", [])} for i in gate["items"]]}
