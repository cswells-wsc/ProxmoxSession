"""
Proxmox access management — groups, users, roles, ACLs, and resource pool
for ProxmoxSession.

All ProxmoxSession-managed objects use the prefix "proxmoxsession_" for groups
and "ProxmoxSession." for roles so they can be identified and managed independently
of any other Proxmox configuration.
"""

import logging
from typing import Optional

import proxmoxer

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

PREFIX = "proxmoxsession_"
POOL_NAME = "proxmoxsession_resources"

ROLES: dict[str, str] = {
    # Per-VM role for individual user assignments: view, power, SPICE, clone
    "ProxmoxSession.VDIUser":   "VM.Console VM.PowerMgmt VM.Audit VM.Clone",
    # Pool-level admin role: full VM management within the resource pool
    "ProxmoxSession.Admin":     "VM.Console VM.PowerMgmt VM.Audit VM.Allocate VM.Config.Options VM.Clone Pool.Audit",
    # Superadmin: manage groups/users + view all VMs/pools + cluster audit
    # Sys.Audit  — read cluster/node status and resources (needed for get_vms node filter)
    # Pool.Audit — read pool members (VM Assignments tab)
    # User.Modify + propagate=1 on /access covers listing users and groups
    "ProxmoxSession.SuperAdmin": (
        "User.Modify Group.Allocate Permissions.Modify "
        "VM.Audit Pool.Audit Sys.Audit"
    ),
    # Pool deploy role for VDI users: lets them clone templates into the pool
    "ProxmoxSession.VDIDeploy": "VM.Allocate Datastore.AllocateSpace",
}

# Standard groups created by the wizard
STANDARD_GROUPS: dict[str, dict] = {
    "superadmin": {
        "comment": "ProxmoxSession superadmin — manages PS groups, users, and VMs",
        "role": "ProxmoxSession.SuperAdmin",
    },
    "admin": {
        "comment": "ProxmoxSession admin — full VM management in resource pool",
        "role": "ProxmoxSession.Admin",
    },
    "vdiuser": {
        "comment": "ProxmoxSession VDI user — SPICE connect and power on assigned VMs",
        "role": "ProxmoxSession.VDIUser",
    },
}

# Users that must never be modified or shown in any UI
_PROTECTED_USERS = {"root@pam"}


# ── Protection helpers ────────────────────────────────────────────────────────

def is_protected(userid: str) -> bool:
    """Return True if userid must never be modified or deleted by ProxmoxSession."""
    return userid in _PROTECTED_USERS


def group_name(short_name: str) -> str:
    """Return the full group ID for a short name, e.g. 'vdiuser' → 'proxmoxsession_vdiuser'."""
    if short_name.startswith(PREFIX):
        return short_name
    return f"{PREFIX}{short_name}"


def role_name(short_name: str) -> str:
    """Return the full role ID, e.g. 'VDIUser' → 'ProxmoxSession.VDIUser'."""
    if short_name.startswith("ProxmoxSession."):
        return short_name
    return f"ProxmoxSession.{short_name}"


# ── Idempotent resource creation ───────────────────────────────────────────────

def create_proxmoxsession_roles(proxmox: proxmoxer.ProxmoxAPI) -> list[str]:
    """
    Create or update all ProxmoxSession.* roles.
    Existing roles are updated in-place so re-running the wizard repairs permissions.
    Returns list of role IDs that were created (not updated).
    """
    created = []
    existing = {r["roleid"] for r in proxmox.access.roles.get()}

    for roleid, privs in ROLES.items():
        # Normalize multi-line privilege strings to a single space-separated value
        privs_str = " ".join(privs.split())
        if roleid in existing:
            # Always update to ensure privileges are current
            proxmox.access.roles(roleid).put(privs=privs_str)
            log.info("Updated role privileges: %s", roleid)
        else:
            proxmox.access.roles.post(roleid=roleid, privs=privs_str)
            log.info("Created role: %s", roleid)
            created.append(roleid)

    return created


def create_proxmoxsession_pool(proxmox: proxmoxer.ProxmoxAPI) -> bool:
    """
    Create the proxmoxsession_resources resource pool. Idempotent.
    Returns True if created, False if already existed.
    """
    try:
        existing = {p["poolid"] for p in proxmox.pools.get()}
    except Exception:
        existing = set()

    if POOL_NAME in existing:
        log.debug("Pool %s already exists", POOL_NAME)
        return False

    try:
        proxmox.pools.post(
            poolid=POOL_NAME,
            comment="ProxmoxSession managed VMs and templates",
        )
        log.info("Created pool: %s", POOL_NAME)
        return True
    except proxmoxer.core.ResourceException as e:
        if e.status_code == 409:
            log.debug("Pool %s already exists (409)", POOL_NAME)
            return False
        raise


def create_proxmoxsession_group(
    proxmox: proxmoxer.ProxmoxAPI,
    short_name: str,
    comment: str = "",
) -> bool:
    """
    Create proxmoxsession_{short_name} group. Idempotent.
    Returns True if created, False if already existed.
    """
    groupid = group_name(short_name)
    try:
        proxmox.access.groups.post(groupid=groupid, comment=comment)
        log.info("Created group: %s", groupid)
        return True
    except proxmoxer.core.ResourceException as e:
        if e.status_code == 409:
            log.debug("Group %s already exists", groupid)
            return False
        raise


def assign_group_permissions(
    proxmox: proxmoxer.ProxmoxAPI,
    short_name: str,
    vm_path: str = "/vms",
) -> None:
    """
    Assign the appropriate ProxmoxSession role to a standard group.

    ACL model:
    - superadmin → /vms (VM.Audit view of all VMs) + /access/groups management
    - admin       → /pool/proxmoxsession_resources (full management of pool VMs)
    - vdiuser     → /pool/proxmoxsession_resources (VDIDeploy: allocate for cloning)
                    individual VM access is granted per-user via assign_vm_to_user()

    Also grants superadmin management access to this group.
    """
    groupid = group_name(short_name)
    group_info = STANDARD_GROUPS.get(short_name)
    assigned_role = group_info["role"] if group_info else "ProxmoxSession.VDIUser"

    if short_name == "superadmin":
        # SuperAdmin sees all VMs at /vms level (VM.Audit)
        proxmox.access.acl.put(
            path="/vms",
            groups=groupid,
            roles="ProxmoxSession.SuperAdmin",
            propagate=1,
        )
        log.info("ACL: %s → ProxmoxSession.SuperAdmin on /vms", groupid)
        # SuperAdmin needs the role on /access with propagate=1 so it covers
        # /access/users (User.Audit/Modify), /access/groups (Group.Allocate/Audit),
        # and /access/roles — without propagation these sub-paths are not covered.
        proxmox.access.acl.put(
            path="/access",
            groups=groupid,
            roles="ProxmoxSession.SuperAdmin",
            propagate=1,
        )
        log.info("ACL: %s → ProxmoxSession.SuperAdmin on /access (propagate)", groupid)
    elif short_name == "admin":
        # Admin manages VMs in the resource pool
        pool_path = f"/pool/{POOL_NAME}"
        proxmox.access.acl.put(
            path=pool_path,
            groups=groupid,
            roles="ProxmoxSession.Admin",
            propagate=1,
        )
        log.info("ACL: %s → ProxmoxSession.Admin on %s", groupid, pool_path)
    elif short_name == "vdiuser":
        # VDIUser group gets deploy (allocate/clone) permission on the pool
        # Individual VM access is per-user via assign_vm_to_user()
        pool_path = f"/pool/{POOL_NAME}"
        proxmox.access.acl.put(
            path=pool_path,
            groups=groupid,
            roles="ProxmoxSession.VDIDeploy",
            propagate=1,
        )
        log.info("ACL: %s → ProxmoxSession.VDIDeploy on %s", groupid, pool_path)
    else:
        # Custom group — use vm_path
        proxmox.access.acl.put(
            path=vm_path,
            groups=groupid,
            roles=assigned_role,
            propagate=1,
        )
        log.info("ACL: %s → %s on %s", groupid, assigned_role, vm_path)

    # Grant superadmin management access to this group
    superadmin_groupid = group_name("superadmin")
    proxmox.access.acl.put(
        path=f"/access/groups/{groupid}",
        groups=superadmin_groupid,
        roles="ProxmoxSession.SuperAdmin",
        propagate=1,
    )
    log.info("ACL: %s → ProxmoxSession.SuperAdmin on /access/groups/%s", superadmin_groupid, groupid)


