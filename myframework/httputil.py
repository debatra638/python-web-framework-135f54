"""Low-level HTTP helpers: status lines, header parsing, cookies and dates.

These functions are pure and have no dependency on the rest of the framework,
which keeps them easy to test and reuse.
"""

from __future__ import annotations

import email.utils
import re
import unicodedata
from datetime import datetime, timezone
from http import HTTPStatus
from urllib.parse import unquote

__all__ = [
    "status_line",
    "parse_options_header",
    "parse_cookie_header",
    "dump_set_cookie",
    "http_date",
    "parse_http_date",
    "parse_accept",
    "prefers_json",
    "secure_filename",
    "is_token",
]

_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# RFC 6265 cookie-octet: printable US-ASCII except space, DQUOTE, comma, semicolon and backslash.
_COOKIE_VALUE_RE = re.compile(r"^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]*$")
_OPTION_RE = re.compile(
    r"""\s*;\s*([^\s;=]+)\s*(?:=\s*("(?:[^"\\]|\\.)*"|[^;]*?))?\s*(?=;|$)""",
    re.DOTALL,
)
_SAMESITE_VALUES = {"strict": "Strict", "lax": "Lax", "none": "None"}


def is_token(value: str) -> bool:
    """Return ``True`` if *value* is a valid RFC 7230 token (header names, methods, cookie names)."""
    return bool(_TOKEN_RE.match(value))


def status_line(code: int) -> str:
    """Return a WSGI status string such as ``"404 Not Found"`` for *code*."""
    if not 100 <= code <= 999:
        raise ValueError(f"Invalid HTTP status code: {code!r}")
    try:
        phrase = HTTPStatus(code).phrase
    except ValueError:
        phrase = "UNKNOWN"
    return f"{code} {phrase}"


def _unquote_header_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
        return re.sub(r"\\(.)", r"\1", value)
    return value


def parse_options_header(value: str | None) -> tuple[str, dict[str, str]]:
    """Split a header like ``multipart/form-data; boundary="x"`` into ``(value, params)``.

    The main value is lower-cased. Parameter names are lower-cased. RFC 5987 extended
    parameters (``filename*=UTF-8''na%C3%AFve.txt``) are decoded and take precedence
    over their plain counterparts.
    """
    if not value:
        return "", {}
    main, sep, rest = value.partition(";")
    params: dict[str, str] = {}
    extended: dict[str, str] = {}
    if sep:
        for match in _OPTION_RE.finditer(";" + rest):
            key = match.group(1).lower()
            raw = match.group(2) or ""
            if key.endswith("*"):
                charset, _, encoded = raw.partition("''")
                try:
                    extended[key[:-1]] = unquote(encoded, encoding=charset or "utf-8", errors="strict")
                except (LookupError, UnicodeDecodeError):
                    continue
            else:
                params[key] = _unquote_header_value(raw.strip())
    params.update(extended)
    return main.strip().lower(), params


def parse_cookie_header(value: str | None) -> dict[str, str]:
    """Parse a ``Cookie`` request header into a dict.

    Malformed pairs are skipped rather than rejecting the whole header. When a name
    appears more than once the first occurrence wins (it is the most specific path).
    """
    cookies: dict[str, str] = {}
    if not value:
        return cookies
    for chunk in value.split(";"):
        name, sep, val = chunk.partition("=")
        name = name.strip()
        if not sep or not name or not is_token(name):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        cookies.setdefault(name, val)
    return cookies


def http_date(timestamp: float | datetime | None = None) -> str:
    """Format *timestamp* (default: now) as an IMF-fixdate, e.g. ``Wed, 21 Oct 2026 07:28:00 GMT``."""
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.timestamp()
    return email.utils.formatdate(timestamp, usegmt=True)


def parse_http_date(value: str | None) -> datetime | None:
    """Parse an HTTP date header. Returns ``None`` when the value is missing or malformed."""
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def dump_set_cookie(
    name: str,
    value: str = "",
    *,
    max_age: int | None = None,
    expires: datetime | float | None = None,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    httponly: bool = True,
    samesite: str | None = "Lax",
) -> str:
    """Build a ``Set-Cookie`` header value, validating every component.

    Raises :class:`ValueError` for names or values that would produce an invalid or
    injectable header, and for ``SameSite=None`` without ``Secure`` (browsers reject it).
    """
    if not name or not is_token(name):
        raise ValueError(f"Invalid cookie name {name!r}: must be a non-empty RFC 7230 token.")
    if not _COOKIE_VALUE_RE.match(value):
        raise ValueError(
            f"Invalid cookie value for {name!r}: cookie values may not contain spaces, quotes, "
            "commas, semicolons, backslashes or non-ASCII characters. Encode the value first "
            "(for example with urllib.parse.quote or base64)."
        )
    parts = [f"{name}={value}"]
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    if expires is not None:
        parts.append(f"Expires={http_date(expires)}")
    for label, attr in (("Domain", domain), ("Path", path)):
        if attr is not None:
            if any(c in attr for c in ";\r\n\x00"):
                raise ValueError(f"Invalid cookie {label.lower()} {attr!r}.")
            parts.append(f"{label}={attr}")
    if secure:
        parts.append("Secure")
    if httponly:
        parts.append("HttpOnly")
    if samesite is not None:
        normalized = _SAMESITE_VALUES.get(samesite.lower())
        if normalized is None:
            raise ValueError("samesite must be 'Strict', 'Lax', 'None' or None.")
        if normalized == "None" and not secure:
            raise ValueError("SameSite=None requires secure=True; browsers reject it otherwise.")
        parts.append(f"SameSite={normalized}")
    return "; ".join(parts)


def parse_accept(value: str | None) -> list[tuple[str, float]]:
    """Parse an ``Accept`` header into ``[(media_type, quality), ...]`` sorted by quality."""
    result: list[tuple[str, float]] = []
    if not value:
        return result
    for item in value.split(","):
        media, params = parse_options_header(item)
        if not media:
            continue
        try:
            quality = float(params.get("q", "1"))
        except ValueError:
            quality = 0.0
        result.append((media, max(0.0, min(quality, 1.0))))
    result.sort(key=lambda pair: pair[1], reverse=True)
    return result


def prefers_json(accept: str | None) -> bool:
    """Return ``True`` when the client ranks JSON strictly above HTML."""
    json_q = html_q = 0.0
    for media, quality in parse_accept(accept):
        if media in ("application/json", "application/problem+json") or media.endswith("+json"):
            json_q = max(json_q, quality)
        elif media in ("text/html", "application/xhtml+xml"):
            html_q = max(html_q, quality)
    return json_q > html_q


_FILENAME_STRIP_RE = re.compile(r"[^A-Za-z0-9_.-]")
_WINDOWS_DEVICE_NAMES = {
    "CON", "AUX", "COM1", "COM2", "COM3", "COM4", "LPT1", "LPT2", "LPT3", "PRN", "NUL",
}


def secure_filename(filename: str) -> str:
    """Return an ASCII-only filename that is safe to store on any filesystem.

    Path separators, leading dots and special characters are removed, so the result
    can never point outside the target directory. May return an empty string, which
    callers should treat as invalid.

    >>> secure_filename("../../etc/passwd")
    'etc_passwd'
    """
    normalized = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    for sep in ("/", "\\"):
        normalized = normalized.replace(sep, " ")
    cleaned = _FILENAME_STRIP_RE.sub("", "_".join(normalized.split())).strip("._")
    if cleaned.split(".")[0].upper() in _WINDOWS_DEVICE_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned
