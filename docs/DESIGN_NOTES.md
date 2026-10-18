# Design Notes — Viswalk BIM Builder

> สรุปเหตุผลและหลักฐานการตัดสินใจจากการพัฒนา POC จนถึง v0.4.1a เอกสารนี้ไม่ใช่บันทึกบทสนทนาทั้งหมด และไม่ได้รับรองความพร้อมของโมเดลทุกประเภท

## เป้าหมายและ Architecture

เป้าหมายคือช่วยให้วิศวกรสร้างโมเดลเรขาคณิตคนเดินสำหรับ PTV Viswalk จาก IFC/BIM และแบบวิศวกรรมในอนาคต ลดงานวาดซ้ำ และยังตรวจสอบแก้ไขข้อมูลได้ก่อนส่งเข้า Simulation

```text
IFC / Drawing
 -> Parser / Source Audit
 -> Object Candidates
 -> Human Selection / Review
 -> Semantic Geometry (metres)
 -> Deterministic Geometry Engine + Validation
 -> Windows Vissim 2025 COM
 -> .inpx + Report + Log
```

- ไม่แก้ไข IFC ต้นฉบับ; เก็บสถานะ Auto/Include/Exclude/Review แยก โดยอ้างอิง IFC GlobalId
- Parser/AI ไม่แก้ไฟล์ `.inpx` โดยตรง; deterministic engine เป็นผู้สร้างเรขาคณิต
- BIM solids และ pedestrian simulation geometry เป็นคนละ representation
- โปรแกรมเป็น local-first; โมเดลโครงการจริงไม่ถูกเผยแพร่ขึ้น Public GitHub

## ADR-001 — Logical Wall กับ Physical Wall Segments

ผนังหนึ่งเส้นใน BIM อาจมีประตูหลายช่อง จึงเก็บ logical wall สำหรับการแก้ไข แต่ตัดเป็น physical wall segments รอบช่องประตูก่อนส่ง Geometry Engine

```text
logical:   ------------------
door:          [   ]
physical: ------   ---------
```

- `IfcRelVoidsElement` เชื่อม Opening กับ host Wall
- `IfcRelFillsElement` เชื่อม Door กับ Opening
- เฉพาะช่องประตูที่รวมอยู่ใน model จึงถือเป็น pedestrian gap; `IfcWindow` **ไม่ใช่ช่องเดิน** โดยอัตโนมัติ
- ผนังที่ส่งเข้า Engine ในฐานะ physical segments แล้วต้องไม่เก็บ `openings` ที่ทำให้ engine ตัดผนังซ้ำ

**Regression Fixture #1:** 24 logical walls → 29 physical wall segments; ประตู 5 ช่องเปิดจริง; หน้าต่าง 21 ชิ้นไม่สร้างช่องเดิน; 29 obstacles ผ่าน Geometry Engine โดยไม่มีการตัดผนังซ้ำ

## ADR-002 — Walkable Surface ไม่เท่ากับ Slab ทุกชิ้น

Structural IFC อาจแบ่งพื้นหนึ่งชั้นเป็น panel จำนวนมาก; slab ที่เป็น Base/Roof ไม่จำเป็นต้องเป็นพื้นเดิน

- กรอง FLOOR ที่เหมาะสมเป็น walkable; BASESLAB ต้อง Review; Roof/non-floor ไม่ถูก Auto-Include
- รวม floor-panel footprints ต่อ Storey ด้วย union/merge
- รักษา void/shaft/atrium และพื้นที่ไม่ต่อเนื่อง ไม่ให้ union เติมช่องว่างที่ไม่ใช่พื้นเดิน
- Validation ต้องแยกข้อผิดพลาดจริงกับ boundary walls ที่ล้ำออกนอก walkable envelope

**Fixture #1:** 5 storeys แต่มี 4 floor areas เพราะอีกชั้นเป็น roof-only

## ADR-003 — Elevation และ Vertical Circulation

ใช้ข้อมูล elevation จริง ไม่สรุปความสูงจากชื่อชั้น เช่น Level 1, Level 2 หรือการเรียงเลขที่ไม่ต่อเนื่อง

การสร้าง Stair/Ramp/Elevator ต้องอาศัยระดับปลายทางจริงจาก geometry และความสัมพันธ์ขององค์ประกอบกับ walkable regions ไม่ใช่ใช้ Next Storey โดยอัตโนมัติ ฟังก์ชันดังกล่าวยังอยู่ในการพัฒนา ไม่ควรประกาศว่ารองรับ IFC ซับซ้อนสมบูรณ์แล้ว

## ADR-004 — Large IFC: Filter / Lazy-load / Preflight

การส่ง mesh ทั้งอาคาร 30+ ชั้นเข้า browser พร้อมกันเป็นภาระสูง จึงเพิ่ม:
- Simulation-relevant หรือ Full IFC mode
- Selected-storey และ Whole-building display
- โหลด Storey ที่มี geometry จริงก่อน แทนเลือก Storey แรกตาม elevation
- ไม่ส่ง IfcBeam เข้า default simulation-relevant view
- Semantic model ของทั้งอาคารต้องสร้างจาก backend ที่มีข้อมูลครบ ไม่ขึ้นกับการแสดงใน browser เพียงบางชั้น

