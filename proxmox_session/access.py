"""
Proxmox access management — groups, users, roles, and ACLs for ProxmoxSession.

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

ROLES: dict[str, str] = {
    "ProxmoxSession.VDIUser": "VM.Console VM.PowerMgmt VM.Audit",
    "ProxmoxSession.Admin": "VM.Console VM.PowerMgmt VM.Audit VM.Allocate VM.Config.Options",
    "ProxmoxSession.SuperAdmin": "User.Modify Group.Allocate Permissions.Modify",
}

# Standard groups created by the wizard
STANDARD_GROUPS: dict[str, dict] = {
    "superadmin": {
        "comment": "ProxmoxSession superadmin — manages PS groups and users",
        "role": "ProxmoxSession.SuperAdmin",
    },
    "admin": {
        "comment": "ProxmoxSession admin — full VM management",
        "role": "ProxmoxSession.Admin",
    },
    "vdiuser": {
        "comment": "ProxmoxSession VDI user — SPICE connect and power only",
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
    Create all three ProxmoxSession.* roles. Idempotent — skips existing roles.
    Returns list of role IDs that were created.
    """
    created = []
    existing = {r["roleid"] for r in proxmox.access.roles.get()}

    for roleid, privs in ROLES.items():
        if roleid in existing:
            log.debug("Role %s already exists, skipping", roleid)
            continue
        proxmox.access.roles.post(roleid=roleid, privs=privs)
        log.info("Created role: %s", roleid)
        created.append(roleid)

    return created


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
    Assign the appropriate ProxmoxSession role to a group on the given VM path.
    Also grants the superadmin group management access to this group.
    """
    groupid = group_name(short_name)
    group_info = STANDARD_GROUPS.get(short_name)
    assigned_role = group_info["role"] if group_info else "ProxmoxSession.VDIUser"

    # Grant VM access
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
        user_groups = set(user.get("groups", "").split(",")) if user.get("groups") else set()
        if user_groups & ps_groups:
            result.append(user)
    return result


def wizard_already_run(proxmox: proxmoxer.ProxmoxAPI) -> bool:
    """Return True if the proxmoxsession_superadmin group already exists."""
    existing = {g["groupid"] for g in proxmox.access.groups.get()}
    return group_name("superadmin") in existing


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
    vm_path: e.g. '/vms' or '/pool/mypool'
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

    # 2. Always ensure superadmin group exists first
    for short_name, info in STANDARD_GROUPS.items():
        try:
            new = create_proxmoxsession_group(proxmox, short_name, info["comment"])
            record("created" if new else "skipped", f"Group: {group_name(short_name)}")
        except Exception as e:
            record("failed", f"Group: {group_name(short_name)}", str(e))

    # 3. Custom groups
    for g in groups_to_create:
        short = g["short_name"]
        if short in STANDARD_GROUPS:
            continue  # already handled above
        try:
            new = create_proxmoxsession_group(proxmox, short, g.get("comment", ""))
            record("created" if new else "skipped", f"Group: {group_name(short)}")
        except Exception as e:
            record("failed", f"Group: {group_name(short)}", str(e))

    # 4. ACL assignments — standard groups
    for short_name in STANDARD_GROUPS:
        try:
            assign_group_permissions(proxmox, short_name, vm_path)
            record("created", f"ACL: {group_name(short_name)} on {vm_path}")
        except Exception as e:
            record("failed", f"ACL: {group_name(short_name)}", str(e))

    # 5. ACL assignments — custom groups
    for g in groups_to_create:
        short = g["short_name"]
        if short in STANDARD_GROUPS:
            continue
        try:
            assign_custom_group_permissions(proxmox, short, g.get("role", "VDIUser"), vm_path)
            record("created", f"ACL: {group_name(short)} on {vm_path}")
        except Exception as e:
            record("failed", f"ACL: {group_name(short)}", str(e))

    # 6. SuperAdmin user
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

    # 7. Extra VDI users
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
