"""WhatsApp channel for the owner (Twilio) + email-style messages to buyers.

Every message is stored in the database, so the website can show a phone
simulator even when Twilio is not configured. When Twilio keys are set,
owner messages are also really sent to the owner's WhatsApp.
"""
import logging
import re

from sqlmodel import select

from app import config
from app.db import Approval, Message

log = logging.getLogger("paymitra.whatsapp")


def send_owner(session, body: str, approval_id: int | None = None, invoice_id: str | None = None) -> Message:
    msg = Message(audience="owner", direction="out", channel="whatsapp", to=config.OWNER_WHATSAPP or "owner",
                  body=body, approval_id=approval_id, invoice_id=invoice_id)
    if config.twilio_ready():
        try:
            from twilio.rest import Client
            Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN).messages.create(
                from_=config.TWILIO_WHATSAPP_FROM, to=config.OWNER_WHATSAPP, body=body[:1550])
            msg.delivered = True
        except Exception as exc:  # never let a messaging failure break the agent loop
            log.warning("Twilio send failed: %s", exc)
    session.add(msg)
    return msg


def send_buyer(session, invoice_id: str, to: str, subject: str, body: str, channel: str = "email") -> Message:
    """Buyer messages are recorded (outbox). Wire a real email/WhatsApp Business sender here."""
    msg = Message(audience="buyer", direction="out", channel=channel, to=to, subject=subject,
                  body=body, invoice_id=invoice_id)
    session.add(msg)
    return msg


def record_inbound(session, body: str, sender: str = "owner") -> Message:
    msg = Message(audience="owner", direction="in", channel="whatsapp", to=sender, body=body)
    session.add(msg)
    return msg


_CMD = re.compile(r"^\s*(1|2|3|approve|edit|hold|yes|no)\b\s*#?(\d+)?", re.I)
WORDS = {"1": "approve", "approve": "approve", "yes": "approve",
         "2": "edit", "edit": "edit", "3": "hold", "hold": "hold", "no": "hold"}


def parse_command(text: str) -> tuple[str | None, int | None]:
    m = _CMD.match(text or "")
    if not m:
        return None, None
    return WORDS[m.group(1).lower()], (int(m.group(2)) if m.group(2) else None)


def oldest_pending(session) -> Approval | None:
    return session.exec(select(Approval).where(Approval.status == "PENDING")
                        .order_by(Approval.created_at, Approval.id)).first()


def last_offered(session) -> Approval | None:
    """The approval the bot most recently asked about, if it is still waiting.
    A bare '1' answers the question just asked (e.g. 'Finance via TReDS?')."""
    msg = session.exec(select(Message).where(Message.audience == "owner", Message.direction == "out",
                                             Message.approval_id != None)  # noqa: E711
                       .order_by(Message.id.desc())).first()
    if msg:
        a = session.get(Approval, msg.approval_id)
        if a and a.status == "PENDING":
            return a
    return None