**ตัวอย่าง regression ขนาดใหญ่ (ไม่เผยแพร่ชื่อหรือไฟล์โครงการ):** IFC2X3 ขนาดหลายสิบ MB อาคารสูงหลายสิบชั้น มีผนัง พื้น เสา และคานรวมหลายพันชิ้น บันไดจำนวนน้อย และไม่มีข้อมูลประตู/หน้าต่าง; Viewer แสดงทั้งอาคารได้ แต่ semantic/consolidation/vertical QA ของทั้งอาคารยังไม่ผ่านการยืนยัน

**บั๊ก v0.4.1:** เลือก storey แรกที่ -5 m ซึ่งมี 0 relevant meshes ทำให้จอว่าง; พบ storey ถัดไป -2 m มี 183 relevant meshes และแก้ให้เลือกชั้นแรกที่มี geometry

## ADR-005 — Engine Adapter และ Severity

- Vissim COM อยู่ใน Windows backend เท่านั้น และควร serialize build เพื่อหลีกเลี่ยง concurrent mutable COM state
- ใช้ geometry engine ที่พิสูจน์กับ Fixture #1 แทนเขียนใหม่โดยไม่จำเป็น
- Result ต้องมี validation report, log และ output path
- ระดับ validation: ERROR (block), WARNING (review), INFO (อธิบายได้ไม่ block)

**กรณี Fixture #1:** engine validation รายงาน 9 รายการ: 1 roof-only level และ 8 exterior wall fragments ที่ยื่นออกนอก walkable area ซึ่ง adapter จัดเป็น INFO ตามเงื่อนไขของชุดทดสอบนั้น ไม่ควรใช้กฎ “สิ่งกีดขวางนอกพื้นเดินทั้งหมด = INFO” กับทุกโครงการ

## Regression และหลักฐานการทดสอบ

| กรณี | สถานะ |
| --- | --- |
| IFC Fixture #1: 55 meshes, 0 failures, 5 levels, 4 areas | PASS |
| 24 logical walls → 29 physical wall segments, 5 door gaps, 0 window gaps | PASS |
| Geometry Engine: 29 obstacles โดยไม่ตัดผนังซ้ำ | PASS |
| Vissim 2025 COM: สร้าง/เปิด `.inpx` และตรวจด้วยวิศวกร | PASS สำหรับ Fixture #1 |
| Large IFC: viewer แบบ selected-storey และ whole-building | ผ่านการทดสอบ viewer |
| Large-model floor union และ void preservation | unit test ผ่าน; full-model engineering QA ยังไม่ผ่าน |
| Stair/Ramp/Elevator จาก IFC จริง | ยังอยู่ระหว่างพัฒนา |

## Source Import Manifest และข้อจำกัด

- `engine/05_geometry_engine_v03.py`: engine ต้นฉบับที่ใช้ทดสอบ POC
- `examples/geometry_v03.json`: synthetic 2-level JSON input example
- `legacy/10_*.py` ถึง `legacy/30_*.py`: 21 สคริปต์ DXF/PDF และ review workspace เก็บชื่อเดิม
- **ยังไม่พบสคริปต์ 01–09 และ 31–33** ในไฟล์ที่เข้าถึงได้ จึงไม่สร้างทดแทน
- สคริปต์ legacy บางตัวอ้างอิง input fixture, mapping JSON, DXF/PDF หรือ dependencies ซึ่งไม่รวมใน PR นี้
- `main` ปัจจุบันยังอ้าง engine ที่ Project Root; **การนำ engine เข้า `engine/` ไม่ทำให้แอปใช้ตำแหน่งใหม่นี้เอง** ต้องแยก PR ปรับ path resolution และ CI
- CI บน Linux อาจต้อง mock `win32com` เมื่อ import engine; actual COM build ยังต้อง Windows + Licensed Vissim
- `base_empty.inpx` เป็น local external dependency; ไม่ใส่ใน Public Repo

## ข้อมูลและสิทธิ์เผยแพร่

ไม่เพิ่ม IFC ของโครงการจริง, `.inpx`, screenshot จากโครงการจริง, runtime output, log, cache หรือ virtual environment

การมี Source Code ในแชทเดิมไม่ได้เป็นหลักฐานว่าผู้จัดทำทุกฝ่ายมีสิทธิ์เผยแพร่ ดังนั้น PR นี้ควรได้รับการยืนยันสิทธิ์/นโยบายองค์กรจากเจ้าของโครงการก่อน Merge เข้าสู่ Public `main`

เอกสารนี้เป็น design history และ evidence summary ไม่ใช่คำยืนยันว่าไม่มีข้อผิดพลาดในระบบ
