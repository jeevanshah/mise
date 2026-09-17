from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditEvent
from app.models.purchase_order import (
    DeliveryIssue,
    DeliveryIssueType,
    DeliveryStatus,
    PurchaseOrder,
    PurchaseOrderStatus,
)
from app.models.user import User
from app.services.catalog_service import create_ingredient, create_supplier
from app.services.onboarding_service import create_organisation_with_venue
from app.services import supplier_order_service as sos
from app.services.supplier_order_service import (
    CannotModifyNonDraftOrder,
    CannotSendOrder,
    MissingOrderIdentity,
    PartialDeliveryRequiresLineNote,
    ProviderSendError,
    ProviderSendResult,
    UnknownIngredient,
    UnknownSupplier,
    add_or_merge_line,
    get_or_create_draft_purchase_order,
    log_delivery_issue,
    mark_delivery,
    send_purchase_order,
    update_line_quantity,
)


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def _supplier_and_ingredient(session, venue, actor, contact_email="supplier@example.com"):
    supplier = create_supplier(session, venue=venue, actor=actor, name="Fresh Co", contact_email=contact_email)
    ingredient = create_ingredient(
        session, venue=venue, actor=actor, name="Onions", unit="kg", ordering_unit="carton",
    )
    return supplier, ingredient


@pytest.fixture(autouse=True)
def _reset_email_provider():
    """Every test gets the real default stub provider unless it explicitly
    monkeypatches sos.EMAIL_PROVIDER — reset afterwards so tests never leak
    a fake provider into each other."""
    original = sos.EMAIL_PROVIDER
    yield
    sos.EMAIL_PROVIDER = original


def test_add_line_creates_draft_with_open_draft_identity(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)

    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )

    assert result.merged is False
    assert result.purchase_order.status == PurchaseOrderStatus.draft
    assert result.line.unit == "carton"  # defaulted from Ingredient.ordering_unit
    assert result.line.quantity == Decimal("5")


def test_missing_identity_raises(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)

    with pytest.raises(MissingOrderIdentity):
        add_or_merge_line(
            session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
            quantity=Decimal("5"),
        )


def test_unknown_supplier_and_ingredient_raise(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    import uuid

    with pytest.raises(UnknownSupplier):
        add_or_merge_line(
            session, venue=venue, actor=owner, supplier_id=uuid.uuid4(), ingredient_id=ingredient.id,
            quantity=Decimal("1"), required_delivery_date=date(2026, 6, 10),
        )
    with pytest.raises(UnknownIngredient):
        add_or_merge_line(
            session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=uuid.uuid4(),
            quantity=Decimal("1"), required_delivery_date=date(2026, 6, 10),
        )


def test_second_add_for_same_key_and_ingredient_merges_not_duplicates(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)

    first = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    second = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("3"), required_delivery_date=date(2026, 6, 10),
    )

    assert second.merged is True
    assert second.previous_quantity == Decimal("5")
    assert second.line.id == first.line.id  # same line, not a duplicate
    assert second.line.quantity == Decimal("8")
    assert second.purchase_order.id == first.purchase_order.id  # same draft
    assert len(second.purchase_order.lines) == 1


def test_different_delivery_date_creates_separate_draft(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)

    friday = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 12),
    )
    next_tuesday = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 16),
    )

    assert friday.purchase_order.id != next_tuesday.purchase_order.id
    assert session.query(PurchaseOrder).filter_by(venue_id=venue.id).count() == 2


def test_different_ingredient_same_draft_adds_second_line(session):
    owner, venue = _owner_venue(session)
    supplier, onions = _supplier_and_ingredient(session, venue, owner)
    carrots = create_ingredient(session, venue=venue, actor=owner, name="Carrots", unit="kg", ordering_unit="bag")

    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=carrots.id,
        quantity=Decimal("2"), required_delivery_date=date(2026, 6, 10),
    )

    assert len(result.purchase_order.lines) == 2


def test_get_or_create_draft_purchase_order_is_idempotent(session):
    owner, venue = _owner_venue(session)
    supplier, _ = _supplier_and_ingredient(session, venue, owner)

    first = get_or_create_draft_purchase_order(
        session, venue=venue, supplier=supplier, order_cycle="standing-tuesday"
    )
    session.commit()
    second = get_or_create_draft_purchase_order(
        session, venue=venue, supplier=supplier, order_cycle="standing-tuesday"
    )

    assert first.id == second.id