def assign_custom_group_permissions(
    proxmox: proxmoxer.ProxmoxAPI,
    short_name: str,
    role_short: str,
    vm_path: str = "/vms",
) -> None:
    """
    Assign a chosen role to a custom group and grant superadmin management access.
    role_short: 'VDIUser', 'Admin', or 'SuperAdmin'
    """
    groupid = group_name(short_name)
    roleid = role_name(role_short)

    proxmox.access.acl.put(
        path=vm_path,
        groups=groupid,
        roles=roleid,
        propagate=1,
    )
    log.info("ACL: %s → %s on %s", groupid, roleid, vm_path)

    superadmin_groupid = group_name("superadmin")
    proxmox.access.acl.put(
        path=f"/access/groups/{groupid}",
        groups=superadmin_groupid,
        roles="ProxmoxSession.SuperAdmin",
        propagate=1,
    )
    log.info("ACL: superadmin management on /access/groups/%s", groupid)


def create_user(
    proxmox: proxmoxer.ProxmoxAPI,
    username: str,
    password: str,
    short_group: str,
    realm: str = "pve",
    email: str = "",
    firstname: str = "",
    lastname: str = "",
) -> str:
    """
    Create username@realm and add to proxmoxsession_{short_group}.
    Returns the full userid string.
    Raises ValueError if username is protected.
    """
    userid = f"{username}@{realm}"
    if is_protected(userid):
        raise ValueError(f"Cannot create or modify protected user: {userid}")

    groupid = group_name(short_group)
    proxmox.access.users.post(
        userid=userid,
        password=password,
        groups=groupid,
        email=email,
        firstname=firstname,
        lastname=lastname,
        enable=1,
    )
    log.info("Created user: %s in group %s", userid, groupid)
    return userid


# ── Per-user VM assignment ────────────────────────────────────────────────────

def assign_vm_to_user(
    proxmox: proxmoxer.ProxmoxAPI,
    userid: str,
    vmid: int,
) -> None:
    """
    Grant a specific user access to a single VM or template via ACL.
    The user gets ProxmoxSession.VDIUser role on /vms/<vmid>.
    """
    if is_protected(userid):
        raise ValueError(f"Cannot assign VMs to protected user: {userid}")
    path = f"/vms/{vmid}"
    proxmox.access.acl.put(
        path=path,
        users=userid,
        roles="ProxmoxSession.VDIUser",
        propagate=1,
    )
    log.info("ACL: %s → ProxmoxSession.VDIUser on %s", userid, path)


def unassign_vm_from_user(
    proxmox: proxmoxer.ProxmoxAPI,
    userid: str,
    vmid: int,
) -> None:
    """
    Remove a user's ACL on a specific VM.
    """
    if is_protected(userid):
        return
    path = f"/vms/{vmid}"
    try:
        proxmox.access.acl.put(
            path=path,
            users=userid,
            roles="ProxmoxSession.VDIUser",
            propagate=1,
            delete=1,
        )
        log.info("Removed ACL: %s on %s", userid, path)
    except Exception as e:
        log.warning("Could not remove ACL for %s on %s: %s", userid, path, e)


def list_vmids_for_user(proxmox: proxmoxer.ProxmoxAPI, userid: str) -> list[int]:
    """
    Return list of VMIDs that have a direct ACL entry for this user
    (i.e. VMs explicitly assigned to them).
    """
    vmids = []
    try:
        for entry in proxmox.access.acl.get():
            if entry.get("ugid") == userid and entry.get("type") == "user":
                path = entry.get("path", "")
                if path.startswith("/vms/"):
                    try:
                        vmids.append(int(path.split("/")[-1]))
                    except ValueError:
                        pass
    except Exception as e:
        log.warning("Could not list ACLs for user %s: %s", userid, e)
    return vmids


# ── Listing helpers ───────────────────────────────────────────────────────────

def list_proxmoxsession_groups(proxmox: proxmoxer.ProxmoxAPI) -> list[dict]:
    """Return only groups whose groupid starts with proxmoxsession_."""
    return [g for g in proxmox.access.groups.get() if g["groupid"].startswith(PREFIX)]


def list_proxmoxsession_users(proxmox: proxmoxer.ProxmoxAPI) -> list[dict]:
    """
    Return users who belong to at least one proxmoxsession_ group.
    Excludes protected users (root@pam).
    """
    ps_groups = {g["groupid"] for g in list_proxmoxsession_groups(proxmox)}
    result = []
    for user in proxmox.access.users.get(full=1):
        userid = user.get("userid", "")
        if is_protected(userid):
            continue
        raw_groups = user.get("groups")
        if isinstance(raw_groups, list):
            user_groups = set(raw_groups)
        elif raw_groups:
            user_groups = set(g.strip() for g in raw_groups.split(",") if g.strip())
        else:
            user_groups = set()
        if user_groups & ps_groups:
            result.append(user)
    return result


