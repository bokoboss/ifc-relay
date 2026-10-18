# Product Vision & Scope — Viswalk BIM Builder

> **Document status:** Product direction and scope (living document), 15 October 2026. This is not a claim that every planned function is implemented.
>
> **Product line:** Engineer-reviewed conversion of BIM / engineering drawings into simulation-ready pedestrian geometry for PTV Vissim/Viswalk.

## 1. เป้าหมายของแอป (Product Goal)

พัฒนา **Local Web Application สำหรับช่วยสร้างโมเดลคนเดินใน PTV Viswalk จากข้อมูล BIM และแบบวิศวกรรม** เพื่อลดการขึ้นโมเดลเรขาคณิตซ้ำด้วยมือ แต่ยังให้วิศวกรเป็นผู้ตรวจสอบและยืนยันแบบจำลองก่อนนำไปใช้งาน

**โจทย์หลัก:** geometry ของอาคารใน BIM ไม่เท่ากับ geometry ที่คนเดินได้จริงใน pedestrian simulation โดยตรง เช่น แผ่นพื้นอาจแยกเป็นหลายร้อยชิ้น ผนังอาจมีช่องประตูหรือช่องหน้าต่าง เสาเป็นสิ่งกีดขวาง และบันไดต้องเชื่อมระดับที่ถูกต้อง

แอปจึงไม่ใช่แค่ `IFC → .inpx` converter แต่เป็นกระบวนการ:

```text
BIM / CAD / Drawing
  -> Parse and inspect source
  -> Classify candidate simulation objects
  -> Human review and correction
  -> Deterministic semantic geometry
  -> Simplify / consolidate / validate
  -> Build Viswalk geometry with local COM
  -> Engineer checks .inpx in Vissim/Viswalk
```

ข้อมูลต้นฉบับต้องไม่ถูกแก้ไขโดยอัตโนมัติ การตัดสินใจ Include/Exclude/Review ควรเก็บแยกจาก IFC และย้อนกลับไปหา IFC GlobalId ได้

## 2. ผู้ใช้งานเป้าหมาย (Target Users)

- วิศวกรจราจรและขนส่ง / วิศวกรผู้ทำ pedestrian microsimulation
- ผู้พัฒนาโมเดล PTV Viswalk/Vissim
- BIM Coordinator, Architect และผู้จัดเตรียมแบบสำหรับ Simulation
- ทีมวิจัยหรือที่ปรึกษาที่ต้องแปลงแบบอาคาร/สถานี/พื้นที่สาธารณะเป็นโมเดลคนเดิน

**Use cases ที่ต้องรองรับในระยะยาว:** อาคารสำนักงานสูงหลายชั้น สถานีขนส่ง พื้นที่เชื่อมต่อในอาคาร โถงทางเดิน และพื้นที่สาธารณะที่มีทางเชื่อมหลายระดับ

## 3. วัตถุประสงค์เชิงผลิตภัณฑ์ (Objectives)

1. **Reduce manual drafting:** ลดงานวาด Area, Wall, Column และองค์ประกอบเรขาคณิตซ้ำใน Viswalk
2. **Preserve engineering control:** มี 3D/2D review และการแก้ไขข้อสันนิษฐานก่อน Build
3. **Create simulation geometry, not duplicate BIM solids:** แปลงความหมายของ Slab, Door, Wall, Column และ Void ให้เป็นพื้นที่เดิน/สิ่งกีดขวางที่เหมาะกับ pedestrian simulation
4. **Make interpretation traceable:** ระบุที่มา/สถานะของวัตถุและแจ้งข้อจำกัด เช่น IFC ไม่มีประตู
5. **Handle realistic building scale:** รองรับการดูทีละ Storey และไม่บังคับส่ง mesh ทั้งอาคารเข้า Browser ทุกครั้ง
6. **Produce usable local outputs:** Export JSON สำหรับ engine และ `.inpx` ผ่าน Vissim COM พร้อม Validation Report/Build Log
7. **Extend without rewriting:** แยก Source Adapter, Semantic Model, Geometry Engine, Viewer และ Vissim COM Integration
8. **Protect project data:** ประมวลผล BIM ในเครื่อง และไม่นำไฟล์โครงการขึ้น Public Repository

## 4. ขอบเขตและสถานะความสามารถ (Feature Scope)

