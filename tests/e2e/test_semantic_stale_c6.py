"""C6 real-browser readiness after a change made outside the active tab."""
from __future__ import annotations

import os
import pytest

from tests.e2e.test_browser_workflow import page, server, _open
from tests.ifc_factory import Building

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def test_c6_server_stale_disables_validate_and_exports_until_regeneration(page, server, tmp_path):
    b = Building([0.0])
    slab = b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], 0.0, b.storeys[0])
    _open(page, b.write(tmp_path / "c6.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function(
        "() => !document.getElementById('validateBtn').disabled "
        "&& !document.getElementById('downloadSemanticTopBtn').disabled",
        timeout=120000,
    )

    # Another tab writes a selection without calling this tab's local
    # markSemanticStale. Only the project API reports the true semantic state.
    changed = page.request.post(server + "/api/selection", data={
        "global_id": slab.GlobalId, "status": "exclude",
    })
    assert changed.status == 200, changed.text()
    state = page.request.get(server + "/api/project").json()
    assert state["semantic"]["stale"] is True

    page.evaluate("refreshWorkflowState()")
    page.wait_for_function("""() => {
        const ids = ['validateBtn', 'downloadSemanticTopBtn',
                     'downloadEngineTopBtn', 'exportEngineBtn', 'buildViswalkBtn'];
        return ids.every(id => document.getElementById(id).disabled)
          && !document.getElementById('staleBanner').classList.contains('hidden');
    }""", timeout=15000)

    # Regenerate after the external change: backend becomes authoritative
    # ready again and the browser unlocks only then.
    page.click("#generateSemanticBtn")
    page.wait_for_function("""() =>
        !document.getElementById('downloadSemanticTopBtn').disabled
        && !document.getElementById('validateBtn').disabled
        && document.getElementById('staleBanner').classList.contains('hidden')
    """, timeout=120000)
    assert page.request.get(server + "/api/project").json()["semantic"]["stale"] is False
    assert page.errors == []
