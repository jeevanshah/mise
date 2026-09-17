"""
Unit tests for app/services/auth_service.py — the magic-link and access-token
mechanics, independent of HTTP (see tests/test_auth_http.py for the
end-to-end request/response flow).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.magic_link import MagicLink
from app.models.user import User
from app.services.auth_service import (
    InvalidAccessToken,
    InvalidOrExpiredToken,
    create_access_token,
    decode_access_token,
    issue_magic_link,
    verify_magic_link,
)


def test_issue_magic_link_creates_user_when_none_exists(session):
    assert session.query(User).filter_by(email="new.chef@example.com").one_or_none() is None

    issued = issue_magic_link(session, email="new.chef@example.com")

    assert issued.user.email == "new.chef@example.com"
    assert session.query(User).filter_by(email="new.chef@example.com").one() is not None


def test_issue_magic_link_reuses_existing_user_and_normalises_email(session):
    user = User(email="chef@example.com")
    session.add(user)
    session.commit()

    issued = issue_magic_link(session, email="  Chef@Example.com  ")

    assert issued.user.id == user.id
    assert session.query(User).count() == 1


def test_raw_token_is_never_stored(session):
    issued = issue_magic_link(session, email="chef@example.com")

    link = session.query(MagicLink).one()
    assert link.token_hash != issued.raw_token
    assert issued.raw_token not in link.token_hash


def test_verify_magic_link_succeeds_once_and_returns_the_user(session):
    issued = issue_magic_link(session, email="chef@example.com")

    user = verify_magic_link(session, raw_token=issued.raw_token)

    assert user.id == issued.user.id


def test_verify_magic_link_rejects_reuse(session):
    issued = issue_magic_link(session, email="chef@example.com")
    verify_magic_link(session, raw_token=issued.raw_token)

    with pytest.raises(InvalidOrExpiredToken):
        verify_magic_link(session, raw_token=issued.raw_token)


def test_verify_magic_link_rejects_unknown_token(session):
    with pytest.raises(InvalidOrExpiredToken):
        verify_magic_link(session, raw_token="this-token-was-never-issued")


def test_verify_magic_link_rejects_expired_token(session):
    issued = issue_magic_link(session, email="chef@example.com")
    link = session.query(MagicLink).filter_by(user_id=issued.user.id).one()
    link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.add(link)
    session.commit()

    with pytest.raises(InvalidOrExpiredToken):
        verify_magic_link(session, raw_token=issued.raw_token)


def test_access_token_round_trips_to_the_same_user_id(session):
    user = User(email="chef@example.com")
    session.add(user)
    session.commit()

    token = create_access_token(user.id)
    decoded_user_id = decode_access_token(token)

    assert decoded_user_id == user.id


def test_decode_access_token_rejects_garbage():
    with pytest.raises(InvalidAccessToken):
        decode_access_token("not-a-real-jwt")


def test_decode_access_token_rejects_tampered_signature(session):
    user = User(email="chef@example.com")
    session.add(user)
    session.commit()

    token = create_access_token(user.id)
    tampered = token[:-4] + ("0" * 4 if not token.endswith("0000") else "1111")

    with pytest.raises(InvalidAccessToken):
        decode_access_token(tampered)
