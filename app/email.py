"""Outbound email (decision 0004). One small interface; Resend in production, console in dev."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import get_settings
from app.i18n import _

log = logging.getLogger(__name__)


@dataclass
class Email:
    to: str
    subject: str
    text: str


class EmailError(RuntimeError):
    pass


class EmailSender(Protocol):
    def send(self, email: Email) -> None: ...


class ResendSender:
    endpoint = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str):
        self.api_key = api_key
        self.sender = sender

    def send(self, email: Email) -> None:
        try:
            r = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"from": self.sender, "to": [email.to], "subject": email.subject,
                      "text": email.text},
                timeout=15,
            )
        except httpx.HTTPError as e:
            raise EmailError(f"resend request failed: {type(e).__name__}") from e
        if r.status_code >= 300:
            # Resend error bodies contain no secrets; keep them for debugging.
            raise EmailError(f"resend returned {r.status_code}: {r.text[:300]}")


class ConsoleSender:
    """Dev only: prints emails (including login links) to the log instead of sending."""

    def send(self, email: Email) -> None:
        log.warning("DEV EMAIL to=%s subject=%s\n%s", email.to, email.subject, email.text)


@dataclass
class MemorySender:
    """Tests: collects emails in memory."""

    outbox: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.outbox.append(email)


class MisconfiguredSender:
    def send(self, email: Email) -> None:
        raise EmailError("RESEND_API_KEY is not set")


def get_email_sender() -> EmailSender:
    s = get_settings()
    if s.is_dev:
        return ConsoleSender()
    if not s.resend_api_key:
        return MisconfiguredSender()
    return ResendSender(s.resend_api_key, s.email_from)


def login_email(to: str, link: str, code: str) -> Email:
    s = get_settings()
    # The code goes into the subject too: iPhone and Mac offer to fill it in from Mail.
    return Email(
        to=to,
        subject=_("Jobsearch Kit sign-in code: {code}", code=code),
        text=_(
            "Hello!\n\nYour sign-in code: {code}\n"
            "Enter it on the page where you asked for it.\n\n"
            "Or open this link:\n{link}\n\n"
            "The code and the link work once and are valid for {minutes} minutes.\n"
            "If you did not ask for them, just ignore this email.",
            code=code, link=link, minutes=s.login_token_ttl_minutes,
        ),
    )


def invite_email(to: str) -> Email:
    s = get_settings()
    return Email(
        to=to,
        subject=_("You are invited to Jobsearch Kit"),
        text=_(
            "Hello!\n\nYou have been invited to Jobsearch Kit, a job-search assistant.\n\n"
            "To sign in, open {url} and enter this email address: {email}\n"
            "You will receive a sign-in link. No password needed.",
            url=s.app_base_url, email=to,
        ),
    )
