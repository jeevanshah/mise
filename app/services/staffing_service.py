"""
Epic 1 step 6 — Staff/Stations/Coverage endpoints (service layer).

Covers the remaining Epic 1 ACs:
  - "Stations created with StaffSkill; StationCoverageRule set per station ×
    day-of-week (no service_type field in v1 — see open question)."
  - "A Staff record can exist with zero Users attached."

Every mutation goes through audited_transaction, same pattern as
onboarding_service — see that module's docstring for why entities that
don't exist yet (nothing here needs that trick; venue always already
exists by the time these are called) are flushed before the audited block.
"""

from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy.orm import Session

from app.models.staff import Staff, StaffSkill
from app.models.station import Station, StationCoverageRule
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class InvalidCoverageWindow(Exception):
    """window_start must be strictly before window_end — a zero-or-negative
    window can never be satisfied by any roster, so it's rejected at
    creation rather than silently always firing a coverage warning later."""


class DuplicateStaffSkill(Exception):
    """This Staff already has a StaffSkill row for this Station — use an
    update, not another create (mirrors MembershipAlreadyExists' reasoning
    in onboarding_service)."""


class DuplicateCoverageRule(Exception):
    """A rule already exists for this exact station/day/window."""


def create_station(session: Session, *, venue: Venue, actor: User, name: str) -> Station:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        station = Station(venue_id=venue.id, name=name)
        session.add(station)
        session.flush()
        audit.record(
            action="station.created", entity_type="station", entity_id=station.id,
            after={"name": station.name},
        )
    return station


def create_staff(
    session: Session, *, venue: Venue, actor: User, name: str, user_id: uuid.UUID | None = None
) -> Staff:
    """user_id is optional and unrelated to Membership — a Staff record
    tracks an employee on the floor, not a login. Passing one just links an
    existing User account (e.g. the head chef also appears on the roster);
    it is never required."""
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        staff = Staff(venue_id=venue.id, name=name, user_id=user_id)
        session.add(staff)
        session.flush()
        audit.record(
            action="staff.created", entity_type="staff", entity_id=staff.id,
            after={"name": staff.name, "user_id": str(user_id) if user_id else None},
        )
    return staff


def add_staff_skill(
    session: Session, *, venue: Venue, actor: User, staff: Staff, station: Station,
    trained: bool = True,
) -> StaffSkill:
    existing = (
        session.query(StaffSkill).filter_by(staff_id=staff.id, station_id=station.id).one_or_none()
    )
    if existing is not None:
        raise DuplicateStaffSkill(f"{staff.name} already has a skill row for {station.name}")

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        skill = StaffSkill(staff_id=staff.id, station_id=station.id, trained=trained)
        session.add(skill)
        session.flush()
        audit.record(
            action="staff_skill.created", entity_type="staff_skill", entity_id=skill.id,
            after={"staff_id": str(staff.id), "station_id": str(station.id), "trained": trained},
        )
    return skill


def create_coverage_rule(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    station: Station,
    day_of_week: int,
    window_start: time,
    window_end: time,
    minimum_staff: int = 1,
) -> StationCoverageRule:
    if window_start >= window_end:
        raise InvalidCoverageWindow(
            f"window_start ({window_start}) must be before window_end ({window_end})"
        )

    existing = (
        session.query(StationCoverageRule)
        .filter_by(
            station_id=station.id,
            day_of_week=day_of_week,
            window_start=window_start,
            window_end=window_end,
        )
        .one_or_none()
    )
    if existing is not None:
        raise DuplicateCoverageRule(
            f"A coverage rule already exists for {station.name} on day {day_of_week} "
            f"between {window_start} and {window_end}"
        )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        rule = StationCoverageRule(
            venue_id=venue.id,
            station_id=station.id,
            day_of_week=day_of_week,
            window_start=window_start,
            window_end=window_end,
            minimum_staff=minimum_staff,
        )
        session.add(rule)
        session.flush()
        audit.record(
            action="station_coverage_rule.created",
            entity_type="station_coverage_rule",
            entity_id=rule.id,
            after={
                "station_id": str(station.id),
                "day_of_week": day_of_week,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "minimum_staff": minimum_staff,
            },
        )
    return rule
