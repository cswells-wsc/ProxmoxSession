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
    PREFIX,
    ROLES,
    STANDARD_GROUPS,
    assign_custom_group_permissions,
    assign_group_permissions,
    create_proxmoxsession_group,
    create_proxmoxsession_roles,
    create_user,
    group_name,
    is_protected,
    list_proxmoxsession_groups,
    list_proxmoxsession_users,
    role_name,
    run_full_setup,
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

    def test_skips_existing_roles(self):
        px = _make_proxmox()
        existing_roleid = list(ROLES.keys())[0]
        px.access.roles.get.return_value = [{"roleid": existing_roleid}]
        created = create_proxmoxsession_roles(px)
        self.assertNotIn(existing_roleid, created)
        self.assertEqual(px.access.roles.post.call_count, len(ROLES) - 1)

    def test_skips_all_when_all_exist(self):
        px = _make_proxmox()
        px.access.roles.get.return_value = [{"roleid": r} for r in ROLES]
        created = create_proxmoxsession_roles(px)
        self.assertEqual(created, [])
        px.access.roles.post.assert_not_called()


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
    def test_grants_vm_acl_and_superadmin_acl(self):
        px = _make_proxmox()
        assign_group_permissions(px, "vdiuser", "/vms")
        calls = px.access.acl.put.call_args_list
        # Should have called put twice: VM access + superadmin group management
        self.assertEqual(len(calls), 2)

        # First call: VM access for the group
        first = calls[0]
        self.assertEqual(first.kwargs["path"], "/vms")
        self.assertIn("proxmoxsession_vdiuser", first.kwargs["groups"])

        # Second call: superadmin can manage this group
        second = calls[1]
        self.assertIn("/access/groups/proxmoxsession_vdiuser", second.kwargs["path"])
        self.assertIn("proxmoxsession_superadmin", second.kwargs["groups"])

    def test_standard_groups_get_correct_roles(self):
        px = _make_proxmox()
        for short_name, info in STANDARD_GROUPS.items():
            px.reset_mock()
            assign_group_permissions(px, short_name, "/vms")
            first_call = px.access.acl.put.call_args_list[0]
            self.assertEqual(first_call.kwargs["roles"], info["role"])


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
        # All three roles should be in created
        created_items = [r["item"] for r in results["created"]]
        for roleid in ROLES:
            self.assertTrue(
                any(roleid in item for item in created_items),
                f"Expected role {roleid} in created items"
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
