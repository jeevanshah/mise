"""
Epic 10 — Operational Email Notifications.

The real, pluggable EmailSender interface every earlier epic's docstring
has been pointing at ("no email provider exists yet — Epic 10"):
StaffLink's raw-token-in-response stand-in (Epic 2), supplier_order_
service's own EMAIL_PROVIDER stub (Epic 5). This module generalizes the
same "module-level hook, not a hardcoded call" pattern those already used
into the ONE place every outbound email in the system should go through,
so a real provider (SES/Postmark/etc.) can be swapped in later without
touching any caller.

No real SMTP/API integration in v1 (locked build is backend-only) — the
default sender "sends" by logging and returns a durable, unique message_id,
so the full trigger -> send -> audit pipeline can be built, tested, and
used end to end today. Swappable in tests via EMAIL_SENDER, the same way
supplier_order_service.EMAIL_PROVIDER already is.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("mise.email")


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


@dataclass
class SentEmail:
    message_id: str
    to: str


def _stub_email_sender(message: EmailMessage) -> SentEmail:
    message_id = f"stub-{uuid.uuid4()}"
    logger.info("EMAIL to=%s subject=%r message_id=%s", message.to, message.subject, message_id)
    return SentEmail(message_id=message_id, to=message.to)


# Module-level hook, deliberately swappable — see this module's own
# docstring. Tests substitute a fake the same way
# tests/test_supplier_order_service.py already does for EMAIL_PROVIDER.
EMAIL_SENDER: Callable[[EmailMessage], SentEmail] = _stub_email_sender


def send_email(*, to: str, subject: str, body: str) -> SentEmail:
    """The one function every outbound email in the system should call —
    never EMAIL_SENDER directly — so a future real-provider swap only ever
    happens in this one place."""
    return EMAIL_SENDER(EmailMessage(to=to, subject=subject, body=body))
