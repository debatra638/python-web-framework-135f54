"""The :class:`Response` object and helpers that create common responses."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .datastructures import Headers
from .httputil import dump_set_cookie, status_line

if TYPE_CHECKING:
    from .wsgi import StartResponse, WSGIEnvironment

__all__ = ["Response", "JSONResponse", "redirect", "json_dumps"]

HeadersLike = Headers | Mapping[str, str] | Iterable[tuple[str, str]]
BodyLike = str | bytes | bytearray | Iterable[bytes] | Iterable[str] | None

_NO_BODY_STATUSES = frozenset({204, 304})


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, (UUID, Decimal)):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def json_dumps(data: Any, *, indent: int | None = None, sort_keys: bool = False) -> str:
    """Serialize *data* to JSON, also handling datetimes, UUIDs, Decimals, sets and dataclasses."""
    separators = None if indent is not None else (",", ":")
    return json.dumps(data, default=_json_default, indent=indent, sort_keys=sort_keys, separators=separators)


class Response:
    """An HTTP response, which is also a WSGI application.

    :param body: ``str`` (encoded as UTF-8), ``bytes``, or an iterable of ``bytes``/``str``
        chunks for a streamed response.
    :param status: integer status code or a full status string such as ``"201 Created"``.
    :param headers: initial headers as a mapping, list of pairs or :class:`Headers`.
    :param mimetype: media type without parameters; ``charset=utf-8`` is appended for text types.
    :param content_type: the full ``Content-Type`` value; overrides *mimetype*.
    """

    default_mimetype = "text/html"
    charset = "utf-8"

    def __init__(
        self,
        body: BodyLike = None,
        status: int | str = 200,
        headers: HeadersLike | None = None,
        *,
        mimetype: str | None = None,
        content_type: str | None = None,
    ) -> None:
        self.headers = Headers(headers)
        self.status = status  # type: ignore[assignment]
        self._on_close: list[Callable[[], None]] = []
        self._body: bytes | None = None
        self._iterable: Iterable[bytes | str] | None = None
        if content_type is None and "Content-Type" not in self.headers:
            mimetype = mimetype or self.default_mimetype
            content_type = mimetype
            if mimetype.startswith("text/") or mimetype in ("application/json", "application/xml"):
                content_type = f"{mimetype}; charset={self.charset}"
        if content_type is not None:
            self.headers.set("Content-Type", content_type)
        self.set_data(body)

    # -- status -------------------------------------------------------------------------
    @property
    def status(self) -> str:
        """The full status line, e.g. ``"200 OK"``. Assign an int or a status string."""
        return self._status

    @status.setter
    def status(self, value: int | str) -> None:
        if isinstance(value, int):
            self._status_code = value
            self._status = status_line(value)
            return
        code, _, reason = str(value).strip().partition(" ")
        if not code.isdigit() or len(code) != 3:
            raise ValueError(f"Invalid status {value!r}; expected an int or a string like '404 Not Found'.")
        self._status_code = int(code)
        self._status = f"{code} {reason}" if reason else status_line(int(code))

    @property
    def status_code(self) -> int:
        """The integer status code."""
        return self._status_code

    @status_code.setter
    def status_code(self, value: int) -> None:
        self.status = value

    # -- body ---------------------------------------------------------------------------
    def set_data(self, body: BodyLike) -> None:
        """Replace the body. ``str`` and ``bytes`` set ``Content-Length`` automatically."""
        self._iterable = None
        if body is None:
            self._body = b""
        elif isinstance(body, str):
            self._body = body.encode(self.charset)
        elif isinstance(body, (bytes, bytearray)):
            self._body = bytes(body)
        else:
            self._body = None
            self._iterable = body
            self.headers.remove("Content-Length")
            return
        self.headers.set("Content-Length", str(len(self._body)))

    @property
    def is_streamed(self) -> bool:
        """``True`` when the body is an iterable whose length is not known in advance."""
        return self._iterable is not None

    def iter_encoded(self) -> Iterator[bytes]:
        """Yield the body as ``bytes`` chunks, encoding ``str`` chunks on the fly."""
        if self._body is not None:
            if self._body:
                yield self._body
            return
        for chunk in self._iterable or ():
            if isinstance(chunk, str):
                chunk = chunk.encode(self.charset)
            elif not isinstance(chunk, (bytes, bytearray)):
                raise TypeError(f"Response iterables must yield bytes or str, got {type(chunk).__name__}.")
            if chunk:
                yield bytes(chunk)

    @property
    def data(self) -> bytes:
        """The full body as bytes. Reading this consumes and buffers a streamed body."""
        if self._body is None:
            self.set_data(b"".join(self.iter_encoded()))
        return self._body or b""

    @data.setter
    def data(self, value: str | bytes) -> None:
        self.set_data(value)

    @property
    def text(self) -> str:
        """The body decoded with the response charset."""
        return self.data.decode(self.charset, errors="replace")

    # -- header shortcuts ---------------------------------------------------------------
    @property
    def content_type(self) -> str | None:
        return self.headers.get("Content-Type")

    @content_type.setter
    def content_type(self, value: str) -> None:
        self.headers.set("Content-Type", value)

    @property
    def mimetype(self) -> str | None:
        """The media type without parameters, e.g. ``"text/html"``."""
        value = self.content_type
        return value.split(";", 1)[0].strip().lower() if value else None

    @property
    def content_length(self) -> int | None:
        value = self.headers.get("Content-Length")
        return int(value) if value and value.isdigit() else None

    @property
    def location(self) -> str | None:
        return self.headers.get("Location")

    # -- cookies ------------------------------------------------------------------------
    def set_cookie(
        self,
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
    ) -> None:
        """Add a ``Set-Cookie`` header.

        Defaults are deliberately conservative: ``HttpOnly`` and ``SameSite=Lax`` are on.
        Pass ``secure=True`` when the site is served over HTTPS (recommended in production).
        """
        self.headers.add(
            "Set-Cookie",
            dump_set_cookie(
                name,
                value,
                max_age=max_age,
                expires=expires,
                path=path,
                domain=domain,
                secure=secure,
                httponly=httponly,
                samesite=samesite,
            ),
        )

    def delete_cookie(
        self,
        name: str,
        *,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = True,
        samesite: str | None = "Lax",
    ) -> None:
        """Expire a cookie. *path* and *domain* must match the values used to set it."""
        self.set_cookie(
            name,
            "",
            max_age=0,
            expires=0,
            path=path,
            domain=domain,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
        )

    # -- lifecycle ----------------------------------------------------------------------
    def call_on_close(self, func: Callable[[], None]) -> Callable[[], None]:
        """Register *func* to run when the server closes the response iterable."""
        self._on_close.append(func)
        return func

    def close(self) -> None:
        """Close the body iterable (if it supports it) and run ``call_on_close`` callbacks."""
        close = getattr(self._iterable, "close", None)
        try:
            if callable(close):
                close()
        finally:
            for func in self._on_close:
                func()

    # -- WSGI ---------------------------------------------------------------------------
    def get_wsgi_headers(self, environ: WSGIEnvironment) -> Headers:
        """Return the headers to send, adjusted for the request (e.g. no body for 204/304)."""
        headers = self.headers.copy()
        if self.status_code in _NO_BODY_STATUSES or 100 <= self.status_code < 200:
            headers.remove("Content-Type")
            headers.remove("Content-Length")
        return headers

    def get_app_iter(self, environ: WSGIEnvironment) -> Iterable[bytes]:
        """Return the iterable of body chunks to hand back to the WSGI server."""
        if (
            environ.get("REQUEST_METHOD") == "HEAD"
            or self.status_code in _NO_BODY_STATUSES
            or 100 <= self.status_code < 200
        ):
            return []
        return self.iter_encoded()

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        """Run this response as a WSGI application (PEP 3333)."""
        headers = self.get_wsgi_headers(environ).to_wsgi_list()
        app_iter = self.get_app_iter(environ)
        start_response(self.status, headers)
        return app_iter

    def __repr__(self) -> str:
        size = f"{len(self._body)} bytes" if self._body is not None else "streamed"
        return f"<{type(self).__name__} [{self.status}] {size}>"


class JSONResponse(Response):
    """A response whose body is *data* serialized as JSON."""

    default_mimetype = "application/json"

    def __init__(
        self,
        data: Any,
        status: int | str = 200,
        headers: HeadersLike | None = None,
        *,
        indent: int | None = None,
        sort_keys: bool = False,
    ) -> None:
        super().__init__(json_dumps(data, indent=indent, sort_keys=sort_keys), status, headers)


def redirect(location: str, code: int = 302) -> Response:
    """Return a redirect response to *location*.

    Use 303 after a successful form POST, and 307/308 to preserve the request method.
    """
    if code not in (301, 302, 303, 307, 308):
        raise ValueError(f"{code} is not a redirect status code.")
    from .templates import escape

    safe = escape(location)
    body = f'<!doctype html>\n<title>Redirecting</title>\n<p>Redirecting to <a href="{safe}">{safe}</a>.</p>\n'
    return Response(body, code, {"Location": location})
