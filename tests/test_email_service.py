from app.services import email_service


def test_stub_sender_returns_unique_message_ids_and_echoes_recipient():
    first = email_service.send_email(to="a@example.com", subject="Hi", body="Body")
    second = email_service.send_email(to="a@example.com", subject="Hi", body="Body")

    assert first.message_id != second.message_id
    assert first.to == "a@example.com"


def test_email_sender_is_swappable():
    """Same module-level-hook pattern as supplier_order_service.EMAIL_PROVIDER
    — a caller (or a test) can substitute a fake sender without touching
    send_email's own signature."""
    original = email_service.EMAIL_SENDER
    sent = []

    def fake_sender(message: email_service.EmailMessage) -> email_service.SentEmail:
        sent.append(message)
        return email_service.SentEmail(message_id="fixed-id", to=message.to)

    try:
        email_service.EMAIL_SENDER = fake_sender
        result = email_service.send_email(to="chef@example.com", subject="Test", body="Body text")

        assert result.message_id == "fixed-id"
        assert sent[0].to == "chef@example.com"
        assert sent[0].subject == "Test"
        assert sent[0].body == "Body text"
    finally:
        email_service.EMAIL_SENDER = original
