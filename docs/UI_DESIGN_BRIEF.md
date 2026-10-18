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
3. **Single-row primary toolbar:** เลือกไฟล์/เปิดโมเดล → เตรียมโมเดลคนเดิน → ตรวจสอบโมเดล → สร้างไฟล์ Viswalk; Analyze/Load 3D/Export เป็นคำสั่งรองในเมนูเพิ่มเติม (Desktop 1366 px ขึ้นไปควรเหลือแถวเดียว)
4. **System traceability:** Status Strip แจ้งข้อความจาก Backend; Local Engine status ย้ายเป็นเมนูสถานะที่ Top Bar
5. **Visual discipline:** ใช้สีเขียวอมฟ้าสำหรับการทำงานทั่วไป สีดินเผาสำหรับ Build, สีเหลืองสำหรับ Review และแดงเฉพาะ Error
6. **Clear hierarchy:** ขนาดฟอนต์ทั่วไป 12–14 px, ชื่อขั้นตอน 11–12 px, หัวข้อ 15–23 px
7. **Offline-friendly:** ไม่มี External Fonts, CDN หรือการเชื่อมต่อ API ใหม่จากการแก้ดีไซน์นี้

## 3. Layout — No Sidebar, Minimal Toolbar

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [V] VISWALK BIM BUILDER    ENGINEERING WORKSPACE    Local Engine    Reset    │
├──────────────────────────────────────────────────────────────────────────────┤
│ [เลือกไฟล์ BIM] [เปิดโมเดล] │ [เตรียมโมเดลคนเดิน] [ตรวจสอบโมเดล]               │
│                                             [สร้างไฟล์ Viswalk]  [เพิ่มเติม]   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Status Strip — File Imported / Geometry Ready / Validation / Errors          │
├───────────────────────┬──────────────────────────────────────┬───────────────┤
│ MODEL TREE            │ โมเดลต้นฉบับ / โมเดลคนเดิน           │ PROPERTIES     │
│ Storeys               ├──────────────────────────────────────┤ IFC Type       │
│ Categories            │                                      │ Level          │
│ Selection summary     │         3D MODEL WORKSPACE           │ GlobalId       │
│                       │  พื้นที่เดิน / ผนัง / สิ่งกีดขวาง  │ Include/Review │
│                       │                                      │ Exclude        │
│                       ├──────────────────────────────────────┤               │
│                       │ Viewer Status                        │               │
├───────────────────────┴──────────────────────────────────────┴───────────────┤
│ IFC Audit / Large IFC / Semantic / Validation / Build / Category Details    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**แถบคำสั่งในรูปคือองค์ประกอบของแถวเดียวเมื่อ Desktop มีความกว้างเพียงพอ** แต่แสดงเป็นสองบรรทัดในผังเพื่อความชัดเจน; CSS ตั้งให้แยกเป็นหลายแถวเมื่อ viewport ไม่เกิน 1120 px เพื่อไม่ให้ปุ่มทับกัน

**ลำดับคำสั่งไม่ได้ถูกลบ:** ปุ่มต่าง ๆ ยังถูกเปิด/ปิดตามเงื่อนไขเดิม, Status Strip แสดงความคืบหน้า และ hidden DOM anchors สำหรับ `stepAnalyze/stepExplore/stepSelect/stepPreview/stepSemantic/stepBuild` คงไว้เพื่อป้องกัน JavaScript Regression

**คำว่า “เตรียมโมเดลคนเดิน” หมายถึง:** สร้าง Semantic/Engine Geometry จาก IFC ไม่ใช่การโหลดโมเดลต้นฉบับซ้ำ; ระบบจะเรียก `loadSemantic()` และสลับเป็นโหมดโมเดลคนเดินใน 3D อัตโนมัติหลังสร้างสำเร็จ หากข้อมูลถูกสร้างสำเร็จแต่ Preview มีปัญหา ต้องยังดาวน์โหลดไฟล์ JSON และตรวจสอบเหตุได้