สถานะ:
- **Validated baseline** = ทดสอบกับ IFC ขนาดเล็กและสร้าง/เปิดโมเดลใน Vissim จริง
- **Implemented / needs QA** = มีโค้ดใช้งานหรือ unit tests แต่ยังไม่ผ่านการรับรองกับ IFC หลากหลายรูปแบบ
- **Planned** = เป็นเป้าหมาย ไม่ควรกล่าวว่าใช้งานได้แล้ว

| Module | What it should do | Current status |
| --- | --- | --- |
| A. Source intake | IFC metadata, project units, Storeys, categories, relationships; later DXF/PDF/vector/scan adapters | IFC implemented; DXF/PDF app integration planned |
| B. Source viewer | 3D model, select objects, filter Storey/category, single/whole model, future 2D drawing overlay | 3D implemented |
| C. Engineering review | Auto / Include / Exclude / Review; source-to-simulation comparison; future manual edits, draw/move/split/merge geometry | Selection implemented, carried across IFC revisions by GlobalId with a change report; geometry editing planned |
| D. Semantic mapping | Map slabs to walkable areas; walls/columns/other objects to obstacles; door-filled openings to gaps; exclude window openings | Validated baseline; unfilled openings reviewable and non-straight walls as polygons (synthetic-IFC tested); complex cases need QA |
| E. Simplification | Consolidate floor panels, preserve openings/voids, remove unnecessary detail, handle irregular geometry | Slab merge & void logic implemented / needs full large-IFC QA |
| F. Multi-level circulation | Geometry-aware mapping of stairs, stair flights, ramps, elevators; endpoints/elevations and connected walkable surfaces | Stairs/ramps per flight + intermediate landing levels implemented (v0.5 draft, synthetic-IFC tested; see [VERTICAL_CIRCULATION.md](VERTICAL_CIRCULATION.md)); Vissim verification pending; elevators planned |
| G. Validation | Geometry integrity, unit/level consistency, passability, warnings with severity and evidence | Core implemented; richer connectivity checks planned |
| H. Build / Export | Deterministic geometry engine, Vissim COM, save `.inpx`, JSON/reports/logs | Validated baseline; external engine and template not in public repo |
| I. Simulation configuration | Pedestrian inputs, origins/destinations, routes, demand, scenario presets | Longer-term extension |
| J. Simulation results | Run scenarios, measure travel time/density/LOS/queues, export QA and reports | Longer-term extension |

**Input maturity:** IFC is the active end-to-end path. Earlier standalone DXF/PDF experiments are research prototypes; the current public web app must **not** be described as a fully functioning DXF/PDF converter.

**AI maturity:** Intelligent/AI-assisted interpretation of ambiguous 2D drawing features is a future possibility, not a verified production feature. Geometry construction after review must remain deterministic.

## 5. สิ่งที่ไม่ใช่เป้าหมายของรุ่นปัจจุบัน (Non-goals)

- ไม่แทนที่ PTV Viswalk/Vissim simulation solver หรือการตรวจสอบแบบจำลองโดยวิศวกร
- ไม่รับรองว่า BIM ทุกไฟล์มีประตู/พื้นที่เดิน/ความเชื่อมต่อที่สมบูรณ์
- ไม่เติมทางเข้าออกหรือบันไดที่ไม่มีหลักฐานจากต้นฉบับโดยอัตโนมัติแล้วถือว่าถูกต้อง
- ไม่สร้างแบบจำลองพฤติกรรมคนเดิน/Calibration/ผลวิเคราะห์ LOS จาก BIM เพียงอย่างเดียว
- ไม่ถือว่า `.inpx` เปิดได้แล้วเท่ากับใช้เพื่อการออกแบบจริงได้ทันที
- ไม่อัปโหลดไฟล์โครงการจริงเข้าบริการออนไลน์โดยไม่ได้รับอนุญาต

## 6. สถาปัตยกรรมที่ต้องรักษา (Architecture Invariants)

```text
Source IFC / future DXF / PDF
          |
   Parser + Source Audit  -------- Original file remains unchanged
          |
   3D / 2D Source Viewer
          |
  Reviewed Selection State ------ IFC GlobalId / evidence / overrides
          |
    Semantic Model (m)
          |
  Simplification + Validation --- floor merge, voids, physical door gaps
          |
 Deterministic Geometry Engine
          |
  Vissim 2025 COM Adapter ------- local Windows, serial build
          |
      .inpx + Reports
```

