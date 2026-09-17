"""
Epic 11 — "Order emails and Handover/roster PDFs render correctly in
Gmail and Outlook web" (locked AC). The rendering-in-an-email-client half
of that AC is a visual-QA concern outside what a backend build can verify
(see README's Epic 11 section) — but generating the PDFs themselves is a
genuinely backend-buildable, testable feature, so that's what this module
does: turn an already-saved Handover or a week of published Shifts into a
one-page-per-topic PDF a Head Chef could print, forward, or hand to a
relief cook.

Deliberately read-only and derived: neither function writes anything —
they format data that close_service_day/publish_shift/etc. already
produced. reportlab is used because it's a pure-Python dependency already
present in this environment (no system-level wkhtmltopdf/Cairo install
needed), which matters for a script that has to run unattended in a
pilot venue's own environment later.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.capture import Capture
from app.models.equipment import EquipmentIssue, EquipmentItem
from app.models.handover import Handover, HandoverItem
from app.models.menu import MenuAvailabilityEvent, MenuItem
from app.models.prep import PrepTask
from app.models.purchase_order import DeliveryIssue, PurchaseOrder
from app.models.roster import Shift
from app.models.service_day import ServiceDay
from app.models.staff import Staff
from app.models.station import Station
from app.models.supplier import Supplier
from app.models.venue import Venue

_STYLES = getSampleStyleSheet()

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f2f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]
)


def _describe_handover_item(session: Session, item: HandoverItem) -> str:
    """One human-readable line per item, resolved from whichever typed FK
    is set — mirrors HandoverItem.item_type's own dispatch. Falls back to
    a bare identifier for a referenced row that's since been deleted
    (nothing here cascades that hard, but a PDF export should never 500
    over a dangling reference)."""
    if item.prep_task_id is not None:
        task = session.get(PrepTask, item.prep_task_id)
        if task is None:
            return "Prep task (no longer available)"
        return f"Prep: {task.item} — {task.quantity} {task.unit} — status: {task.status.value}"

    if item.menu_availability_event_id is not None:
        event = session.get(MenuAvailabilityEvent, item.menu_availability_event_id)
        if event is None:
            return "Menu availability change (no longer available)"
        menu_item = session.get(MenuItem, event.menu_item_id)
        name = menu_item.name if menu_item else "Unknown item"
        return f"Menu: {name} — {event.status.value}"

    if item.equipment_issue_id is not None:
        issue = session.get(EquipmentIssue, item.equipment_issue_id)
        if issue is None:
            return "Equipment issue (no longer available)"
        equipment_item = session.get(EquipmentItem, issue.equipment_item_id)
        name = equipment_item.name if equipment_item else "Unknown equipment"
        line = f"Equipment: {name} — priority: {issue.priority.value}, status: {issue.status.value}"
        if issue.resolution_notes:
            line += f" ({issue.resolution_notes})"
        return line

    if item.delivery_issue_id is not None:
        delivery_issue = session.get(DeliveryIssue, item.delivery_issue_id)
        if delivery_issue is None:
            return "Delivery issue (no longer available)"
        purchase_order = session.get(PurchaseOrder, delivery_issue.purchase_order_id)
        supplier_name = "Unknown supplier"
        if purchase_order is not None:
            supplier = session.get(Supplier, purchase_order.supplier_id)
            supplier_name = supplier.name if supplier else supplier_name
        return f"Delivery issue: {delivery_issue.issue_type.value} — supplier: {supplier_name}"

    if item.purchase_order_id is not None:
        purchase_order = session.get(PurchaseOrder, item.purchase_order_id)
        if purchase_order is None:
            return "Purchase order (no longer available)"
        supplier = session.get(Supplier, purchase_order.supplier_id)
        supplier_name = supplier.name if supplier else "Unknown supplier"
        return f"Purchase order: {supplier_name} — status: {purchase_order.status.value}"

    if item.capture_id is not None:
        capture = session.get(Capture, item.capture_id)
        if capture is None:
            return "Unparsed note (no longer available)"
        return f"Unparsed note: {capture.raw_text}"

    return "Item"  # pragma: no cover — the DB CHECK constraint makes this unreachable


def render_handover_pdf(session: Session, *, venue: Venue, service_day: ServiceDay, handover: Handover) -> bytes:
    """One PDF per closed day: the note the closing chef left, then every
    included HandoverItem grouped under the same six categories the
    Handover screen itself uses. Only `included` items are shown — a
    toggled-off item is exactly as absent here as it is in the API
    response (see handover_service.set_handover_item_included)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=f"Handover — {venue.name} — {service_day.business_date.isoformat()}",
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )

    elements = [
        Paragraph(f"Handover — {venue.name}", _STYLES["Title"]),
        Paragraph(f"Business date: {service_day.business_date.isoformat()}", _STYLES["Normal"]),
        Paragraph(f"Closed at: {handover.closed_at.isoformat()}", _STYLES["Normal"]),
        Spacer(1, 8),
    ]

    if handover.note:
        elements.append(Paragraph("Note from the closing chef", _STYLES["Heading2"]))
        elements.append(Paragraph(handover.note, _STYLES["Normal"]))
        elements.append(Spacer(1, 8))

    included_items = [item for item in handover.items if item.included]
    if not included_items:
        elements.append(Paragraph("Nothing outstanding — a clean handover.", _STYLES["Normal"]))
    else:
        rows = [["#", "Item"]]
        for index, item in enumerate(included_items, start=1):
            rows.append([str(index), _describe_handover_item(session, item)])
        table = Table(rows, colWidths=[10 * mm, 160 * mm])
        table.setStyle(_TABLE_STYLE)
        elements.append(table)

    doc.build(elements)
    return buffer.getvalue()


