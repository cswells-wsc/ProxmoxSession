# Proxmox Setup Wizard

The Setup Wizard performs first-time configuration of a Proxmox server for ProxmoxSession.
It logs in once as `root@pam`, creates the required groups, roles, and permissions, then
creates your initial superadmin user. After the wizard runs, you never need `root` again for
ongoing management — the superadmin account takes over.

---

## How to Launch

Open the **Config Editor** (Start Menu → ProxmoxSession Config, or Applications → ProxmoxSession Config).

Select the **Host tab** for the server you want to configure. At the bottom of the tab:

```
┌─ ProxmoxSession Server Setup ───────────────────────────────┐
│  [ Run Setup Wizard… ]   [ Manage Groups & Users… ]         │
└─────────────────────────────────────────────────────────────┘
```

Click **Run Setup Wizard…**

---

## Wizard Pages

### Page 1 — Welcome

Explains what the wizard will create. You can proceed or cancel.

### Page 2 — Root Login

Connect to your Proxmox server as `root@pam` (one time only).

- **Host** and **port** are pre-filled from your config
- **Realm** defaults to `pam` (Linux system accounts — correct for `root`)
- Click **Test Connection** to verify credentials before proceeding
- If the wizard has already been run on this server, a warning is shown — you can still
  re-run to create additional users or repair permissions

### Page 3 — Groups

Select which standard groups to create. `proxmoxsession_superadmin` and
`proxmoxsession_vdiuser` are always created. `proxmoxsession_admin` is optional.

Use **Add Custom Group** to create additional groups with a chosen role.

| Group | Role | VM Permissions |
|---|---|---|
| `proxmoxsession_superadmin` | ProxmoxSession.SuperAdmin | Manages groups and users |
| `proxmoxsession_admin` | ProxmoxSession.Admin | Full VM management |
| `proxmoxsession_vdiuser` | ProxmoxSession.VDIUser | SPICE connect + power only |

### Page 4 — Permissions

Choose the VM scope that ProxmoxSession groups will have access to:

| Option | Path | Use case |
|---|---|---|
| All VMs | `/vms` | Grant access to every VM on the server |
| Pool | `/pool/<name>` | Limit to VMs in a specific resource pool |
| VMIDs | `/vms/<id>` (one per VM) | Precise per-VM control |

### Page 5 — SuperAdmin User

Create the ongoing management account — a member of `proxmoxsession_superadmin`.

After the wizard runs, use this account (not `root`) to log into ProxmoxSession's
Manage window to add/remove users and groups.

### Page 6 — VDI Users (Optional)

Add initial end users. Each user is assigned to one of the groups created in page 3.
Skip this page if you want to add users later via the Manage window.

### Page 7 — Summary

Shows everything created (green) or failed (red). Review any failures and retry if needed.

---

## What Gets Created

### Resource Pool

The wizard creates the `proxmoxsession_resources` Proxmox resource pool. This is where
all ProxmoxSession-managed VMs and templates live. Admins manage VMs in this pool;
VDI users can deploy clones into it.

Add VMs and templates to this pool from the Proxmox web UI (Datacenter → Pool → Members)
or via the CLI: `pvesh create /pools/proxmoxsession_resources/members --vms 100,101`.

### Roles

| Role | Privileges |
|---|---|
| `ProxmoxSession.VDIUser` | `VM.Console VM.PowerMgmt VM.Audit VM.Clone` |
| `ProxmoxSession.Admin` | `VM.Console VM.PowerMgmt VM.Audit VM.Allocate VM.Config.Options VM.Clone Pool.Audit` |
| `ProxmoxSession.SuperAdmin` | `User.Modify Group.Allocate Permissions.Modify VM.Audit` |
| `ProxmoxSession.VDIDeploy` | `VM.Allocate Datastore.AllocateSpace` |

### ACLs

| Path | Group | Role | Purpose |
|---|---|---|---|
| `/vms` | `proxmoxsession_superadmin` | `ProxmoxSession.SuperAdmin` | Superadmin sees all VMs |
| `/pool/proxmoxsession_resources` | `proxmoxsession_admin` | `ProxmoxSession.Admin` | Admin manages pool VMs |
| `/pool/proxmoxsession_resources` | `proxmoxsession_vdiuser` | `ProxmoxSession.VDIDeploy` | VDI users can clone into pool |
| `/vms/<vmid>` | individual user | `ProxmoxSession.VDIUser` | Per-user VM assignment (via Manage window) |
| `/access/groups/proxmoxsession_*` | `proxmoxsession_superadmin` | `ProxmoxSession.SuperAdmin` | Superadmin manages groups |

### VM Access Model

- **SuperAdmin** sees all VMs on the cluster (via `VM.Audit` on `/vms`)
- **Admin** fully manages VMs in the `proxmoxsession_resources` pool
- **VDI Users** only see VMs explicitly assigned to them by an admin (per-VM ACLs on `/vms/<vmid>`)
- VDI Users can clone templates assigned to them — the clone is placed in the resource pool
  and must be assigned to them by an admin before they can connect

The superadmin group receives management access scoped to each `proxmoxsession_*` group path —
it cannot see or modify `root@pam` or any users outside ProxmoxSession groups.

---

## Root Protection

`root@pam` is never shown or modified by the wizard or the Manage window. The ProxmoxSession
superadmin role only grants `User.Modify` on `/access/groups/proxmoxsession_*` paths.

| Action | root@pam | proxmoxsession_* users |
|---|---|---|
| Login to Proxmox web UI | Always works | Works |
| Modify root@pam via wizard/app | Never — not shown | No permission |
| Manage proxmoxsession groups | Not needed | superadmin only |
| Connect to VMs | Has all permissions | Within assigned role |

---

## After the Wizard

Use **Manage Groups & Users…** in the Config Editor's Host tab to:

- Add or remove `proxmoxsession_*` groups
- Add, delete, or reset passwords for users in those groups
- Add or remove members from groups

You will be prompted for your superadmin credentials (not root) when you open the Manage window.

---

## Running on Multiple Clusters

Each Host tab in the Config Editor has its own wizard and manage buttons. Run the wizard
once per Proxmox server to set up each cluster independently.
