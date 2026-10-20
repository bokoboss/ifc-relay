# v0.4.1a Storey Auto-Select Hotfix

Fixes a Large IFC viewer issue where the first storey by elevation could contain zero simulation-relevant meshes.

For the current 30-storey structural IFC, the lowest Pit Lift storey at -5 m is spatially valid but contains no simulation-relevant IfcElement geometry. The previous UI selected it automatically, so Load 3D returned zero meshes and appeared blank.

Changes:
- Audit now reports `simulation_mesh_count` per storey.
- Simulation-storey mode auto-selects the first storey with meshable simulation geometry.
- Storey dropdown shows `N sim meshes` or `no simulation geometry`.
- A zero-mesh request reports a clear message instead of silently showing an empty viewer.

Apply over `local_web_app_v041`, restart the server, and hard-refresh the browser.
