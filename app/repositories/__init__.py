"""Compatibility facade for MEATTRACK standalone inventory domain repositories."""

from app.portal_config import default_section_for, portal_nav, portal_nav_for, roles, team_leader_nav_by_role, team_leader_role_labels
from . import _shared, accounts, inventory, notifications, reporting, superuser
from ._shared import *
from .accounts import *
from .inventory import *
from .notifications import *
from .reporting import *
from .superuser import *

__all__ = (
    _shared.__all__
    + accounts.__all__
    + inventory.__all__
    + notifications.__all__
    + reporting.__all__
    + superuser.__all__
    + ['default_section_for', 'portal_nav', 'portal_nav_for', 'roles', 'team_leader_nav_by_role', 'team_leader_role_labels']
)