- **Logical vs Physical:** ผนังหนึ่งแนวอาจแตกเป็นหลาย physical wall segments เมื่อมีประตู ห้ามตัดซ้ำซ้อนใน engine
- **Doors vs Windows:** ช่องที่เติมด้วย `IfcDoor` จึงมีสิทธิ์สร้าง pedestrian gap; `IfcWindow` ไม่เป็นช่องคนเดินโดยอัตโนมัติ
- **Levels:** เชื่อถือ elevation/geometry ที่มีหลักฐานจริง ไม่อนุมานความสูงจากชื่อชั้น
- **Source of truth:** ห้ามเปลี่ยน IFC ต้นฉบับเพื่อสร้าง Simulation Model
- **Separation of concerns:** Parser/Review/Semantic/Geometry/COM แยกส่วน และให้กลับไป regression รุ่นก่อนหน้าได้
- **Warnings:** แยก `ERROR / WARNING / INFO` ไม่ซ่อนความไม่แน่นอน

## 7. เกณฑ์ตรวจรับ (Acceptance / Quality Gates)

### Regression Fixture #1 — small architectural IFC

ได้รับการยืนยันบน Windows/Vissim 2025 ตามขอบเขตข้อมูล fixture นี้:

| Check | Expected / verified |
| --- | --- |
| IFC 3D geometry | 55 meshes; 0 mesh-extraction failures |
| Building levels | 5 |
| Walkable areas | 4 (roof not auto-walkable) |
| Logical walls / physical segments | 24 / 29 |
| Door-filled openings applied | 5 |
| Window openings treated as doors | 0 |
| Engine obstacle count | 29, without duplicate wall fragmentation |
| Export | `.inpx` generated, reopened and visually checked by engineer |

Do not generalize these counts to other buildings. Fixture content must not be committed unless redistribution rights are established.

### Regression Fixture #2 — large structural IFC (evaluation ongoing)

- หลายสิบชั้นและองค์ประกอบ IFC จำนวนมาก
- ทดสอบ selected-storey และ whole-building 3D loading
- ทดสอบ floor-panel merging, voids, wall/column placement, storey mapping และ performance
- ตรวจว่า structural IFC ที่ไม่มี Door **ต้องแจ้งข้อมูลขาด** ไม่ใช่สร้าง opening สมมุติแล้วถือว่าถูกต้อง
- Heavy semantic + Viswalk build + engineering QA ทั้งอาคาร **ยังต้องทดสอบ**; viewer ที่แสดงได้ไม่ใช่หลักฐานว่า Simulation Geometry ถูกต้อง

### Additional release gates

- No regression of the small-model golden path.
- No silent geometry omission, incorrect unit scaling, sealed doors, or filled voids.
- Logs and validation reports explain failures and assumptions.
- Large-model operations should support progressive inspection without requiring all browser meshes up front.
- Files that fail engineering checks must remain clearly marked as unverified.

## 8. Roadmap (direction, not a delivery commitment)

| Phase | Goal | Evidence required |
| --- | --- | --- |
| v0.4 | Proven IFC-to-Vissim geometry baseline | **Passed on small fixture** |
| v0.4.1a | Large IFC storey viewer, filtered loading, floor consolidation | **Viewer tested; full semantic/model QA outstanding** |
| Near term | Repository hardening: repeatable setup, test-fixture policy, independent build dependency handling | Clean clone + documented validation |
| v0.5 | IFC Stair / Ramp / Elevator and multi-level connectivity | Floor-to-floor connections reviewed in Vissim |
| v0.6 | Robust complex BIM geometry: irregular/sloped floors, curves, openings, furniture/proxies | Diverse IFC test matrix |
| Future source adapters | Integrate DXF/PDF into the same semantic/review workflow | Engineer-reviewable 2D geometry conversion |
| Later | Model setup, pedestrian inputs, simulation runs and reports | Validated demand, performance and results |

Ordering may change based on engineering risk and the available licensed Vissim environment.

## 9. Source code, BIM files, and distribution

- Project IFC files, client drawings, proprietary PTV files, outputs, local database, and caches must remain outside the public repo.
- The current public repo is **not self-contained**: standalone geometry engine and the local Vissim base network are external and require an appropriate license/right to share.
- No open-source LICENSE is selected yet; do not infer license rights from public visibility.
- Preserve local-first processing. Any future remote service must require explicit design/security review.

---

**English summary:** Viswalk BIM Builder is a local-first, engineer-reviewed pipeline that converts BIM/drawing evidence into simplified, validated pedestrian simulation geometry. The validated small-IFC workflow builds Vissim/Viswalk `.inpx` through Windows COM. Large-IFC consolidation and true multi-level circulation remain under development. Human review, traceability, deterministic geometry and data protection are core product constraints.