def wizard_already_run(proxmox: proxmoxer.ProxmoxAPI) -> bool:
    """Return True if the proxmoxsession_superadmin group already exists."""
    existing = {g["groupid"] for g in proxmox.access.groups.get()}
    return group_name("superadmin") in existing


def repair_permissions(proxmox: proxmoxer.ProxmoxAPI) -> dict:
    """
    Update all ProxmoxSession roles and re-apply ACLs for every existing
    proxmoxsession_* group without touching users or creating new objects.

    Safe to run at any time — idempotent.
    Returns a results dict with fixed/skipped/failed lists.
    """
    results: dict = {"fixed": [], "skipped": [], "failed": []}

    def record(action: str, item: str, detail: str = "") -> None:
        results[action].append({"item": item, "detail": detail})
        log.info("%s: %s %s", action.upper(), item, detail)

    # 1. Update all role privilege definitions
    try:
        existing_roles = {r["roleid"] for r in proxmox.access.roles.get()}
        for roleid, privs in ROLES.items():
            privs_str = " ".join(privs.split())
            if roleid in existing_roles:
                proxmox.access.roles(roleid).put(privs=privs_str)
                record("fixed", f"Role updated: {roleid}")
            else:
                proxmox.access.roles.post(roleid=roleid, privs=privs_str)
                record("fixed", f"Role created: {roleid}")
    except Exception as e:
        record("failed", "Roles", str(e))
        return results  # can't continue without roles

    # 2. Ensure resource pool exists
    try:
        existing_pools = {p["poolid"] for p in proxmox.pools.get()}
        if POOL_NAME not in existing_pools:
            proxmox.pools.post(
                poolid=POOL_NAME,
                comment="ProxmoxSession managed VMs and templates",
            )
            record("fixed", f"Pool created: {POOL_NAME}")
        else:
            record("skipped", f"Pool exists: {POOL_NAME}")
    except Exception as e:
        record("failed", f"Pool: {POOL_NAME}", str(e))

    # 3. Re-apply ACLs for all existing proxmoxsession_* groups
    try:
        existing_groups = list_proxmoxsession_groups(proxmox)
    except Exception as e:
        record("failed", "Group listing", str(e))
        return results

    for g in existing_groups:
        gid = g["groupid"]
        short = gid[len(PREFIX):]
        try:
            if short in STANDARD_GROUPS:
                assign_group_permissions(proxmox, short)
                record("fixed", f"ACLs re-applied: {gid}")
            else:
                # Custom groups: re-apply their existing ACLs by looking up
                # what path they already have an ACL on
                acls = [
                    entry for entry in proxmox.access.acl.get()
                    if entry.get("ugid") == gid and entry.get("type") == "group"
                ]
                if acls:
                    path = acls[0].get("path", "/vms")
                    existing_role = acls[0].get("roleid", "ProxmoxSession.VDIUser")
                    role_short = existing_role.replace("ProxmoxSession.", "")
                    assign_custom_group_permissions(proxmox, short, role_short, path)
                    record("fixed", f"ACLs re-applied: {gid} on {path}")
                else:
                    record("skipped", f"Custom group {gid} — no existing ACL found, skipping")
        except Exception as e:
            record("failed", f"ACL for {gid}", str(e))

    return results


# ── Full wizard setup ─────────────────────────────────────────────────────────

