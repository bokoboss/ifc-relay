# Large IFC loading: measurements

How long opening and preparing large IFCs takes, and what limits it. The
large test models are not in the repository and are named here by size only.

Machine: cloud test container, 2 CPU cores, 7.8 GB RAM, Linux, IfcOpenShell 0.9.0.
An engineer's PC with more cores is faster; peak memory does not depend on the
core count. Old and new were run back to back on the same machine.

## Where the time goes (before)

Opening a 27 MB model end to end in the browser: import + audit ~1.5 s,
**tessellation (IfcOpenShell, server side) ~12 s**, JSON + drawing in the
browser ~0.3 s. The web front end is not the bottleneck; tessellation is.

| Model | Open | Audit | Core tier | Review tier | Peak per process | Meshes to the browser |
| --- | --- | --- | --- | --- | --- | --- |
| A 109 MB · 4,193 elements | 3 s | 5 s | 56 s | 65 s | 1.35 GB | 21 + 13 MB |
| B 162 MB · 11,829 elements | 5 s | 7 s | 57 s | 130 s | 1.56 GB | 26 + 28 MB |
| C 371 MB · 36,503 elements | 12 s | 16 s | 499 s | 496 s | **4.8 GB** | **140 + 137 MB** |

Opening needs about 6x the file size in memory, tessellating about 13x. With
two tessellation workers allowed at once plus the server process holding the
IFC, model C could need over 9 GB: the likely cause of "sometimes it does not
open".

## Changes (perf/large-ifc-loading)

1. **Shared geometry.** The iterator works in local coordinates, so elements
   that share a representation are tessellated once; each element is placed
   with its own 4x4 transformation (column-major). World vertices are the same
   as before (checked element by element below).
2. **Memory-scheduled jobs** (`model_jobs.py`). Audit, revision compare,
   tessellation, pedestrian model and stair overview each run in a fresh
   worker process that exits afterwards. Jobs run side by side only while their
   estimated peaks (6.5x / 14x file size + 400 MB) fit in 75% of physical RAM;
   otherwise they queue. A worker that dies is reported with the estimate and
   the computer's RAM, instead of an empty view.
3. **Failures are errors, partial results are said.** An iterator that cannot
   start, or a request where no element meshes, raises `GeometryFailed`.
   Elements that fail are listed on screen and reach the before-build list
   (`mesh_failed`, check).
4. **Content-keyed cache.** Geometry and audit are cached by the IFC's SHA-256
   (recorded at import), the extractor version and every request condition, so
   a re-import of the same file opens from the cache. Meshes go to the browser
   straight from the cache file; the server never parses them. Pruned beyond
   `VBB_CACHE_MAX_GB` (default 4).
5. **Preflight.** Files over 150 MB open one storey at a time by default (as
   do models with more than 4,000 simulation meshes).
6. **Log.** Every job writes time, peak memory, estimate, wait and outcome to
   `runtime/logs/performance.jsonl`.

## Before / after (same machine, back to back)

| Model · tier | Before | After | Peak before → after | Same geometry |
| --- | --- | --- | --- | --- |
| A · core | 56 s | 50 s | 1.07 → 1.09 GB | 3,644 / 3,644 identical |
| A · review | 65 s | 57 s | 1.35 → 1.21 GB | 270 / 270 identical |
| B · core | 57 s | 50 s | 1.20 → 1.22 GB | 4,456 identical + 4 same triangles, other vertex order |
| B · review | 130 s | **82 s** | 1.56 → 1.39 GB | 7,052 / 7,052 identical |
| C · core | 499 s | **282 s** | 4.78 → 4.62 GB | 33,084 identical + 131 same triangles, other vertex order |
| C · review | 496 s | **46 s** | 2.70 → 2.20 GB | 951 / 951 identical |

"Identical": same entity, GlobalId, metadata, vertices and triangle indices.
"Same triangles": the same set of triangles (coordinates to 0.01 mm) with the
vertices numbered differently. No element changed shape; no element was
missing or added.

Pedestrian models of two further test models (27 MB and 26 MB, with and
without plan edits) are byte-identical before and after.

Re-import of the same file (model A, through the app with real worker
processes): audit 4.2 s → 0.0 s, geometry 52 s → 0.5 s.

## One storey over the view limit

Through the app (real worker processes), model C opens one storey at a time,
but its "second level" storey alone has 16,816 simulation-relevant elements
(10,034 IfcMember + 6,129 IfcPlate, a curtain-wall roof): the 3D view refused it
at 12,000 elements per request, so that storey could not be opened at all.
With the limit raised for the test: 818k triangles, browser parse 0.9 s, mesh
build 0.4 s, JS heap 322 MB. The per-request view limit is now 25,000
(`VBB_VIEW_MAX_ELEMENTS`), and going over it gives a plain message. Frame rate
on a real GPU with ~17k separate meshes is not measured yet (the test machine
renders in software); merging meshes per storey/class is the fix if it is slow.

## Ground storey of model C (reported: Chrome nearly froze)

7,541 elements, 2.26 M triangles, of which 246 doors (manufacturer families up
to 148,000 triangles each) were 1.7 M; the review tier adds 1.9 M more.

- Old version on the 7.8 GB test machine: the server process was killed by the
  system (out of memory) while opening this storey.
- New version: the storey job peaked at 4.2 GB (one job at a time), and the
  browser received the view copy: 294k triangles, JSON parse 0.15 s, mesh build
  0.14 s, JS heap 67 MB. The 3D view also shares materials and draws frames on
  demand. Tessellating the storey took 232 s on 2 cores (each storey request
  reads the whole 371 MB IFC again).

## Still open

- Frame rate with tens of thousands of meshes on a real GPU (see above).
- Peak memory per job is unchanged (meshes are held as Python lists): the
  scheduler keeps jobs from adding up, but one model-C job still needs ~4.7 GB.
- Model C's meshes are 140 MB of JSON per request: binary transfer and
  per-storey streaming are the next step for models of that size.
