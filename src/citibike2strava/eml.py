"""Extract receipt HTML from a saved/forwarded ``.eml`` file or a raw paste.

This is what lets the tool work without the Gmail API at all: a user can save a
Citi Bike receipt as ``.eml`` (or forward it to themselves) and feed it in. The
extracted HTML goes through the exact same :meth:`Pipeline.process_html` as the
Gmail path.

Two corners worth knowing:

* **Forwarded-as-attachment.** When a mail client forwards a message as an
  attachment, the original receipt lives in a nested ``message/rfc822`` part. We
  walk the whole MIME tree (which descends into nested messages) and prefer the
  ``text/html`` part that actually contains a ``polyline=`` map URL — i.e. the
  receipt body, not the forwarder's cover note.
* **Raw HTML paste.** If the input is not an email at all (just receipt HTML on
  stdin), we detect the absence of MIME structure and return it as-is.
"""

from __future__ import annotations

import email
from email import policy

# Guard against pathological input (a giant attachment) eating memory.
MAX_EML_BYTES = 25 * 1024 * 1024


class EmlParseError(ValueError):
    """Raised when no receipt HTML can be found in the supplied data."""


def _html_parts(message) -> list[str]:
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        try:
            parts.append(part.get_content())
        except (LookupError, ValueError):
            # Unknown charset / undecodable part: skip it, try the others.
            continue
    return parts


def html_from_eml(data: bytes | str) -> str:
    """Return the receipt HTML from ``.eml`` bytes/str or a raw HTML paste."""
    raw = data.encode("utf-8", "replace") if isinstance(data, str) else data
    if len(raw) > MAX_EML_BYTES:
        raise EmlParseError(
            f"Input is {len(raw)} bytes, over the {MAX_EML_BYTES}-byte limit"
        )

    message = email.message_from_bytes(raw, policy=policy.default)
    htmls = _html_parts(message)

    if not htmls:
        # Not a MIME message with an HTML part — maybe a raw HTML paste.
        text = raw.decode("utf-8", "replace")
        if "polyline=" in text:
            return text
        raise EmlParseError("No text/html receipt body found in the input")

    # Prefer the HTML that carries the route polyline (the actual receipt),
    # not a forwarder's cover note; fall back to the largest HTML part.
    for html in htmls:
        if "polyline=" in html:
            return html
    return max(htmls, key=len)
