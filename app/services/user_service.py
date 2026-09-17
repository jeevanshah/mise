"""Shared User lookup/creation — used by both magic-link login (a brand-new
owner "signing up") and onboarding invites (an owner adding a teammate who
may or may not have ever logged in before). One place, so the normalisation
rule (strip + lowercase) can't drift between the two call sites."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User


def find_or_create_user(session: Session, *, email: str) -> User:
    normalised_email = email.strip().lower()
    user = session.query(User).filter_by(email=normalised_email).one_or_none()
    if user is None:
        user = User(email=normalised_email)
        session.add(user)
        session.flush()  # assign user.id without committing
    return user
