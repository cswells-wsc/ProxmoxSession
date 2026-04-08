"""
Tests for proxmox_session/access.py — group/role/user helpers.

These tests use unittest.mock to simulate the Proxmox API. No live Proxmox
server is needed.

Run with:
    python tests/test_access.py
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxmox_session import access
from proxmox_session.access import (
    POOL_NAME,
    PREFIX,
    ROLES,
    STANDARD_GROUPS,
    assign_custom_group_permissions,
    assign_group_permissions,
    assign_vm_to_user,
    create_proxmoxsession_group,
    create_proxmoxsession_pool,
    create_proxmoxsession_roles,
    create_user,
    group_name,
    is_protected,
    list_proxmoxsession_groups,
    list_proxmoxsession_users,
    list_vmids_for_user,
    role_name,
    run_full_setup,
    unassign_vm_from_user,
    wizard_already_run,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_proxmox():
    """Return a MagicMock that mimics a proxmoxer.ProxmoxAPI."""
    px = MagicMock()
    # Default: no existing roles, groups, users
    px.access.roles.get.return_value = []
    px.access.groups.get.return_value = []
    px.access.users.get.return_value = []
    return px


# ── is_protected ──────────────────────────────────────────────────────────────

class TestRoleDefinitions(unittest.TestCase):
    def test_superadmin_has_user_modify(self):
        """User.Modify with propagate=1 on /access covers listing and managing users."""
        self.assertIn("User.Modify", ROLES["ProxmoxSession.SuperAdmin"])

    def test_superadmin_has_no_invalid_privs(self):
        """User.Audit and Group.Audit are not real Proxmox privileges — must not be present."""
        privs = ROLES["ProxmoxSession.SuperAdmin"]
        self.assertNotIn("User.Audit", privs)
        self.assertNotIn("Group.Audit", privs)

    def test_superadmin_has_pool_audit(self):
        """Pool.Audit is required to read pool members in VM Assignments tab."""
        self.assertIn("Pool.Audit", ROLES["ProxmoxSession.SuperAdmin"])

    def test_superadmin_has_pool_allocate(self):
        """Pool.Allocate is required to add/remove VMs from the resource pool."""
        self.assertIn("Pool.Allocate", ROLES["ProxmoxSession.SuperAdmin"])

    def test_superadmin_has_sys_audit(self):
        """Sys.Audit is required to read cluster/node resource status."""
        self.assertIn("Sys.Audit", ROLES["ProxmoxSession.SuperAdmin"])

    def test_superadmin_has_vm_audit(self):
        self.assertIn("VM.Audit", ROLES["ProxmoxSession.SuperAdmin"])


class TestIsProtected(unittest.TestCase):
    def test_root_is_protected(self):
        self.assertTrue(is_protected("root@pam"))

    def test_normal_user_not_protected(self):
        self.assertFalse(is_protected("alice@pve"))

    def test_admin_user_not_protected(self):
        self.assertFalse(is_protected("admin@pve"))


# ── group_name / role_name ────────────────────────────────────────────────────

class TestNameHelpers(unittest.TestCase):
    def test_group_name_adds_prefix(self):
        self.assertEqual(group_name("vdiuser"), "proxmoxsession_vdiuser")

    def test_group_name_idempotent(self):
        self.assertEqual(group_name("proxmoxsession_vdiuser"), "proxmoxsession_vdiuser")

    def test_role_name_adds_prefix(self):
        self.assertEqual(role_name("VDIUser"), "ProxmoxSession.VDIUser")

    def test_role_name_idempotent(self):
        self.assertEqual(role_name("ProxmoxSession.VDIUser"), "ProxmoxSession.VDIUser")


# ── create_proxmoxsession_roles ───────────────────────────────────────────────

class TestCreateRoles(unittest.TestCase):
    def test_creates_all_roles_when_none_exist(self):
        px = _make_proxmox()
        px.access.roles.get.return_value = []
        created = create_proxmoxsession_roles(px)
        self.assertEqual(set(created), set(ROLES.keys()))
        self.assertEqual(px.access.roles.post.call_count, len(ROLES))

    def test_updates_existing_roles_in_place(self):
        """Re-running the wizard updates role privileges instead of skipping."""
        px = _make_proxmox()
        existing_roleid = list(ROLES.keys())[0]
        px.access.roles.get.return_value = [{"roleid": existing_roleid}]
        created = create_proxmoxsession_roles(px)
        # The existing role should NOT appear in created
        self.assertNotIn(existing_roleid, created)
        # But it should have been updated via PUT
        px.access.roles(existing_roleid).put.assert_called_once()
        # The remaining roles were created via POST
        self.assertEqual(px.access.roles.post.call_count, len(ROLES) - 1)

    def test_updates_all_when_all_exist(self):
        """All existing roles are updated — none are silently skipped."""
        px = _make_proxmox()
        px.access.roles.get.return_value = [{"roleid": r} for r in ROLES]
        created = create_proxmoxsession_roles(px)
        self.assertEqual(created, [])
        px.access.roles.post.assert_not_called()
        # Each existing role should have been updated
        for roleid in ROLES:
            px.access.roles(roleid).put.assert_called()


# ── create_proxmoxsession_group ───────────────────────────────────────────────

class TestCreateGroup(unittest.TestCase):
    def test_creates_new_group(self):
        px = _make_proxmox()
        result = create_proxmoxsession_group(px, "vdiuser", "VDI Users")
        self.assertTrue(result)
        px.access.groups.post.assert_called_once_with(
            groupid="proxmoxsession_vdiuser", comment="VDI Users"
        )

    def test_returns_false_on_409(self):
        import proxmoxer
        px = _make_proxmox()
        exc = proxmoxer.core.ResourceException(409, "already exists", None)
        px.access.groups.post.side_effect = exc
        result = create_proxmoxsession_group(px, "vdiuser")
        self.assertFalse(result)

    def test_raises_on_other_errors(self):
        import proxmoxer
        px = _make_proxmox()
        exc = proxmoxer.core.ResourceException(500, "server error", None)
        px.access.groups.post.side_effect = exc
        with self.assertRaises(proxmoxer.core.ResourceException):
            create_proxmoxsession_group(px, "vdiuser")


# ── assign_group_permissions ──────────────────────────────────────────────────

class TestAssignGroupPermissions(unittest.TestCase):
    def test_superadmin_gets_vms_path(self):
        px = _make_proxmox()
        assign_group_permissions(px, "superadmin", "/vms")
        paths = [c.kwargs["path"] for c in px.access.acl.put.call_args_list]
        self.assertIn("/vms", paths)

    def test_superadmin_gets_pool_acl(self):
        """Superadmin needs Pool.Audit on the pool path to see it in pools.get()."""
        px = _make_proxmox()
        assign_group_permissions(px, "superadmin", "/vms")
        paths = [c.kwargs["path"] for c in px.access.acl.put.call_args_list]
        self.assertIn(f"/pool/{POOL_NAME}", paths,
                      "Superadmin must have ACL on pool path to see it")

    def test_admin_gets_pool_path(self):
        px = _make_proxmox()
        assign_group_permissions(px, "admin", "/vms")
        first = px.access.acl.put.call_args_list[0]
        self.assertIn(f"/pool/{POOL_NAME}", first.kwargs["path"])
        self.assertEqual(first.kwargs["roles"], "ProxmoxSession.Admin")

    def test_vdiuser_gets_deploy_role_on_pool(self):
        px = _make_proxmox()
        assign_group_permissions(px, "vdiuser", "/vms")
        first = px.access.acl.put.call_args_list[0]
        self.assertIn(f"/pool/{POOL_NAME}", first.kwargs["path"])
        self.assertEqual(first.kwargs["roles"], "ProxmoxSession.VDIDeploy")

    def test_superadmin_gets_access_path_with_propagate(self):
        """Superadmin /access ACL must propagate so /access/users and /access/groups are covered."""
        px = _make_proxmox()
        assign_group_permissions(px, "superadmin", "/vms")
        access_calls = [
            c for c in px.access.acl.put.call_args_list
            if c.kwargs.get("path") == "/access"
        ]
        self.assertTrue(access_calls, "Expected /access ACL for superadmin")
        self.assertEqual(access_calls[0].kwargs.get("propagate"), 1,
                         "/access ACL must have propagate=1 to cover /access/users and /access/groups")

    def test_superadmin_management_acl_always_granted(self):
        """Every group gets a superadmin management ACL on /access/groups/<gid>."""
        px = _make_proxmox()
        for short_name in STANDARD_GROUPS:
            px.reset_mock()
            assign_group_permissions(px, short_name, "/vms")
            paths = [c.kwargs["path"] for c in px.access.acl.put.call_args_list]
            gid = group_name(short_name)
            self.assertTrue(
                any(f"/access/groups/{gid}" in p for p in paths),
                f"Expected superadmin group management ACL for {gid}"
            )


# ── create_user ───────────────────────────────────────────────────────────────

class TestCreateUser(unittest.TestCase):
    def test_creates_user(self):
        px = _make_proxmox()
        uid = create_user(px, "alice", "password123", "vdiuser")
        self.assertEqual(uid, "alice@pve")
        px.access.users.post.assert_called_once()
        call_kwargs = px.access.users.post.call_args.kwargs
        self.assertEqual(call_kwargs["userid"], "alice@pve")
        self.assertEqual(call_kwargs["groups"], "proxmoxsession_vdiuser")

    def test_raises_for_protected_user(self):
        px = _make_proxmox()
        with self.assertRaises(ValueError):
            create_user(px, "root", "password", "superadmin", realm="pam")

    def test_custom_realm(self):
        px = _make_proxmox()
        uid = create_user(px, "bob", "password123", "admin", realm="ldap")
        self.assertEqual(uid, "bob@ldap")


# ── list_proxmoxsession_groups ────────────────────────────────────────────────

class TestListGroups(unittest.TestCase):
    def test_filters_by_prefix(self):
        px = _make_proxmox()
        px.access.groups.get.return_value = [
            {"groupid": "proxmoxsession_vdiuser"},
            {"groupid": "admins"},
            {"groupid": "proxmoxsession_admin"},
        ]
        result = list_proxmoxsession_groups(px)
        self.assertEqual(len(result), 2)
        gids = {g["groupid"] for g in result}
        self.assertIn("proxmoxsession_vdiuser", gids)
        self.assertIn("proxmoxsession_admin", gids)
        self.assertNotIn("admins", gids)


# ── list_proxmoxsession_users ─────────────────────────────────────────────────

class TestListUsers(unittest.TestCase):
    def test_returns_users_in_ps_groups(self):
        px = _make_proxmox()
        px.access.groups.get.return_value = [
            {"groupid": "proxmoxsession_vdiuser"},
        ]
        px.access.users.get.return_value = [
            {"userid": "alice@pve", "groups": "proxmoxsession_vdiuser"},
            {"userid": "bob@pve", "groups": "other_group"},
            {"userid": "root@pam", "groups": ""},
        ]
        result = list_proxmoxsession_users(px)
        userids = {u["userid"] for u in result}
        self.assertIn("alice@pve", userids)
        self.assertNotIn("bob@pve", userids)
        self.assertNotIn("root@pam", userids)

    def test_excludes_root(self):
        px = _make_proxmox()
        px.access.groups.get.return_value = [{"groupid": "proxmoxsession_superadmin"}]
        px.access.users.get.return_value = [
            {"userid": "root@pam", "groups": "proxmoxsession_superadmin"},
            {"userid": "admin@pve", "groups": "proxmoxsession_superadmin"},
        ]
        result = list_proxmoxsession_users(px)
        userids = {u["userid"] for u in result}
        self.assertNotIn("root@pam", userids)
        self.assertIn("admin@pve", userids)


# ── create_proxmoxsession_pool ────────────────────────────────────────────────

class TestCreatePool(unittest.TestCase):
    def test_creates_pool_when_not_existing(self):
        px = _make_proxmox()
        px.pools.get.return_value = []
        result = create_proxmoxsession_pool(px)
        self.assertTrue(result)
        px.pools.post.assert_called_once_with(
            poolid=POOL_NAME,
            comment="ProxmoxSession managed VMs and templates",
        )

    def test_skips_existing_pool(self):
        px = _make_proxmox()
        px.pools.get.return_value = [{"poolid": POOL_NAME}]
        result = create_proxmoxsession_pool(px)
        self.assertFalse(result)
        px.pools.post.assert_not_called()


# ── assign_vm_to_user / unassign_vm_from_user ─────────────────────────────────

class TestVMAssignment(unittest.TestCase):
    def test_assign_vm_sets_acl(self):
        px = _make_proxmox()
        assign_vm_to_user(px, "alice@pve", 100)
        px.access.acl.put.assert_called_once_with(
            path="/vms/100",
            users="alice@pve",
            roles="ProxmoxSession.VDIUser",
            propagate=1,
        )

    def test_assign_vm_raises_for_protected(self):
        px = _make_proxmox()
        with self.assertRaises(ValueError):
            assign_vm_to_user(px, "root@pam", 100)

    def test_unassign_vm_deletes_acl(self):
        px = _make_proxmox()
        unassign_vm_from_user(px, "alice@pve", 100)
        px.access.acl.put.assert_called_once()
        call_kwargs = px.access.acl.put.call_args.kwargs
        self.assertEqual(call_kwargs["path"], "/vms/100")
        self.assertEqual(call_kwargs.get("delete"), 1)

    def test_unassign_protected_is_noop(self):
        px = _make_proxmox()
        unassign_vm_from_user(px, "root@pam", 100)
        px.access.acl.put.assert_not_called()


# ── list_vmids_for_user ───────────────────────────────────────────────────────

class TestListVmidsForUser(unittest.TestCase):
    def test_returns_assigned_vmids(self):
        px = _make_proxmox()
        px.access.acl.get.return_value = [
            {"ugid": "alice@pve", "type": "user", "path": "/vms/100", "roleid": "ProxmoxSession.VDIUser"},
            {"ugid": "alice@pve", "type": "user", "path": "/vms/200", "roleid": "ProxmoxSession.VDIUser"},
            {"ugid": "bob@pve",   "type": "user", "path": "/vms/300", "roleid": "ProxmoxSession.VDIUser"},
        ]
        result = list_vmids_for_user(px, "alice@pve")
        self.assertEqual(set(result), {100, 200})

    def test_ignores_non_vm_paths(self):
        px = _make_proxmox()
        px.access.acl.get.return_value = [
            {"ugid": "alice@pve", "type": "user", "path": "/access/groups/proxmoxsession_vdiuser"},
            {"ugid": "alice@pve", "type": "user", "path": "/vms/101"},
        ]
        result = list_vmids_for_user(px, "alice@pve")
        self.assertEqual(result, [101])


# ── wizard_already_run ────────────────────────────────────────────────────────

class TestWizardAlreadyRun(unittest.TestCase):
    def test_true_when_superadmin_group_exists(self):
        px = _make_proxmox()
        px.access.groups.get.return_value = [
            {"groupid": "proxmoxsession_superadmin"},
        ]
        self.assertTrue(wizard_already_run(px))

    def test_false_when_no_ps_groups(self):
        px = _make_proxmox()
        px.access.groups.get.return_value = []
        self.assertFalse(wizard_already_run(px))


# ── run_full_setup ────────────────────────────────────────────────────────────

class TestRunFullSetup(unittest.TestCase):
    def _make_px(self):
        px = _make_proxmox()
        # Roles don't exist yet
        px.access.roles.get.return_value = []
        # Groups don't exist yet
        px.access.groups.get.return_value = []
        # Pool doesn't exist yet
        px.pools.get.return_value = []
        return px

    def test_creates_roles_groups_and_superadmin_user(self):
        px = self._make_px()
        results = run_full_setup(
            px,
            groups_to_create=[],
            vm_path="/vms",
            superadmin_username="psadmin",
            superadmin_password="Passw0rd!",
        )
        created_items = [r["item"] for r in results["created"]]
        # All roles should be in created
        for roleid in ROLES:
            self.assertTrue(
                any(roleid in item for item in created_items),
                f"Expected role {roleid} in created items"
            )
        # Resource pool should be created
        self.assertTrue(
            any(POOL_NAME in item for item in created_items),
            f"Expected pool {POOL_NAME} in created items"
        )
        # Standard groups should be created
        for short_name in STANDARD_GROUPS:
            full_gid = group_name(short_name)
            self.assertTrue(
                any(full_gid in item for item in created_items),
                f"Expected group {full_gid} in created items"
            )
        # Superadmin user
        self.assertTrue(any("psadmin" in item for item in created_items))
        # No failures
        self.assertEqual(results["failed"], [])

    def test_returns_failed_on_role_error(self):
        px = self._make_px()
        px.access.roles.get.side_effect = Exception("API error")
        results = run_full_setup(
            px,
            groups_to_create=[],
            vm_path="/vms",
            superadmin_username="psadmin",
            superadmin_password="Passw0rd!",
        )
        self.assertTrue(len(results["failed"]) > 0)

    def test_custom_groups_included(self):
        px = self._make_px()
        results = run_full_setup(
            px,
            groups_to_create=[{"short_name": "contractors", "comment": "Contractors", "role": "VDIUser"}],
            vm_path="/vms",
            superadmin_username="psadmin",
            superadmin_password="Passw0rd!",
        )
        created_items = [r["item"] for r in results["created"]]
        self.assertTrue(any("contractors" in item for item in created_items))


# ─────────────────────────────────────────────────────────────────────────────

def main():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
