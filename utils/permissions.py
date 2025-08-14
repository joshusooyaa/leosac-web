"""
Permission helpers for UI gating based on user rank.

This is a frontend safety net. The backend still enforces permissions.
"""

from typing import Set

# Rank order from lowest to highest privilege
ROLE_ORDER = ['user', 'viewer', 'manager', 'supervisor', 'administrator']


def _role_index(rank: str) -> int:
  try:
    return ROLE_ORDER.index((rank or '').lower())
  except ValueError:
    return 0


def get_permissions_for_rank(rank: str) -> Set[str]:
  r = (rank or 'user').lower()
  idx = _role_index(r)

  # Base permissions mapping by rank tier
  # Note: Keep conservative. Backend is the source of truth.
  perms: Set[str] = set()

  # Everyone logged-in: only profile and alarms in top bar
  perms.update({
    'nav.profile', 'nav.alarms'
  })

  if idx >= _role_index('viewer'):
    # Viewer can see everything (all index/detail pages), but cannot mutate
    perms.update({
      'nav.dashboard', 'nav.users', 'nav.groups', 'nav.credentials', 'nav.schedules',
      'nav.zones', 'nav.doors'
    })
    perms.update({
      'users.view', 'groups.view', 'credentials.view', 'schedules.view',
      'zones.view', 'doors.view'
    })

  if idx >= _role_index('manager'):
    # Limited management (non-destructive creates/updates for operational data)
    perms.update({
      'credentials.create', 'credentials.update',
      'schedules.create', 'schedules.update',
      'groups.create', 'groups.update',
      'doors.create', 'doors.update',
      # User-related privileges above viewer
      'users.change_password',
      'users.view.others'
    })

  if idx >= _role_index('supervisor'):
    # Elevated management across entities
    perms.update({
      'users.update', 'groups.delete', 'credentials.delete',
      'schedules.delete', 'zones.create', 'zones.update', 'zones.delete',
      'doors.delete'
    })

  if idx >= _role_index('administrator'):
    # Full access, including user CRUD
    perms.update({
      'users.create', 'users.delete', 'admin.all', 'nav.audit', 'audit.view'
    })

  return perms


def has_permission(rank: str, permission: str) -> bool:
  return permission in get_permissions_for_rank(rank)