def render_roster_pdf(session: Session, *, venue: Venue, week_start: date) -> bytes:
    """One row per Shift across the 7-day window starting week_start —
    same date range list_shifts (app/api/routes/roster.py) uses for the
    roster grid, just flattened into a printable table instead of JSON."""
    shifts = (
        session.query(Shift)
        .join(ServiceDay, Shift.service_day_id == ServiceDay.id)
        .filter(
            ServiceDay.venue_id == venue.id,
            ServiceDay.business_date >= week_start,
            ServiceDay.business_date < week_start + timedelta(days=7),
        )
        .order_by(ServiceDay.business_date, Shift.start_at)
        .all()
    )

    service_days_by_id = {sd.id: sd for sd in session.query(ServiceDay).filter(
        ServiceDay.venue_id == venue.id,
        ServiceDay.business_date >= week_start,
        ServiceDay.business_date < week_start + timedelta(days=7),
    )}
    stations_by_id = {s.id: s for s in session.query(Station).filter(Station.venue_id == venue.id)}
    staff_by_id = {s.id: s for s in session.query(Staff).filter(Staff.venue_id == venue.id)}
    tz = ZoneInfo(venue.timezone)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=f"Roster — {venue.name} — week of {week_start.isoformat()}",
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )

    elements = [
        Paragraph(f"Roster — {venue.name}", _STYLES["Title"]),
        Paragraph(f"Week of {week_start.isoformat()}", _STYLES["Normal"]),
        Spacer(1, 8),
    ]

    if not shifts:
        elements.append(Paragraph("No shifts scheduled for this week.", _STYLES["Normal"]))
    else:
        rows = [["Date", "Station", "Staff", "Time", "Status"]]
        for shift in shifts:
            service_day = service_days_by_id.get(shift.service_day_id)
            business_date = service_day.business_date.isoformat() if service_day else "?"
            station = stations_by_id.get(shift.station_id)
            staff = staff_by_id.get(shift.staff_id)
            # Venue-local wall-clock time for a printed roster (same
            # ZoneInfo(venue.timezone) + astimezone pattern
            # roster_service.copy_week/compute_coverage_warnings use) —
            # start_at/end_at are stored as UTC instants, and a kitchen
            # wall poster needs local time, not UTC.
            local_start = shift.start_at.astimezone(tz)
            local_end = shift.end_at.astimezone(tz)
            time_range = f"{local_start.strftime('%H:%M')}–{local_end.strftime('%H:%M')}"
            rows.append(
                [
                    business_date,
                    station.name if station else "Unknown station",
                    staff.name if staff else "Unknown staff",
                    time_range,
                    shift.status.value,
                ]
            )
        table = Table(rows, colWidths=[24 * mm, 40 * mm, 45 * mm, 30 * mm, 25 * mm])
        table.setStyle(_TABLE_STYLE)
        elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
