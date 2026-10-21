"""One place for every version the app reports (review F-20).

* APP_VERSION              - this application (UI + API + converter)
* PROJECT_STATE_VERSION    - layout of runtime/project_state.json
* GEOMETRY_PAYLOAD_VERSION - browser/semantic mesh payload from IFC
* SEMANTIC_SCHEMA_VERSION  - pedestrian-model JSON handed to the Geometry Engine
* ENGINE_CONTRACT          - the Geometry Engine the JSON is written for
* SUPPORTED_VISSIM         - Vissim release/COM ProgID the build is tested with
"""
APP_VERSION = "0.6.0"
PROJECT_STATE_VERSION = "0.6"
GEOMETRY_PAYLOAD_VERSION = "0.6"
SEMANTIC_SCHEMA_VERSION = "0.6.0"
ENGINE_CONTRACT = "Geometry Engine v0.3 (engine/05_geometry_engine_v03.py)"
SUPPORTED_VISSIM = "PTV Vissim 2025 SP15 and 2026 (both tested; picks the newest installed via COM)"

CREDIT = "Orchestrated by KITTIPAT TANGITTINUNT"


def versions() -> dict[str, str]:
    return {
        "app_version": APP_VERSION,
        "project_state_version": PROJECT_STATE_VERSION,
        "geometry_payload_version": GEOMETRY_PAYLOAD_VERSION,
        "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
        "engine_contract": ENGINE_CONTRACT,
        "supported_vissim": SUPPORTED_VISSIM,
        "credit": CREDIT,
    }