def run_full_setup(
    proxmox: proxmoxer.ProxmoxAPI,
    groups_to_create: list[dict],
    vm_path: str,
    superadmin_username: str,
    superadmin_password: str,
    superadmin_realm: str = "pve",
    superadmin_email: str = "",
    superadmin_firstname: str = "",
    superadmin_lastname: str = "",
    extra_users: Optional[list[dict]] = None,
) -> dict:
    """
    Execute the full wizard setup. Returns a results dict with created/failed lists.

    groups_to_create: list of dicts with keys: short_name, comment, role (VDIUser/Admin/SuperAdmin)
    vm_path: e.g. '/vms' or '/pool/mypool' (used for custom groups only)
    extra_users: list of dicts with keys: username, password, short_group, realm, email,
                 firstname, lastname
    """
    results: dict = {"created": [], "skipped": [], "failed": []}

    def record(action: str, item: str, detail: str = "") -> None:
        results[action].append({"item": item, "detail": detail})
        if action == "failed":
            log.error("FAILED %s: %s", item, detail)
        else:
            log.info("%s: %s", action.upper(), item)

    # 1. Roles
    try:
        created_roles = create_proxmoxsession_roles(proxmox)
        for r in created_roles:
            record("created", f"Role: {r}")
        for r in ROLES:
            if r not in created_roles:
                record("skipped", f"Role: {r}", "already existed")
    except Exception as e:
        record("failed", "Roles", str(e))
        return results  # Can't proceed without roles

    # 2. Resource pool
    try:
        new_pool = create_proxmoxsession_pool(proxmox)
        record("created" if new_pool else "skipped", f"Pool: {POOL_NAME}")
    except Exception as e:
        record("failed", f"Pool: {POOL_NAME}", str(e))
        # Non-fatal — continue

    # 3. Always ensure standard groups exist first
    for short_name, info in STANDARD_GROUPS.items():
        try:
            new = create_proxmoxsession_group(proxmox, short_name, info["comment"])
            record("created" if new else "skipped", f"Group: {group_name(short_name)}")
        except Exception as e:
            record("failed", f"Group: {group_name(short_name)}", str(e))

    # 4. Custom groups
    for g in groups_to_create:
        short = g["short_name"]
        if short in STANDARD_GROUPS:
            continue  # already handled above
        try:
            new = create_proxmoxsession_group(proxmox, short, g.get("comment", ""))
            record("created" if new else "skipped", f"Group: {group_name(short)}")
        except Exception as e:
            record("failed", f"Group: {group_name(short)}", str(e))

    # 5. ACL assignments — standard groups (use pool-aware logic)
    for short_name in STANDARD_GROUPS:
        try:
            assign_group_permissions(proxmox, short_name, vm_path)
            if short_name == "superadmin":
                record("created", f"ACL: {group_name(short_name)} → view all VMs")
            elif short_name == "admin":
                record("created", f"ACL: {group_name(short_name)} → manage /pool/{POOL_NAME}")
            else:
                record("created", f"ACL: {group_name(short_name)} → deploy into /pool/{POOL_NAME}")
        except Exception as e:
            record("failed", f"ACL: {group_name(short_name)}", str(e))

    # 6. ACL assignments — custom groups (use vm_path)
    for g in groups_to_create:
        short = g["short_name"]
        if short in STANDARD_GROUPS:
            continue
        try:
            assign_custom_group_permissions(proxmox, short, g.get("role", "VDIUser"), vm_path)
            record("created", f"ACL: {group_name(short)} on {vm_path}")
        except Exception as e:
            record("failed", f"ACL: {group_name(short)}", str(e))

    # 7. SuperAdmin user
    try:
        uid = create_user(
            proxmox,
            superadmin_username,
            superadmin_password,
            "superadmin",
            realm=superadmin_realm,
            email=superadmin_email,
            firstname=superadmin_firstname,
            lastname=superadmin_lastname,
        )
        record("created", f"User: {uid} (superadmin)")
    except proxmoxer.core.ResourceException as e:
        if e.status_code == 409:
            record("skipped", f"User: {superadmin_username}@{superadmin_realm}", "already existed")
        else:
            record("failed", f"User: {superadmin_username}@{superadmin_realm}", str(e))
    except Exception as e:
        record("failed", f"User: {superadmin_username}@{superadmin_realm}", str(e))

    # 8. Extra VDI users
    for u in (extra_users or []):
        try:
            uid = create_user(
                proxmox,
                u["username"],
                u["password"],
                u.get("short_group", "vdiuser"),
                realm=u.get("realm", "pve"),
                email=u.get("email", ""),
                firstname=u.get("firstname", ""),
                lastname=u.get("lastname", ""),
            )
            record("created", f"User: {uid}")
        except proxmoxer.core.ResourceException as e:
            if e.status_code == 409:
                record("skipped", f"User: {u['username']}", "already existed")
            else:
                record("failed", f"User: {u['username']}", str(e))
        except Exception as e:
            record("failed", f"User: {u['username']}", str(e))

    return results
