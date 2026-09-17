#!/usr/bin/env python3
"""
Epic 11 — seed/import script (locked AC: "Seed/import script loads the
known customer's real menu, suppliers, staff, stations into the system").

No actual pilot customer's data was available to this build, so what ships
here is the SCRIPT — fully generic and data-driven — plus one clearly
labeled, made-up sample dataset (scripts/seed_data/sample_venue.yaml) for
demos and smoke-testing a fresh environment. Onboarding a real pilot venue
is then: copy that YAML file, replace every value with the real venue's
real information, and point --config at it. The script itself never
fabricates or assumes any real customer's data.

Deliberately built on the SAME service-layer functions every API route
calls (onboarding_service, staffing_service, catalog_service,
prep_service) rather than raw INSERTs — that's what makes a seeded venue
indistinguishable from one a Head Chef set up by hand through the app: it
gets the exact same validation, and the exact same AuditEvent trail
(organisation.created, venue.created, station.created, ...) any other
onboarding path would produce.

One-shot, not an upsert: if an Organisation with the config's
organisation_name already exists, the script prints a message and exits
without touching anything — re-seeding the same config twice is a no-op,
not a duplicate. Delete the organisation (and its dependents) first if you
genuinely want to re-run it.

Usage:
    python3 scripts/seed.py                              # the bundled sample dataset
    python3 scripts/seed.py --config path/to/venue.yaml   # a real venue's data
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from datetime import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.services.catalog_service import (  # noqa: E402
    create_equipment_item,
    create_ingredient,
    create_menu_item,
    create_supplier,
)
from app.services.onboarding_service import create_organisation_with_venue  # noqa: E402
from app.services.prep_service import add_template_item, create_prep_template  # noqa: E402
from app.services.staffing_service import (  # noqa: E402
    add_staff_skill,
    create_coverage_rule,
    create_staff,
    create_station,
)
from app.services.user_service import find_or_create_user  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "seed_data" / "sample_venue.yaml"


def _parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def seed(session, config: dict) -> None:
    organisation_name = config["organisation_name"]
    existing = session.query(Organisation).filter_by(name=organisation_name).one_or_none()
    if existing is not None:
        print(
            f"Organisation {organisation_name!r} already exists (id={existing.id}) — "
            "nothing to do. This script is one-shot, not an upsert; delete the "
            "organisation first if you really want to re-seed it."
        )
        return

    owner = find_or_create_user(session, email=config["owner_email"])

    organisation, venue, _membership = create_organisation_with_venue(
        session, owner=owner, organisation_name=organisation_name, venue_name=config["venue_name"],
        timezone=config.get("timezone"), business_day_boundary=_parse_time(config.get("business_day_boundary")),
    )
    print(f"Created organisation {organisation.name!r} / venue {venue.name!r} (venue_id={venue.id})")

    stations_by_name = {}
    for name in config.get("stations", []):
        stations_by_name[name] = create_station(session, venue=venue, actor=owner, name=name)
    print(f"  stations: {len(stations_by_name)}")

    staff_count = 0
    for entry in config.get("staff", []):
        staff = create_staff(
            session, venue=venue, actor=owner, name=entry["name"], contact_email=entry.get("contact_email"),
        )
        for skill_station_name in entry.get("skills", []):
            station = stations_by_name.get(skill_station_name)
            if station is None:
                print(f"  warning: staff {entry['name']!r} lists unknown station {skill_station_name!r} — skipped")
                continue
            add_staff_skill(session, venue=venue, actor=owner, staff=staff, station=station)
        staff_count += 1
    print(f"  staff: {staff_count}")

    coverage_rule_count = 0
    for rule in config.get("coverage_rules", []):
        station = stations_by_name.get(rule["station"])
        if station is None:
            print(f"  warning: coverage rule references unknown station {rule['station']!r} — skipped")
            continue
        create_coverage_rule(
            session, venue=venue, actor=owner, station=station, day_of_week=rule["day_of_week"],
            window_start=_parse_time(rule["window_start"]), window_end=_parse_time(rule["window_end"]),
            minimum_staff=rule.get("minimum_staff", 1),
        )
        coverage_rule_count += 1
    print(f"  coverage rules: {coverage_rule_count}")

    suppliers_by_name = {}
    for entry in config.get("suppliers", []):
        suppliers_by_name[entry["name"]] = create_supplier(
            session, venue=venue, actor=owner, name=entry["name"], contact_email=entry.get("contact_email"),
            order_days=entry.get("order_days"), cutoff_time=_parse_time(entry.get("cutoff_time")),
            notes=entry.get("notes"),
        )
    print(f"  suppliers: {len(suppliers_by_name)}")

    ingredient_count = 0
    for entry in config.get("ingredients", []):
        preferred_supplier = suppliers_by_name.get(entry.get("preferred_supplier"))
        create_ingredient(
            session, venue=venue, actor=owner, name=entry["name"], unit=entry["unit"],
            ordering_unit=entry["ordering_unit"],
            preferred_supplier_id=preferred_supplier.id if preferred_supplier else None,
        )
        ingredient_count += 1
    print(f"  ingredients: {ingredient_count}")

    menu_item_count = 0
    for name in config.get("menu_items", []):
        create_menu_item(session, venue=venue, actor=owner, name=name)
        menu_item_count += 1
    print(f"  menu items: {menu_item_count}")

    equipment_count = 0
    for entry in config.get("equipment_items", []):
        create_equipment_item(
            session, venue=venue, actor=owner, name=entry["name"], location=entry.get("location"),
            repair_contact=entry.get("repair_contact"),
        )
        equipment_count += 1
    print(f"  equipment items: {equipment_count}")

    template_count = 0
    for entry in config.get("prep_templates", []):
        template = create_prep_template(session, venue=venue, actor=owner, name=entry["name"])
        for item in entry.get("items", []):
            station = stations_by_name.get(item["station"])
            if station is None:
                print(f"  warning: prep template item references unknown station {item['station']!r} — skipped")
                continue
            add_template_item(
                session, venue=venue, actor=owner, template=template, station=station, item=item["item"],
                quantity=Decimal(item["quantity"]), unit=item["unit"], priority=item.get("priority", 0),
            )
        template_count += 1
    print(f"  prep templates: {template_count}")

    print(f"\nDone. venue_id={venue.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="Path to a seed YAML file (default: the bundled sample dataset)",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    session = SessionLocal()
    try:
        seed(session, config)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
