"""
Epic 1 step 4 — Authentication and Membership permissions.

Two independent mechanisms live here:

1. Magic links: how a User proves control of an email address once, to get
   logged in. Single-use, hashed at rest, expiring.
2. Access tokens: a signed JWT issued after a successful magic-link verify,
   used as a bearer credential on subsequent requests. It carries only the
   user id + expiry — no role/venue data, on purpose (see Membership's
   docstring: role checks always hit the DB fresh, so a revoked Membership
   takes effect on the very next request, not whenever the token expires).

No email provider exists yet (that's Epic 10). See app/api/routes/auth.py
for how the raw magic-link token is surfaced in the meantime.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.magic_link import MagicLink
from app.models.user import User
from app.services.user_service import find_or_create_user


class InvalidOrExpiredToken(Exception):
    """Raised for any magic-link failure — unknown, already-used, or expired.

    Deliberately one exception type for all three cases: the API response
    must not let a caller distinguish "wrong token" from "expired token"
    from "someone else's token", which would leak whether a given token
    string was ever valid."""


class InvalidAccessToken(Exception):
    """Raised when a bearer access token fails to decode/verify."""


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class IssuedMagicLink:
    user: User
    raw_token: str
    expires_at: datetime


def issue_magic_link(session: Session, *, email: str, purpose: str = "login") -> IssuedMagicLink:
    """Find-or-create the User by email, then issue a fresh magic link.

    This is also how a brand-new owner "signs up" per the locked spec —
    there is no separate registration step; requesting a link for an email
    that doesn't exist yet creates the User record. Org/Venue creation
    itself is Epic 1 step 5, not this function.
    """
    user = find_or_create_user(session, email=email)

    raw_token = _generate_raw_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_expire_minutes)
    link = MagicLink(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        purpose=purpose,
        expires_at=expires_at,
    )
    session.add(link)
    session.commit()

    return IssuedMagicLink(user=user, raw_token=raw_token, expires_at=expires_at)


def verify_magic_link(session: Session, *, raw_token: str, purpose: str = "login") -> User:
    """Consume a magic link token exactly once. Raises InvalidOrExpiredToken
    for any failure mode (see that class's docstring for why they're not
    distinguished)."""
    token_hash = _hash_token(raw_token)
    link = session.query(MagicLink).filter_by(token_hash=token_hash, purpose=purpose).one_or_none()

    if link is None:
        raise InvalidOrExpiredToken("no such token")
    if link.consumed_at is not None:
        raise InvalidOrExpiredToken("token already used")
    if link.expires_at < datetime.now(timezone.utc):
        raise InvalidOrExpiredToken("token expired")

    link.consumed_at = datetime.now(timezone.utc)
    session.add(link)
    session.commit()

    user = session.get(User, link.user_id)
    if user is None:  # pragma: no cover — FK guarantees this in practice
        raise InvalidOrExpiredToken("user no longer exists")
    return user


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Returns the user id encoded in a valid, unexpired access token.
    Raises InvalidAccessToken otherwise (bad signature, malformed, expired)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidAccessToken(str(exc)) from exc

    sub = payload.get("sub")
    if not sub:
        raise InvalidAccessToken("token missing subject")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidAccessToken("token subject is not a valid user id") from exc
