"""A small client for the Proxmox VE REST API (/api2/json), with API-token authentication.

Only what a migration needs: nodes, VM configs, creating a VM that imports its disks from an ESXi
storage, starting and stopping, the guest agent, and waiting for tasks (UPIDs).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


class ProxmoxError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskResult:
    upid: str
    ok: bool
    exitstatus: str


class Proxmox:
    def __init__(
        self,
        http: httpx.Client,
        token: str | None = None,
        base: str = "/api2/json",
        poll_s: float = 0.5,
        task_timeout_s: float = 3600,
    ):
        self.http = http
        self.base = base
        self.poll_s = poll_s
        self.task_timeout_s = task_timeout_s
        if token:
            self.http.headers["Authorization"] = f"PVEAPIToken={token}"

    TRANSIENT = (502, 503, 504, 596)  # 596: Proxmox's "broken pipe / proxy" status between nodes

    def _req(self, method: str, path: str, retry: bool = True, **kw: Any) -> Any:
        """One API call. Transient failures are retried, except where a retry could act twice
        (creating a VM): the caller decides there, with the journal to go on."""
        attempts = 3 if retry else 1
        for n in range(attempts):
            try:
                r = self.http.request(method, self.base + path, **kw)
            except httpx.TransportError as e:
                if n + 1 == attempts:
                    raise ProxmoxError(f"{method} {path}: {e}") from e
                time.sleep(self.poll_s)
                continue
            if r.status_code in self.TRANSIENT and n + 1 < attempts:
                time.sleep(self.poll_s)
                continue
            if r.status_code >= 400:
                raise ProxmoxError(f"{method} {path}: {r.status_code} {r.text[:200]}")
            return r.json().get("data")
        raise ProxmoxError(f"{method} {path}: no answer")

    def nodes(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/nodes") or [])

    def vms(self, node: str) -> list[dict[str, Any]]:
        return list(self._req("GET", f"/nodes/{node}/qemu") or [])

    def find(self, vmid: int) -> str | None:
        """The node a VM id lives on, or None."""
        for n in self.nodes():
            if any(int(v["vmid"]) == vmid for v in self.vms(n["node"])):
                return str(n["node"])
        return None

    def config(self, node: str, vmid: int) -> dict[str, Any]:
        return dict(self._req("GET", f"/nodes/{node}/qemu/{vmid}/config") or {})

    def status(self, node: str, vmid: int) -> str:
        return str((self._req("GET", f"/nodes/{node}/qemu/{vmid}/status/current") or {}).get("status", "unknown"))

    def create(self, node: str, params: dict[str, Any]) -> str:
        return str(self._req("POST", f"/nodes/{node}/qemu", retry=False, data=params))

    def start(self, node: str, vmid: int) -> str:
        return str(self._req("POST", f"/nodes/{node}/qemu/{vmid}/status/start"))

    def stop(self, node: str, vmid: int) -> str:
        return str(self._req("POST", f"/nodes/{node}/qemu/{vmid}/status/stop"))

    def destroy(self, node: str, vmid: int) -> str:
        return str(self._req("DELETE", f"/nodes/{node}/qemu/{vmid}", params={"purge": 1, "destroy-unreferenced-disks": 1}))

    def agent_ping(self, node: str, vmid: int) -> bool:
        try:
            self._req("POST", f"/nodes/{node}/qemu/{vmid}/agent/ping")
            return True
        except ProxmoxError:
            return False

    def agent_interfaces(self, node: str, vmid: int) -> list[dict[str, Any]]:
        data = self._req("GET", f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces") or {}
        return list(data.get("result", []))

    def wait(self, node: str, upid: str) -> TaskResult:
        deadline = time.monotonic() + self.task_timeout_s
        while time.monotonic() < deadline:
            st = self._req("GET", f"/nodes/{node}/tasks/{upid}/status") or {}
            if st.get("status") == "stopped":
                ex = str(st.get("exitstatus", ""))
                return TaskResult(upid, ex == "OK", ex)
            time.sleep(self.poll_s)
        raise ProxmoxError(f"task {upid} did not finish in {self.task_timeout_s}s")
