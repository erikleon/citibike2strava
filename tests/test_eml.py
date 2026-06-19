from email.message import EmailMessage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

from citibike2strava.eml import MAX_EML_BYTES, EmlParseError, html_from_eml

FIXTURE = Path(__file__).parent / "fixtures" / "sample_receipt.html"


@pytest.fixture
def receipt_html():
    return FIXTURE.read_text(encoding="utf-8")


def test_simple_eml_with_html_part(receipt_html):
    msg = EmailMessage()
    msg["Subject"] = "Ride Receipt"
    msg["From"] = "updates@citibikenyc.com"
    msg.add_alternative(receipt_html, subtype="html")
    out = html_from_eml(msg.as_bytes())
    assert "polyline=" in out


def test_raw_html_paste_passthrough(receipt_html):
    # Not an email at all — just receipt HTML on stdin.
    out = html_from_eml(receipt_html)
    assert "polyline=" in out


def test_prefers_html_part_with_polyline(receipt_html):
    # A forward whose cover note is its own HTML part lacking the route; the
    # receipt body (with polyline) must be the one chosen.
    outer = MIMEMultipart("mixed")
    outer.attach(MIMEText("<html><body>FYI my ride</body></html>", "html"))
    outer.attach(MIMEText(receipt_html, "html"))
    out = html_from_eml(outer.as_bytes())
    assert "polyline=" in out


def test_forwarded_as_attachment_nested_rfc822(receipt_html):
    inner = MIMEText(receipt_html, "html")
    inner["Subject"] = "Ride Receipt"
    inner["From"] = "updates@citibikenyc.com"

    outer = MIMEMultipart("mixed")
    outer.attach(MIMEText("Forwarding my ride receipt.", "plain"))
    outer.attach(MIMEMessage(inner))  # original receipt as a message/rfc822 part

    out = html_from_eml(outer.as_bytes())
    assert "polyline=" in out


def test_no_html_raises():
    msg = EmailMessage()
    msg["Subject"] = "hello"
    msg.set_content("plain text only, no receipt here")
    with pytest.raises(EmlParseError):
        html_from_eml(msg.as_bytes())


def test_oversize_input_raises():
    with pytest.raises(EmlParseError):
        html_from_eml(b"x" * (MAX_EML_BYTES + 1))
