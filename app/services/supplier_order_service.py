"""
Epic 5 — Supplier Orders.

Core rule (locked AC): a draft PurchaseOrder's identity is (venue, supplier,
required_delivery_date, order_cycle, status=draft) — NOT supplier alone.
add_or_merge_line() is the single entry point both the chef-facing API and
Quick Capture (Epic 6, which "calls Epic 5's existing add/merge line to
draft PurchaseOrder function directly") use to build up a draft: it finds
or creates the draft matching that key, then either merges into an existing
line for the same ingredient (summing quantities) or creates a new one.

Send lifecycle (draft -> sending -> sent | send_failed) commits the
"sending" transition BEFORE calling the (stubbed, pluggable) email
provider, so a crash or timeout mid-send leaves a durable "sending" record
rather than silently reverting to "draft" — the caller can tell the two
apart. idempotency_key is generated once and reused on every retry.

EMAIL_PROVIDER is a module-level hook rather than a hardcoded call so
Epic 10 (Operational Email Notifications, which introduces the real
pluggable EmailSender interface) can swap it without changing this
module's public functions, and so tests can substitute a fake without
monkeypatching internals.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from app.models.ingredient import Ingredient
from app.models.purchase_order import (
    DeliveryIssue,
    DeliveryIssueType,
    DeliveryStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class MissingOrderIdentity(Exception):
    """A draft's identity requires at least one of required_delivery_date /
    order_cycle — supplier alone is not enough (locked AC): otherwise a
    next-Tuesday order could silently merge into an unrelated Friday order
    for the same supplier."""


class UnknownSupplier(Exception):
    """supplier_id must reference a Supplier at this venue."""


class UnknownIngredient(Exception):
    """ingredient_id must reference an Ingredient at this venue."""


class CannotModifyNonDraftOrder(Exception):
    """Lines (and their quantities) can only be added/changed while the
    order is still a draft — once it starts sending, its content is what
    was actually sent."""


class CannotSendOrder(Exception):
    """Raised when send_purchase_order is called on an order that isn't in
    a sendable state (draft or send_failed) or that has no lines."""


class PartialDeliveryRequiresLineNote(Exception):
    """AC: "partial requires a line-level note" — at least one line must
    carry a note explaining what was short/wrong."""


class ProviderSendError(Exception):
    """Raised by the EMAIL_PROVIDER hook when the provider rejects or fails
    a send attempt. Caught by send_purchase_order and turned into a
    send_failed transition with last_error set to str(exc)."""


@dataclass
class ProviderSendResult:
    message_id: str
    recipient: str


def _default_email_provider(*, supplier: Supplier, purchase_order: PurchaseOrder) -> ProviderSendResult:
    """
    Stub provider for v1. Epic 10 introduces the real pluggable EmailSender
    interface (console/log sender by default, swappable for a real
    provider) — until then, this always "succeeds" as long as the supplier
    has a contact_email on file, so the full draft -> sending -> sent
    lifecycle, audit trail, and idempotency-key plumbing can be built,
    tested, and used by Quick Capture (Epic 6) now. Epic 10 replaces this
    function's body (and can raise ProviderSendError for real failures)
    without changing send_purchase_order's contract.
    """
    if not supplier.contact_email:
        raise ProviderSendError(f"Supplier {supplier.id} has no contact_email on file")
    return ProviderSendResult(
        message_id=f"stub-{purchase_order.idempotency_key}",
        recipient=supplier.contact_email,
    )


EMAIL_PROVIDER: Callable[..., ProviderSendResult] = _default_email_provider


def _validated_supplier(session: Session, *, venue: Venue, supplier_id: uuid.UUID) -> Supplier:
    supplier = session.query(Supplier).filter_by(id=supplier_id, venue_id=venue.id).one_or_none()
    if supplier is None:
        raise UnknownSupplier(f"Supplier {supplier_id} does not exist at this venue")
    return supplier


def _validated_ingredient(session: Session, *, venue: Venue, ingredient_id: uuid.UUID) -> Ingredient:
    ingredient = session.query(Ingredient).filter_by(id=ingredient_id, venue_id=venue.id).one_or_none()
    if ingredient is None:
        raise UnknownIngredient(f"Ingredient {ingredient_id} does not exist at this venue")
    return ingredient


def get_or_create_draft_purchase_order(
    session: Session,
    *,
    venue: Venue,
    supplier: Supplier,
    required_delivery_date: date | None = None,
    order_cycle: str | None = None,
) -> PurchaseOrder:
    """Idempotent find-or-create keyed on the full open-draft identity.
    Does not commit — same "flush now, let the caller's audited_transaction
    commit everything together" pattern as get_or_create_service_day."""
    if required_delivery_date is None and order_cycle is None:
        raise MissingOrderIdentity(
            "Provide required_delivery_date or order_cycle to identify this draft"
        )

    existing = (
        session.query(PurchaseOrder)
        .filter_by(
            venue_id=venue.id,
            supplier_id=supplier.id,
            required_delivery_date=required_delivery_date,
            order_cycle=order_cycle,
            status=PurchaseOrderStatus.draft,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    order = PurchaseOrder(
        venue_id=venue.id,
        supplier_id=supplier.id,
        required_delivery_date=required_delivery_date,
        order_cycle=order_cycle,
        status=PurchaseOrderStatus.draft,
    )
    session.add(order)
    session.flush()
    return order


@dataclass
class AddOrMergeLineResult:
    purchase_order: PurchaseOrder
    line: PurchaseOrderLine
    merged: bool
    previous_quantity: Decimal | None  # None when a new line was created


def add_or_merge_line(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    supplier_id: uuid.UUID,
    ingredient_id: uuid.UUID,
    quantity: Decimal,
    unit: str | None = None,
    required_delivery_date: date | None = None,
    order_cycle: str | None = None,
) -> AddOrMergeLineResult:
    """Finds/creates the draft matching (venue, supplier, delivery date or
    cycle, status=draft), then either merges `quantity` into an existing
    line for the same ingredient (summing) or creates a new line. unit
    defaults from Ingredient.ordering_unit when not given. The caller
    (chef, or Quick Capture on their behalf) sees previous_quantity/new
    quantity in the result and audit trail to confirm or correct the
    merge afterwards via update_line_quantity."""
    supplier = _validated_supplier(session, venue=venue, supplier_id=supplier_id)
    ingredient = _validated_ingredient(session, venue=venue, ingredient_id=ingredient_id)
    resolved_unit = unit or ingredient.ordering_unit

    order = get_or_create_draft_purchase_order(
        session, venue=venue, supplier=supplier,
        required_delivery_date=required_delivery_date, order_cycle=order_cycle,
    )

    existing_line = (
        session.query(PurchaseOrderLine)
        .filter_by(purchase_order_id=order.id, ingredient_id=ingredient.id)
        .one_or_none()
    )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        if existing_line is not None:
            previous_quantity = existing_line.quantity
            merged_quantity = existing_line.quantity + quantity
            existing_line.quantity = merged_quantity
            session.add(existing_line)
            session.flush()
            audit.record(
                action="purchase_order_line.merged", entity_type="purchase_order_line",
                entity_id=existing_line.id,
                before={"quantity": str(previous_quantity)},
                after={"quantity": str(merged_quantity), "added": str(quantity)},
            )
            return AddOrMergeLineResult(
                purchase_order=order, line=existing_line, merged=True, previous_quantity=previous_quantity,
            )

        line = PurchaseOrderLine(
            purchase_order_id=order.id, ingredient_id=ingredient.id,
            quantity=quantity, unit=resolved_unit,
        )
        session.add(line)
        session.flush()
        audit.record(
            action="purchase_order_line.created", entity_type="purchase_order_line", entity_id=line.id,
            after={
                "purchase_order_id": str(order.id), "ingredient_id": str(ingredient.id),
                "quantity": str(quantity), "unit": resolved_unit,
            },
        )
        return AddOrMergeLineResult(purchase_order=order, line=line, merged=False, previous_quantity=None)


def update_line_quantity(
    session: Session, *, venue: Venue, actor: User, line: PurchaseOrderLine, quantity: Decimal
) -> PurchaseOrderLine:
    """Explicit post-merge correction — e.g. the chef confirms a different
    total than the raw sum add_or_merge_line produced. Only valid while the
    parent order is still a draft."""
    order = line.purchase_order
    if order.status != PurchaseOrderStatus.draft:
        raise CannotModifyNonDraftOrder(
            f"Cannot change a line on a purchase order in status {order.status.value}"
        )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        before_quantity = line.quantity
        line.quantity = quantity
        session.add(line)
        session.flush()
        audit.record(
            action="purchase_order_line.quantity_corrected", entity_type="purchase_order_line",
            entity_id=line.id,
            before={"quantity": str(before_quantity)}, after={"quantity": str(quantity)},
        )
    return line


def send_purchase_order(
    session: Session, *, venue: Venue, actor: User, purchase_order: PurchaseOrder
) -> PurchaseOrder:
    """draft | send_failed -> sending -> sent | send_failed.

    The "sending" transition is committed on its own, BEFORE the provider
    is called, so a process crash or hang during the provider call leaves
    a durable "sending" record rather than reverting to "draft" — the
    order never silently loses the fact that a send was attempted.
    idempotency_key is generated once (on the first attempt) and reused on
    every retry, including a retry from send_failed, so the provider can
    dedupe a request it actually received despite our client seeing a
    failure."""
    if purchase_order.status not in (PurchaseOrderStatus.draft, PurchaseOrderStatus.send_failed):
        raise CannotSendOrder(
            f"Cannot send a purchase order in status {purchase_order.status.value}"
        )
    if not purchase_order.lines:
        raise CannotSendOrder("Cannot send a purchase order with no lines")

    supplier = session.get(Supplier, purchase_order.supplier_id)
    if purchase_order.idempotency_key is None:
        purchase_order.idempotency_key = secrets.token_hex(16)

    before_status = purchase_order.status.value
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        purchase_order.status = PurchaseOrderStatus.sending
        session.add(purchase_order)
        session.flush()
        audit.record(
            action="purchase_order.status_changed", entity_type="purchase_order", entity_id=purchase_order.id,
            before={"status": before_status}, after={"status": "sending"},
        )

    try:
        result = EMAIL_PROVIDER(supplier=supplier, purchase_order=purchase_order)
    except ProviderSendError as exc:
        with audited_transaction(
            session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
        ) as audit:
            purchase_order.status = PurchaseOrderStatus.send_failed
            purchase_order.last_error = str(exc)
            session.add(purchase_order)
            session.flush()
            audit.record(
                action="purchase_order.send_failed", entity_type="purchase_order", entity_id=purchase_order.id,
                before={"status": "sending"}, after={"status": "send_failed", "error": str(exc)},
            )
        return purchase_order

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        purchase_order.status = PurchaseOrderStatus.sent
        purchase_order.sent_at = datetime.now(timezone.utc)
        purchase_order.sent_by = actor.id
        purchase_order.provider_message_id = result.message_id
        purchase_order.recipient_snapshot = result.recipient
        purchase_order.last_error = None
        session.add(purchase_order)
        session.flush()
        audit.record(
            action="purchase_order.sent", entity_type="purchase_order", entity_id=purchase_order.id,
            before={"status": "sending"},
            after={
                "status": "sent", "provider_message_id": result.message_id,
                "recipient_snapshot": result.recipient,
            },
        )
    return purchase_order


def mark_delivery(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    purchase_order: PurchaseOrder,
    partial: bool,
    line_notes: dict[uuid.UUID, str] | None = None,
) -> PurchaseOrder:
    """Marks a PurchaseOrder received or partially_received. AC: a partial
    delivery requires at least one line-level note — a bare "partial" flag
    with no explanation of what was short is not accepted."""
    line_notes = line_notes or {}
    if partial and not any(note and note.strip() for note in line_notes.values()):
        raise PartialDeliveryRequiresLineNote(
            "A partial delivery requires at least one line-level note"
        )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        before_status = purchase_order.delivery_status.value
        purchase_order.delivery_status = (
            DeliveryStatus.partially_received if partial else DeliveryStatus.received
        )
        session.add(purchase_order)
        for line in purchase_order.lines:
            note = line_notes.get(line.id)
            if note:
                line.delivery_note = note
                session.add(line)
        session.flush()
        audit.record(
            action="purchase_order.delivery_marked", entity_type="purchase_order", entity_id=purchase_order.id,
            before={"delivery_status": before_status},
            after={"delivery_status": purchase_order.delivery_status.value},
        )
    return purchase_order


def log_delivery_issue(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    purchase_order: PurchaseOrder,
    issue_type: DeliveryIssueType,
    evidence: str | None = None,
    resolution: str | None = None,
) -> DeliveryIssue:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        issue = DeliveryIssue(
            purchase_order_id=purchase_order.id, issue_type=issue_type,
            evidence=evidence, resolution=resolution,
        )
        session.add(issue)
        session.flush()
        audit.record(
            action="delivery_issue.logged", entity_type="delivery_issue", entity_id=issue.id,
            after={
                "purchase_order_id": str(purchase_order.id), "issue_type": issue_type.value,
                "evidence": evidence, "resolution": resolution,
            },
        )
    return issue
