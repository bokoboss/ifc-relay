# UI Design Brief — Engineering Workspace v1

สถานะ: **Draft UX/UI prototype** บน Branch `design/bim-engineering-workspace-v1`  
Base: `main` commit `1e2b692` (รวม PR #9: เปิด 3D หลัง Import อัตโนมัติ)

## 1. ทำไมต้องออกแบบใหม่

Frontend v0.4.1 เดิมเป็นแบบ dashboard: Sidebar แสดง 7 Steps, Action Bar มีคำสั่งทั้งหมดเรียงในแถวเดียว, 3D Viewer อยู่ในกล่องย่อย และ Audit/Semantic/Build แสดงเป็นหลายการ์ดต่อกัน

รูปแบบดังกล่าวมีผลเสียต่อการทำงานจริง:

- มองโมเดลไม่เป็นจุดศูนย์กลาง ทั้งที่เป็นสิ่งที่วิศวกรต้องตรวจละเอียด
- มี Command หลายตัวที่ยังทำไม่ได้ (disabled) ผสมกันจนผู้ใช้ไม่รู้คำสั่งสำคัญ
- Model Tree, Scene, Inspector ยังขาด visual cohesion
- ฟอนต์ 9–11 px และข้อมูลตัวเลขจำนวนมากทำให้อ่านยาก
- ไม่มีบุคลิกของเครื่องมือด้าน Engineering CAD/BIM; ดูเหมือน Admin Dashboard ทั่วไป

## 2. Design Direction

**BIM Engineering Workspace (No Permanent Sidebar)** — Desktop-first, local-first, focused and technical.

**Owner decision (18 Oct 2026):** ตัด Workflow 7 Stages ที่กินพื้นที่ซ้ายออก เพราะคำสั่งหลักมีใน Command Bar อยู่แล้ว และผู้ใช้ต้องการพื้นที่โมเดล 3D มากขึ้น เวิร์กโฟลว์ยังทำงานตามลำดับผ่านสถานะในระบบ ไม่บังคับแสดง 7 ขั้นค้างไว้บนจอ

ลักษณะเด่น:
1. **Canvas-first:** 3D Workspace เป็นพื้นที่หลัก มองเห็นตั้งแต่ก่อนเปิดไฟล์
2. **Full-width three-pane workbench:** ไม่มี Sidebar Workflow; Model Hierarchy ซ้าย / Viewer กลาง / Properties ขวา และขยายพื้นที่ Viewer
3. **Stage-based commands:** Import → Prepare Geometry → Validate & Build → Export; Downloads ที่ไม่ใช่ Primary Action อยู่ในเมนูเดียว
4. **System traceability:** Status Strip แจ้งข้อความจาก Backend; Local Engine status ย้ายเป็นเมนูสถานะที่ Top Bar
5. **Visual discipline:** ใช้สีเขียวอมฟ้าสำหรับการทำงานทั่วไป สีดินเผาสำหรับ Build, สีเหลืองสำหรับ Review และแดงเฉพาะ Error
6. **Clear hierarchy:** ขนาดฟอนต์ทั่วไป 12–14 px, ชื่อขั้นตอน 11–12 px, หัวข้อ 15–23 px
7. **Offline-friendly:** ไม่มี External Fonts, CDN หรือการเชื่อมต่อ API ใหม่จากการแก้ดีไซน์นี้

## 3. Layout — No Sidebar

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ [V] VISWALK BIM BUILDER │ ENGINEERING WORKSPACE │ Local Engine │ Reset     │
├─────────────────────────────────────────────────────────────────────────────┤
│  01 FILE INPUT  │ 02 GEOMETRY PREP │ 03 VALIDATE + BUILD │ 04 EXPORT       │
├─────────────────────────────────────────────────────────────────────────────┤
│  status strip                                                               │
├───────────────────────┬───────────────────────────────────┬─────────────────┤
│ MODEL TREE            │ Source IFC | Simulation Preview   │ PROPERTIES      │
│  Storeys              ├───────────────────────────────────┤  IFC Type       │
│  Categories           │                                   │  Level          │
│  Selection summary    │          3D MODEL SPACE           │  GlobalId       │
│                       │          primary workspace        │  Include/Review │
│                       │                                   │  Exclude        │
│                       ├───────────────────────────────────┤                 │
│                       │ geometry / loading status         │                 │
├───────────────────────┴───────────────────────────────────┴─────────────────┤
│ Audit / Large IFC / Semantic / Validation & Build / Category Details        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**ลำดับคำสั่งไม่ได้ถูกลบ:** ปุ่มต่าง ๆ ยังแสดง Enable/Disable ตามเงื่อนไขเดิม, Status Strip แจ้งความคืบหน้า และ `stepAnalyze/stepExplore/stepSelect/stepPreview/stepSemantic/stepBuild` ยังเก็บเป็น hidden DOM anchors เพื่อไม่ให้ JavaScript ที่มีอยู่เกิด Regression การลบสถานะภายในจะพิจารณาใน PR refactor ต่างหาก

**พื้นที่หน้าจอเป้าหมาย:** Desktop 1920×1080 และ 1366×768; Tablet 1024×768; Mobile 390×844 เป็นรอง

## 4. สิ่งที่แก้ใน PR นี้

- `static/index.html`: ย้าย Branding และ Local Engine ไป Top Bar, ลบ Sidebar 7 ขั้นจาก Layout, ปรับ Command grouping และ Empty Model State โดยรักษา ID ของ Control และ API contract เดิม
- `static/studio.css`: ใช้ Full-width Workspace ไม่มี Rail Sidebar, เพิ่ม responsive top bar และ Design Tokens, command bar, 3D workbench, audit sections
- `tests/test_ui_workbench_contract.py`: ทดสอบ DOM IDs, การไม่มี Sidebar ถาวร, UI state anchors ที่ยังคงอยู่, CSS loading และ viewer visible shell
- ไม่มีการแก้ `app.py`, `app.js`, `app3d.js`, geometry engine, IFC parser, COM adapter หรือระบบ state

## 5. คำแนะนำการใช้งาน

- เปิดไฟล์ IFC แล้วระบบควร Audit + Load 3D อัตโนมัติเช่นเดิม (จาก PR #9)
- กดองค์ประกอบใน Viewer แล้วข้อมูลแสดงใน Inspector; สถานะ Include/Review/Exclude ต้องยังทำงานเหมือนเดิม
- Stage Build ไม่ควรใช้งานได้ก่อนมี Semantic Model และ Validation
- Download Semantic, Engine JSON และ INPX ย้ายเข้าเมนู **ไฟล์และรายงาน** แต่ Button IDs/handlers ยังเดิม
- รายละเอียด Large IFC / Audit / Semantic / Build ยังคงแสดงด้านล่างเพื่อไม่เปลี่ยน workflow ในรอบแรก
- รุ่นถัดไปสามารถทำ Inspector tabs, dockable panes, keyboard shortcuts, building-floor navigator และ persistent workspaces ได้โดยแยก PR

## 6. Manual QA ที่ยังต้องทำบน Windows

1. เปิดเว็บเมื่อยังไม่มีโมเดล: Viewer empty state แสดงและปุ่มใช้งานเฉพาะ Input
2. Import Small IFC → Audit & Load 3D: Three.js ไม่เกิด 1×1 Canvas, ไม่ถูก CSS บัง
3. คลิก Wall/Door/Slab → ตรวจ Inspector, การตั้งค่า Include/Review/Exclude และไฟล์ Semantic ที่ได้
4. Large IFC: เลือก Storey/Full mode/Append ไม่ขัดกับ Viewer
5. Generate Semantic → Validate → Build Vissim COM → Download
6. ทดสอบที่ 1920×1080, 1366×768, 1024×768 และ 390×844; ไม่เกิด horizontal overflow
7. เปิด Keyboard focus, Export Dropdown, Local Engine status popover, Disabled State และรีเฟรชหน้ากลาง Workflow

**การแก้แบบ Design-only ยังไม่ได้รับประกันว่าทุกหน้าจอแสดงผลสมบูรณ์** ต้องทดสอบใน Browser/Windows จริงก่อน Merge

## 7. Non-goals

- ไม่เพิ่มฟีเจอร์ BIM ใหม่หรือแก้ Algorithm
- Evacuation Simulation เป็นแนวคิดระยะถัดไปที่บันทึกไว้ใน [Issue #11](https://github.com/bokoboss/viswalk-bim-builder/issues/11) และไม่รวมใน UI PR นี้
- ไม่เปลี่ยน Semantic JSON schema
- ไม่เพิ่มระบบ login/cloud storage
- ไม่อ้างว่ารองรับ PDF/DXF เต็มรูปแบบ
- ไม่เปลี่ยนพฤติกรรมของ PTV Vissim / COM

## 8. Post-merge backlog (เสนอ)

- แผง Model Tree แบบจริง (Site → Building → Storey → IFC Class/Item) พร้อมค้นหา
- แยก Model Geometry Review กับ Simulation Geometry แบบ Comparison และ highlight differences
- Workspace Resize / Docking / Fullscreen
- Bottom Validation/Issues panel แบบคลิกประเด็นแล้ว Focus วัตถุ
- Tabs ของ Inspector: Properties / Selection / Semantics / Issues
- In-app Thai labels ที่สอดคล้องกันโดยยังคงชื่อมาตรฐาน IFC
