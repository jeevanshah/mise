"""
Epic 4 — Prep Plan.

Applying a PrepTemplate COPIES each PrepTemplateItem's fields onto a new
PrepTask — a PrepTask never references its template item live, so editing
either afterwards never touches the other (locked AC). Carry-forward
follows the same copy pattern, chained rather than branched (see
PrepTask's docstring for why that keeps it from duplicating indefinitely).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.prep import PrepTask, PrepTaskStatus, PrepTemplate, PrepTemplateItem
from app.models.service_day import ServiceDay
from app.models.station import Station
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


def create_prep_template(session: Session, *, venue: Venue, actor: User, name: str) -> PrepTemplate:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        template = PrepTemplate(venue_id=venue.id, name=name)
        session.add(template)
        session.flush()
        audit.record(
            action="prep_template.created", entity_type="prep_template", entity_id=template.id,
            after={"name": name},
        )
    return template


def add_template_item(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    template: PrepTemplate,
    station: Station,
    item: str,
    quantity: Decimal,
    unit: str,
    priority: int = 0,
) -> PrepTemplateItem:
    next_sort_order = (
        session.query(PrepTemplateItem).filter_by(template_id=template.id).count()
    )
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        template_item = PrepTemplateItem(
            template_id=template.id, station_id=station.id, item=item,
            quantity=quantity, unit=unit, priority=priority, sort_order=next_sort_order,
        )
        session.add(template_item)
        session.flush()
        audit.record(
            action="prep_template_item.created", entity_type="prep_template_item",
            entity_id=template_item.id,
            after={
                "template_id": str(template.id), "station_id": str(station.id), "item": item,
                "quantity": str(quantity), "unit": unit, "priority": priority,
            },
        )
    return template_item


def apply_prep_template(
    session: Session, *, venue: Venue, actor: User, template: PrepTemplate, service_day: ServiceDay
) -> list[PrepTask]:
    """Creates one PrepTask per PrepTemplateItem (ordered by sort_order),
    with every working field COPIED — not referenced — from the template
    item, so subsequent edits to either never touch the other."""
    template_items = (
        session.query(PrepTemplateItem)
        .filter_by(template_id=template.id)
        .order_by(PrepTemplateItem.sort_order)
        .all()
    )
    created: list[PrepTask] = []
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        for template_item in template_items:
            task = PrepTask(
                venue_id=venue.id,
                service_day_id=service_day.id,
                station_id=template_item.station_id,
                item=template_item.item,
                quantity=template_item.quantity,
                unit=template_item.unit,
                priority=template_item.priority,
                status=PrepTaskStatus.not_started,
                template_item_id=template_item.id,
            )
            session.add(task)
            session.flush()
            audit.record(
                action="prep_task.created", entity_type="prep_task", entity_id=task.id,
                after={
                    "station_id": str(task.station_id), "item": task.item,
                    "quantity": str(task.quantity), "unit": task.unit,
                    "template_id": str(template.id),
                },
            )
            created.append(task)
    return created


def update_prep_task_status(
    session: Session, *, venue: Venue, actor: User, task: PrepTask, status: PrepTaskStatus
) -> PrepTask:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=task.service_day_id,
    ) as audit:
        before_status = task.status.value
        task.status = status
        session.add(task)
        session.flush()
        audit.record(
            action="prep_task.status_changed", entity_type="prep_task", entity_id=task.id,
            before={"status": before_status}, after={"status": status.value},
        )
    return task


def carry_forward_prep_tasks(
    session: Session, *, venue: Venue, actor: User, from_service_day: ServiceDay, to_service_day: ServiceDay
) -> list[PrepTask]:
    """Creates a next-day PrepTask for every not-done task in
    from_service_day that hasn't already been carried forward — calling
    this twice for the same pair of days is a no-op the second time
    (idempotent, same reasoning as publish_shift/open_service_day), so it
    never duplicates. carry_count climbs by exactly one per hop; the chain
    only ever extends, never branches, since a task with carried_to_task_id
    already set is skipped."""
    not_done_uncarried = (
        session.query(PrepTask)
        .filter(
            PrepTask.service_day_id == from_service_day.id,
            PrepTask.status != PrepTaskStatus.done,
            PrepTask.carried_to_task_id.is_(None),
        )
        .all()
    )
    if not not_done_uncarried:
        # Nothing to carry, but to_service_day may have just been lazily
        # created by the caller (get_or_create_service_day) and only
        # flushed, not committed — commit here so referencing a future day
        # always persists it, exactly like every other lazy-creation path.
        session.commit()
        return []

    created: list[PrepTask] = []
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
    ) as audit:
        for original in not_done_uncarried:
            new_task = PrepTask(
                venue_id=venue.id,
                service_day_id=to_service_day.id,
                station_id=original.station_id,
                item=original.item,
                quantity=original.quantity,
                unit=original.unit,
                priority=original.priority,
                status=PrepTaskStatus.not_started,
                template_item_id=original.template_item_id,
                carried_from_task_id=original.id,
                carry_count=original.carry_count + 1,
            )
            session.add(new_task)
            session.flush()

            original.carried_to_task_id = new_task.id
            session.add(original)
            session.flush()

            audit.record(
                action="prep_task.carried_forward", entity_type="prep_task", entity_id=original.id,
                before={"carried_to_task_id": None},
                after={"carried_to_task_id": str(new_task.id), "new_carry_count": new_task.carry_count},
                service_day_id=from_service_day.id,
            )
            audit.record(
                action="prep_task.created", entity_type="prep_task", entity_id=new_task.id,
                after={
                    "station_id": str(new_task.station_id), "item": new_task.item,
                    "carried_from_task_id": str(original.id), "carry_count": new_task.carry_count,
                },
                service_day_id=to_service_day.id,
            )
            created.append(new_task)
    return created
