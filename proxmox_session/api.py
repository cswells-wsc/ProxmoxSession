"""
Proxmox API helpers — VM listing and VM actions (start, stop, connect).
All Proxmox API calls are isolated here, away from the UI layer.
"""

from dataclasses import dataclass
from typing import Optional

import proxmoxer
import requests


@dataclass
class VMInfo:
    vmid: int
    name: str
    node: str
    vmtype: str         # "qemu" or "lxc"
    status: str         # "running", "stopped", "suspended", ...
    lock: Optional[str] = None
    is_template: bool = False


class ProxmoxAPIError(Exception):
    pass


def get_vms(proxmox: proxmoxer.ProxmoxAPI, guest_type: str = "both") -> list[VMInfo]:
    """
    Return all non-template VMs the current user can see, filtered by guest_type.
    guest_type: "both", "qemu", or "lxc"
    Raises ProxmoxAPIError on failure.
    """
    try:
        online_nodes = {
            node["node"]
            for node in proxmox.cluster.resources.get(type="node")
            if node["status"] == "online"
        }

        vms = []
        for vm in proxmox.cluster.resources.get(type="vm"):
            if vm["node"] not in online_nodes:
                continue
            if vm.get("template"):
                continue
            if guest_type != "both" and vm["type"] != guest_type:
                continue
            vms.append(
                VMInfo(
                    vmid=vm["vmid"],
                    name=vm.get("name", f"VM {vm['vmid']}"),
                    node=vm["node"],
                    vmtype=vm["type"],
                    status=vm.get("status", "unknown"),
                    lock=vm.get("lock"),
                )
            )
        return vms

    except proxmoxer.core.ResourceException as e:
        raise ProxmoxAPIError(f"Failed to list VMs: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise ProxmoxAPIError(f"Connection lost: {e}") from e


def start_vm(proxmox: proxmoxer.ProxmoxAPI, vm: VMInfo, timeout: int = 28) -> str:
    """Start a VM. Returns the task job ID."""
    try:
        if vm.vmtype == "qemu":
            return proxmox.nodes(vm.node).qemu(str(vm.vmid)).status.start.post(timeout=timeout)
        else:
            return proxmox.nodes(vm.node).lxc(str(vm.vmid)).status.start.post(timeout=timeout)
    except proxmoxer.core.ResourceException as e:
        raise ProxmoxAPIError(f"Failed to start VM {vm.vmid}: {e}") from e


def stop_vm(proxmox: proxmoxer.ProxmoxAPI, vm: VMInfo, timeout: int = 28) -> str:
    """Stop a VM. Returns the task job ID."""
    try:
        if vm.vmtype == "qemu":
            return proxmox.nodes(vm.node).qemu(str(vm.vmid)).status.stop.post(timeout=timeout)
        else:
            return proxmox.nodes(vm.node).lxc(str(vm.vmid)).status.stop.post(timeout=timeout)
    except proxmoxer.core.ResourceException as e:
        raise ProxmoxAPIError(f"Failed to stop VM {vm.vmid}: {e}") from e


def get_vm_status(proxmox: proxmoxer.ProxmoxAPI, vm: VMInfo) -> dict:
    """Fetch current status dict for a single VM."""
    try:
        if vm.vmtype == "qemu":
            return proxmox.nodes(vm.node).qemu(str(vm.vmid)).status.get("current")
        else:
            return proxmox.nodes(vm.node).lxc(str(vm.vmid)).status.get("current")
    except proxmoxer.core.ResourceException as e:
        raise ProxmoxAPIError(f"Failed to get status for VM {vm.vmid}: {e}") from e


def wait_for_task(proxmox: proxmoxer.ProxmoxAPI, node: str, job_id: str, max_wait: int = 30) -> bool:
    """
    Poll a Proxmox task until it finishes or max_wait seconds pass.
    Returns True if the task exited with OK, False otherwise.
    """
    import time
    for _ in range(max_wait):
        try:
            status = proxmox.nodes(node).tasks(job_id).status.get()
        except Exception:
            status = {}
        if "exitstatus" in status:
            return status["exitstatus"] == "OK"
        time.sleep(1)
    return False


def get_spice_config(proxmox: proxmoxer.ProxmoxAPI, vm: VMInfo) -> dict:
    """
    Request a SPICE proxy config from Proxmox for the given VM.
    Raises ProxmoxAPIError if SPICE is not configured on the VM.
    """
    try:
        if vm.vmtype == "qemu":
            return proxmox.nodes(vm.node).qemu(str(vm.vmid)).spiceproxy.post()
        else:
            return proxmox.nodes(vm.node).lxc(str(vm.vmid)).spiceproxy.post()
    except proxmoxer.core.ResourceException as e:
        raise ProxmoxAPIError(
            f"Could not get SPICE config for VM {vm.vmid}. "
            f"Is SPICE display configured?\n{e}"
        ) from e
