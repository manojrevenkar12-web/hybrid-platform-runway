"""The vSphere side of a cutover: stop the source VM, and start it again if the move is rolled back."""

from __future__ import annotations

import time
from typing import Any, Protocol

from runway.model import VM


class Source(Protocol):
    def power_state(self, vm: VM) -> str: ...  # "on" | "off"

    def stop(self, vm: VM, grace_s: float) -> None: ...

    def start(self, vm: VM) -> None: ...

    def import_path(self, vm: VM, disk_index: int) -> str: ...


class VSphereSource:
    """pyVmomi implementation. Guest shutdown first (clean filesystems), power off after the grace time."""

    def __init__(self, si: Any, esxi_storage: dict[str, str], poll_s: float = 2.0):
        self.si = si
        self.esxi_storage = esxi_storage  # site -> Proxmox ESXi storage id, e.g. {"hq": "esxi-hq"}
        self.poll_s = poll_s

    def _vm(self, vm: VM) -> Any:
        from pyVmomi import vim

        content = self.si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        try:
            for v in view.view:
                if v._moId == vm.moid:
                    return v
        finally:
            view.Destroy()
        raise LookupError(f"{vm.name} ({vm.moid}) not found in vCenter")

    def power_state(self, vm: VM) -> str:
        return "on" if str(self._vm(vm).runtime.powerState) == "poweredOn" else "off"

    def _wait(self, task: Any) -> None:
        from pyVmomi import vim

        while task.info.state not in (vim.TaskInfo.State.success, vim.TaskInfo.State.error):
            time.sleep(self.poll_s)
        if task.info.state == vim.TaskInfo.State.error:
            raise RuntimeError(str(task.info.error.msg if task.info.error else "vSphere task failed"))

    def stop(self, vm: VM, grace_s: float) -> None:
        v = self._vm(vm)
        if str(v.runtime.powerState) != "poweredOn":
            return
        try:
            v.ShutdownGuest()
            deadline = time.monotonic() + grace_s
            while time.monotonic() < deadline and str(v.runtime.powerState) == "poweredOn":
                time.sleep(self.poll_s)
        except Exception:  # no tools, or tools not running: fall through to power off
            pass
        if str(v.runtime.powerState) == "poweredOn":
            self._wait(v.PowerOffVM_Task())

    def start(self, vm: VM) -> None:
        v = self._vm(vm)
        if str(v.runtime.powerState) != "poweredOn":
            self._wait(v.PowerOnVM_Task())

    def import_path(self, vm: VM, disk_index: int) -> str:
        d = vm.disks[disk_index]
        suffix = "" if disk_index == 0 else f"_{disk_index}"
        return f"{self.esxi_storage.get(vm.site, 'esxi')}:ha-datacenter/{d.datastore}/{vm.name}/{vm.name}{suffix}.vmdk"


class FakeSource:
    """In-memory vSphere for tests and drills. Records every state change."""

    def __init__(self, vms: list[VM], stop_failure: set[str] | None = None, start_failure: set[str] | None = None):
        self.state = {v.moid: "on" if v.powered_on else "off" for v in vms}
        self.stop_failure = stop_failure or set()
        self.start_failure = start_failure or set()
        self.log: list[tuple[str, str]] = []

    def power_state(self, vm: VM) -> str:
        return self.state[vm.moid]

    def stop(self, vm: VM, grace_s: float) -> None:
        if vm.name in self.stop_failure:
            raise RuntimeError(f"{vm.name}: vCenter refused to power off")
        self.state[vm.moid] = "off"
        self.log.append((vm.name, "off"))

    def start(self, vm: VM) -> None:
        if vm.name in self.start_failure:
            raise RuntimeError(f"{vm.name}: vCenter could not power on")
        self.state[vm.moid] = "on"
        self.log.append((vm.name, "on"))

    def import_path(self, vm: VM, disk_index: int) -> str:
        return f"esxi-{vm.site}:ha-datacenter/{vm.disks[disk_index].datastore}/{vm.name}/{vm.name}.vmdk"