**พื้นที่หน้าจอเป้าหมาย:** Desktop 1920×1080 และ 1366×768; Tablet 1024×768; Mobile 390×844 เป็นรอง

## 4. สิ่งที่แก้ใน PR นี้

- `static/index.html`: Branding และ Local Engine อยู่ใน Top Bar, ไม่มี Sidebar และ Stage numbers; ทำ Single-row Toolbar พร้อมชื่อปุ่ม “เตรียมโมเดลคนเดิน” และเมนู “เพิ่มเติม”; คง DOM IDs และ API contract
- `static/studio.css`: Full-width Workspace, Compact Toolbar สำหรับ Desktop, พื้นที่ 3D ที่ปรับตามความสูงหน้าจอ และ Responsive Breakpoint (1120/1060/730 px)
- `tests/test_ui_workbench_contract.py`: ทดสอบ DOM IDs, การไม่มี Sidebar ถาวร, Single-row Command Bar, ปุ่ม Semantic ที่เปลี่ยนชื่อ และ Automatic Simulation Preview
- `static/app.js`: แก้เฉพาะพฤติกรรมแจ้งสถานะหลัง Semantic Generation ให้ยืนยันการสลับ Simulation Preview ใน 3D และแจ้งเหตุหาก Preview ไม่พร้อม โดยไม่แตะ Backend/API
- ไม่มีการแก้ `app.py`, `app3d.js`, geometry engine, IFC parser, COM adapter หรือระบบ state

## 5. คำแนะนำการใช้งาน

- เปิดไฟล์ IFC แล้วระบบควร Audit + Load 3D อัตโนมัติเช่นเดิม (จาก PR #9)
- กดองค์ประกอบใน Viewer แล้วข้อมูลแสดงใน Inspector; สถานะ Include/Review/Exclude ต้องยังทำงานเหมือนเดิม
- เป้าหมาย UX คือให้ผู้ใช้ตรวจ Geometry ก่อน Build ตามลำดับที่แสดง; **ปัจจุบันต้องยังตรวจ Backend Validation Gate/สถานะปุ่มจริงใน Browser** ก่อนอ้างว่า UI บังคับ Validate แล้ว
- Download Semantic, Engine JSON และ INPX รวมทั้ง Analyze และ Load 3D ซ้ำ ย้ายเข้าเมนู **เพิ่มเติม** โดย Button IDs/handlers ยังเดิม
- รายละเอียด Large IFC / Audit / Semantic / Build ยังคงแสดงด้านล่างเพื่อไม่เปลี่ยน workflow ในรอบแรก
- รุ่นถัดไปสามารถทำ Inspector tabs, dockable panes, keyboard shortcuts, building-floor navigator และ persistent workspaces ได้โดยแยก PR

## 6. Manual QA ที่ยังต้องทำบน Windows

1. เปิดเว็บเมื่อยังไม่มีโมเดล: Viewer empty state แสดงและปุ่มใช้งานเฉพาะ Input
2. Import Small IFC → Audit & Load 3D: Three.js ไม่เกิด 1×1 Canvas, ไม่ถูก CSS บัง
3. คลิก Wall/Door/Slab → ตรวจ Inspector, การตั้งค่า Include/Review/Exclude และไฟล์ Semantic ที่ได้
4. Large IFC: เลือก Storey/Full mode/Append ไม่ขัดกับ Viewer
5. Generate Semantic → Validate → Build Vissim COM → Download
6. ทดสอบที่ 1920×1080, **1366×768 (Command Bar แถวเดียว)**, 1024×768 และ 390×844; ไม่เกิด horizontal overflow
7. ทดสอบ Keyboard focus, **เมนูเพิ่มเติม (รวม Analyze, Load 3D, Carry Selection, Export)**, Local Engine status popover, Disabled State และรีเฟรชหน้ากลาง Workflow

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
