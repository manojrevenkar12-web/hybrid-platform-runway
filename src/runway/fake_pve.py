"""A fake Proxmox VE API for tests, drills and the demo, following the documented /api2/json shapes.

It keeps nodes, VMs and tasks in memory and fails on purpose: imports that fail, guests whose agent
never answers, and an API that is briefly unreachable. Faults are drawn from a seeded generator so
a drill is reproducible.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request


@dataclass
class Faults:
    import_failure_rate: float = 0.0
    agent_never_rate: float = 0.0
    api_error_rate: float = 0.0
    seed: int = 7


@dataclass
class FakeVM:
    vmid: int
    node: str
    name: str
    config: dict[str, Any]
    status: str = "stopped"
    agent_ok: bool = True
    macs: list[str] = field(default_factory=list)


class FakePVE:
    def __init__(self, nodes: dict[str, float], faults: Faults | None = None, token: str = "runway@pve!ci=secret"):
        self.nodes = nodes  # name -> memory GiB
        self.faults = faults or Faults()
        self.rnd = random.Random(self.faults.seed)
        self.vms: dict[int, FakeVM] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.token = token
        self.lock = threading.Lock()
        self.calls = 0
        self.app = self._app()

    def _task(self, node: str, kind: str, ok: bool = True, err: str = "") -> str:
        upid = f"UPID:{node}:{len(self.tasks):08X}:{int(time.time())}:{kind}:runway@pve:"
        self.tasks[upid] = {"status": "stopped", "exitstatus": "OK" if ok else err or "ERROR", "type": kind, "node": node}
        return upid

    def _vm(self, node: str, vmid: int) -> FakeVM:
        vm = self.vms.get(vmid)
        if vm is None or vm.node != node:
            raise HTTPException(500, f"Configuration file 'nodes/{node}/qemu-server/{vmid}.conf' does not exist")
        return vm

    def _app(self) -> FastAPI:
        app = FastAPI(title="fake Proxmox VE")

        @app.middleware("http")
        async def auth(request: Request, call_next: Any) -> Any:
            from fastapi.responses import JSONResponse

            self.calls += 1
            if request.headers.get("Authorization") != f"PVEAPIToken={self.token}":
                return JSONResponse({"data": None, "message": "authentication failure"}, status_code=401)
            if self.faults.api_error_rate and self.rnd.random() < self.faults.api_error_rate:
                return JSONResponse({"data": None, "message": "proxy loop"}, status_code=596)
            return await call_next(request)

        @app.get("/api2/json/nodes")
        def nodes() -> dict[str, Any]:
            used = {n: 0.0 for n in self.nodes}
            for v in self.vms.values():
                if v.status == "running":
                    used[v.node] += float(v.config.get("memory", 0)) / 1024
            return {
                "data": [
                    {"node": n, "status": "online", "maxmem": int(m * 2**30), "mem": int(used[n] * 2**30)}
                    for n, m in sorted(self.nodes.items())
                ]
            }

        @app.get("/api2/json/nodes/{node}/qemu")
        def qemu(node: str) -> dict[str, Any]:
            return {"data": [{"vmid": v.vmid, "name": v.name, "status": v.status} for v in self.vms.values() if v.node == node]}

        @app.post("/api2/json/nodes/{node}/qemu")
        async def create(node: str, request: Request) -> dict[str, Any]:
            form = dict(await request.form())
            vmid = int(str(form["vmid"]))
            with self.lock:
                if vmid in self.vms:
                    raise HTTPException(500, f"VM {vmid} already exists")
                if node not in self.nodes:
                    raise HTTPException(500, f"no such node {node!r}")
                if self.rnd.random() < self.faults.import_failure_rate:
                    return {"data": self._task(node, "qmcreate", ok=False, err="import failed: error reading source disk")}
                macs = [
                    str(v).split("=", 1)[1].split(",")[0].lower()
                    for k, v in form.items()
                    if k.startswith("net") and "=" in str(v)
                ]
                self.vms[vmid] = FakeVM(
                    vmid,
                    node,
                    str(form.get("name", vmid)),
                    {k: v for k, v in form.items() if k != "vmid"},
                    macs=macs,
                    agent_ok=self.rnd.random() >= self.faults.agent_never_rate,
                )
                return {"data": self._task(node, "qmcreate")}

        @app.get("/api2/json/nodes/{node}/qemu/{vmid}/config")
        def config(node: str, vmid: int) -> dict[str, Any]:
            return {"data": dict(self._vm(node, vmid).config, name=self._vm(node, vmid).name)}

        @app.put("/api2/json/nodes/{node}/qemu/{vmid}/config")
        async def set_config(node: str, vmid: int, request: Request) -> dict[str, Any]:
            vm = self._vm(node, vmid)
            vm.config.update(dict(await request.form()))
            return {"data": None}

        @app.get("/api2/json/nodes/{node}/qemu/{vmid}/status/current")
        def current(node: str, vmid: int) -> dict[str, Any]:
            return {"data": {"status": self._vm(node, vmid).status}}

        @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/start")
        def start(node: str, vmid: int) -> dict[str, Any]:
            self._vm(node, vmid).status = "running"
            return {"data": self._task(node, "qmstart")}

        @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/stop")
        def stop(node: str, vmid: int) -> dict[str, Any]:
            self._vm(node, vmid).status = "stopped"
            return {"data": self._task(node, "qmstop")}

        @app.delete("/api2/json/nodes/{node}/qemu/{vmid}")
        def destroy(node: str, vmid: int) -> dict[str, Any]:
            vm = self._vm(node, vmid)
            if vm.status == "running":
                raise HTTPException(500, f"VM {vmid} is running - destroy failed")
            del self.vms[vmid]
            return {"data": self._task(node, "qmdestroy")}

        @app.post("/api2/json/nodes/{node}/qemu/{vmid}/agent/ping")
        def ping(node: str, vmid: int) -> dict[str, Any]:
            vm = self._vm(node, vmid)
            if vm.status != "running" or not vm.agent_ok:
                raise HTTPException(500, "QEMU guest agent is not running")
            return {"data": {}}

        @app.get("/api2/json/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
        def ifaces(node: str, vmid: int) -> dict[str, Any]:
            vm = self._vm(node, vmid)
            if vm.status != "running" or not vm.agent_ok:
                raise HTTPException(500, "QEMU guest agent is not running")
            result = [
                {
                    "name": "lo",
                    "hardware-address": "00:00:00:00:00:00",
                    "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}],
                }
            ]
            for i, mac in enumerate(vm.macs):
                result.append(
                    {
                        "name": f"ens{18 + i}",
                        "hardware-address": mac,
                        "ip-addresses": [
                            {"ip-address": f"10.{vm.vmid % 250}.{i}.{10 + vm.vmid % 200}", "ip-address-type": "ipv4"}
                        ],
                    }
                )
            return {"data": {"result": result}}

        @app.get("/api2/json/nodes/{node}/tasks/{upid}/status")
        def task(node: str, upid: str) -> dict[str, Any]:
            t = self.tasks.get(upid)
            if not t:
                raise HTTPException(500, "no such task")
            return {"data": t}

        return app