def test_add_or_merge_line_writes_audit_event(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)

    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    event = session.query(AuditEvent).filter_by(action="purchase_order_line.created").one()
    assert event.after_data["quantity"] == "5"


def test_update_line_quantity_corrects_after_merge(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )

    updated = update_line_quantity(session, venue=venue, actor=owner, line=result.line, quantity=Decimal("10"))

    assert updated.quantity == Decimal("10")


def test_update_line_quantity_fails_once_order_left_draft(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    with pytest.raises(CannotModifyNonDraftOrder):
        update_line_quantity(session, venue=venue, actor=owner, line=result.line, quantity=Decimal("99"))


def test_send_purchase_order_success_sets_fields_and_status(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner, contact_email="orders@fresh.co")
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )

    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    assert order.status == PurchaseOrderStatus.sent
    assert order.sent_at is not None
    assert order.sent_by == owner.id
    assert order.recipient_snapshot == "orders@fresh.co"
    assert order.provider_message_id is not None
    assert order.idempotency_key is not None
    assert order.last_error is None


def test_cannot_send_empty_order(session):
    owner, venue = _owner_venue(session)
    supplier, _ = _supplier_and_ingredient(session, venue, owner)
    order = get_or_create_draft_purchase_order(
        session, venue=venue, supplier=supplier, required_delivery_date=date(2026, 6, 10)
    )
    session.commit()

    with pytest.raises(CannotSendOrder):
        send_purchase_order(session, venue=venue, actor=owner, purchase_order=order)


def test_cannot_send_already_sent_order(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    with pytest.raises(CannotSendOrder):
        send_purchase_order(session, venue=venue, actor=owner, purchase_order=order)


def test_send_failure_sets_send_failed_with_error_and_keeps_idempotency_key(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner, contact_email=None)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )

    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    assert order.status == PurchaseOrderStatus.send_failed
    assert order.last_error is not None
    assert order.idempotency_key is not None
    key_after_failure = order.idempotency_key

    # Retry reuses the SAME idempotency key rather than minting a new one —
    # this is what lets the provider dedupe a retry after a timeout.
    def fake_success(*, supplier, purchase_order):  # noqa: ARG001
        return ProviderSendResult(message_id="retry-ok", recipient="fixed@fresh.co")

    sos.EMAIL_PROVIDER = fake_success
    retried = send_purchase_order(session, venue=venue, actor=owner, purchase_order=order)

    assert retried.status == PurchaseOrderStatus.sent
    assert retried.idempotency_key == key_after_failure
    assert retried.provider_message_id == "retry-ok"


def test_provider_error_writes_send_failed_audit_event(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )

    def fake_failure(*, supplier, purchase_order):  # noqa: ARG001
        raise ProviderSendError("provider rejected message")

    sos.EMAIL_PROVIDER = fake_failure
    send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    event = session.query(AuditEvent).filter_by(action="purchase_order.send_failed").one()
    assert event.after_data["error"] == "provider rejected message"


def test_mark_delivery_full_receipt(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    updated = mark_delivery(session, venue=venue, actor=owner, purchase_order=order, partial=False)

    assert updated.delivery_status == DeliveryStatus.received


def test_partial_delivery_requires_a_line_note(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    with pytest.raises(PartialDeliveryRequiresLineNote):
        mark_delivery(session, venue=venue, actor=owner, purchase_order=order, partial=True)

    updated = mark_delivery(
        session, venue=venue, actor=owner, purchase_order=order, partial=True,
        line_notes={result.line.id: "Only 3kg arrived, rest on backorder"},
    )
    assert updated.delivery_status == DeliveryStatus.partially_received
    session.refresh(result.line)
    assert result.line.delivery_note == "Only 3kg arrived, rest on backorder"


def test_log_delivery_issue(session):
    owner, venue = _owner_venue(session)
    supplier, ingredient = _supplier_and_ingredient(session, venue, owner)
    result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=ingredient.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 10),
    )
    order = send_purchase_order(session, venue=venue, actor=owner, purchase_order=result.purchase_order)

    issue = log_delivery_issue(
        session, venue=venue, actor=owner, purchase_order=order,
        issue_type=DeliveryIssueType.short_delivery, evidence="photo://stub.jpg",
        resolution=None,
    )

    assert issue.id is not None
    assert session.query(DeliveryIssue).filter_by(purchase_order_id=order.id).count() == 1
