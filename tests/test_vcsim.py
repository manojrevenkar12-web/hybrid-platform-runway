"""Inventory against a real vSphere API: VMware's vCenter simulator (vcsim), run by CI.

Run locally with: docker run -p 8989:8989 vmware/vcsim, then
RUNWAY_VCENTER_URL=https://127.0.0.1:8989/sdk pytest -m vcsim
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from runway import inventory
from runway.assess import Assessor
from runway.model import Verdict

pytestmark = pytest.mark.vcsim

URL = os.environ.get("RUNWAY_VCENTER_URL", "https://127.0.0.1:8989/sdk")


@pytest.fixture(scope="module")
def si() -> Any:
    with inventory.connect(URL, "user", "pass", verify_tls=False) as s:
        yield s


def _wait(task: Any) -> None:
    from pyVmomi import vim

    while task.info.state not in (vim.TaskInfo.State.success, vim.TaskInfo.State.error):
        time.sleep(0.05)
    assert task.info.state == vim.TaskInfo.State.success, task.info.error


def _vms(si: Any) -> list[Any]:
    from pyVmomi import vim

    c = si.RetrieveContent()
    view = c.viewManager.CreateContainerView(c.rootFolder, [vim.VirtualMachine], True)
    try:
        return sorted(view.view, key=lambda v: v.name)
    finally:
        view.Destroy()


def test_discovers_every_vm_with_disks_nics_and_metadata(si: Any) -> None:
    from pyVmomi import vim

    vms = _vms(si)
    assert vms, "vcsim starts with VMs"
    first, second = vms[0], vms[1]
    # owners annotate VMs; runway reads the notes
    spec = vim.vm.ConfigSpec(
        annotation="runway.app=plm\nruntime note\nrunway.depends=ad, plm-db\nrunway.site=factory\nrunway.anti_affinity=plm",
        firmware="efi",
    )
    _wait(first.ReconfigVM_Task(spec))
    _wait(second.CreateSnapshot_Task(name="before-patch", memory=False, quiesce=False))

    found = {v.name: v for v in inventory.discover(si)}
    assert set(found) == {v.name for v in vms if not v.config.template}
    a = found[first.name]
    assert (a.app, a.depends_on, a.site, a.anti_affinity, a.firmware) == ("plm", ("ad", "plm-db"), "factory", "plm", "efi")
    assert a.disks and a.disks[0].size_gib > 0 and a.disks[0].datastore
    assert a.nics and a.nics[0].mac.count(":") == 5 and a.nics[0].portgroup
    assert found[second.name].snapshots >= 1
    assert a.memory_gib > 0 and a.cpus >= 1


def test_a_real_inventory_is_assessed_and_dumped(si: Any, tmp_path: Any) -> None:
    vms = inventory.discover(si)
    path = tmp_path / "inventory.json"
    inventory.dump(vms, path)
    assert inventory.load(path) == vms
    assessed = Assessor().assess_all(vms)
    # vcsim's "VM Network" port group is not in network_map: every VM is blocked until it is mapped
    assert all("unmapped-network" in {f.rule for f in x.findings} for x in assessed if x.vm.nics)
    assert all(x.verdict == Verdict.BLOCKED for x in assessed if x.vm.nics)
