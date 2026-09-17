"""
Import every model module here so SQLAlchemy's mapper configuration sees the
whole schema in one place, regardless of import order elsewhere. Alembic's
env.py imports this module before autogenerating/comparing migrations —
if you add a new model file, add it here too or it silently won't be picked up.
"""

from app.models.organisation import Organisation  # noqa: F401
from app.models.venue import Venue  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.magic_link import MagicLink  # noqa: F401
from app.models.membership import Membership, MembershipRole  # noqa: F401
from app.models.staff import Staff, StaffSkill  # noqa: F401
from app.models.station import Station, StationCoverageRule  # noqa: F401
from app.models.service_day import ServiceDay, ServiceDayStatus  # noqa: F401
from app.models.supplier import Supplier  # noqa: F401
from app.models.ingredient import Ingredient  # noqa: F401
from app.models.menu import MenuItem, MenuAvailabilityEvent, MenuAvailabilityStatus  # noqa: F401
from app.models.recipe import Recipe, RecipeVersion, RecipeIngredient, MenuItemRecipe  # noqa: F401,E501
from app.models.equipment import (  # noqa: F401
    EquipmentItem,
    EquipmentStatus,
    EquipmentIssue,
    EquipmentIssuePriority,
    EquipmentIssueStatus,
)
from app.models.roster import Shift, ShiftStatus, StaffResponse, StaffResponseStatus, StaffLink  # noqa: F401,E501
from app.models.attendance import AttendanceEvent, AttendanceStatus, AttendanceSource  # noqa: F401
from app.models.prep import PrepTemplate, PrepTemplateItem, PrepTask, PrepTaskStatus  # noqa: F401
from app.models.purchase_order import (  # noqa: F401
    DeliveryIssue,
    DeliveryIssueType,
    DeliveryStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.models.capture import (  # noqa: F401
    Capture,
    CaptureStatus,
    CaptureType,
    MatchedEntityType,
)
from app.models.audit import AuditEvent  # noqa: F401

__all__ = [
    "Organisation",
    "Venue",
    "User",
    "MagicLink",
    "Membership",
    "MembershipRole",
    "Staff",
    "StaffSkill",
    "Station",
    "StationCoverageRule",
    "ServiceDay",
    "ServiceDayStatus",
    "Supplier",
    "Ingredient",
    "MenuItem",
    "Recipe",
    "RecipeVersion",
    "RecipeIngredient",
    "MenuItemRecipe",
    "MenuAvailabilityEvent",
    "MenuAvailabilityStatus",
    "EquipmentItem",
    "EquipmentStatus",
    "EquipmentIssue",
    "EquipmentIssuePriority",
    "EquipmentIssueStatus",
    "Shift",
    "ShiftStatus",
    "StaffResponse",
    "StaffResponseStatus",
    "StaffLink",
    "AttendanceEvent",
    "AttendanceStatus",
    "AttendanceSource",
    "PrepTemplate",
    "PrepTemplateItem",
    "PrepTask",
    "PrepTaskStatus",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseOrderStatus",
    "DeliveryStatus",
    "DeliveryIssue",
    "DeliveryIssueType",
    "Capture",
    "CaptureStatus",
    "CaptureType",
    "MatchedEntityType",
    "AuditEvent",
]
