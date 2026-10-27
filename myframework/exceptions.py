"""Framework exceptions, including the HTTP error hierarchy used by :func:`abort`."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from .response import Response

__all__ = [
    "FrameworkError",
    "ConfigError",
    "RouteBuildError",
    "TemplateError",
    "TemplateNotFound",
    "TemplateSyntaxError",
    "HTTPException",
    "RequestRedirect",
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "MethodNotAllowed",
    "NotAcceptable",
    "Conflict",
    "Gone",
    "PayloadTooLarge",
    "UnsupportedMediaType",
    "UnprocessableEntity",
    "TooManyRequests",
    "InternalServerError",
    "NotImplementedHTTP",
    "ServiceUnavailable",
    "abort",
]


class FrameworkError(Exception):
    """Base class for programming and configuration errors raised by the framework."""


class ConfigError(FrameworkError):
    """Raised when configuration cannot be loaded or a value has the wrong type."""


class RouteBuildError(FrameworkError, LookupError):
    """Raised by ``url_for`` when no route can be built from the given endpoint and values."""


class TemplateError(FrameworkError):
    """Base class for template errors."""


class TemplateNotFound(TemplateError, LookupError):
    """Raised when a template cannot be located (or its name is unsafe)."""


class TemplateSyntaxError(TemplateError):
    """Raised when template source cannot be parsed. Includes the template name and line."""

    def __init__(self, message: str, name: str | None = None, lineno: int | None = None) -> None:
        location = ""
        if name or lineno:
            location = f" ({name or '<string>'}, line {lineno or '?'})"
        super().__init__(f"{message}{location}")
        self.name = name
        self.lineno = lineno


class HTTPException(Exception):
    """An exception that maps directly to an HTTP error response.

    Raise a subclass (``raise NotFound()``) or use :func:`abort` from a view, hook or
    middleware. The application turns it into a response, using a registered error
    handler when one exists.
    """

    code: int = 500
    description: str = "An error occurred while handling the request."

    def __init__(
        self,
        description: str | None = None,
        *,
        response: Response | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if description is not None:
            self.description = description
        self.response = response
        self.headers: dict[str, str] = dict(headers or {})
        super().__init__(f"{self.code} {self.name}: {self.description}")

    @property
    def name(self) -> str:
        """The standard reason phrase for :attr:`code`, e.g. ``"Not Found"``."""
        try:
            return HTTPStatus(self.code).phrase
        except ValueError:
            return "Unknown Error"

    def get_headers(self) -> dict[str, str]:
        """Extra headers to include in the default error response."""
        return dict(self.headers)

    def to_dict(self) -> dict[str, Any]:
        """The JSON body used when the client prefers JSON."""
        return {"error": {"code": self.code, "name": self.name, "description": self.description}}

    def get_response(self, *, as_json: bool = False) -> Response:
        """Build the default error response (HTML, or JSON when *as_json*)."""
        from .response import JSONResponse, Response
        from .templates import escape

        if self.response is not None:
            return self.response
        if as_json:
            return JSONResponse(self.to_dict(), self.code, self.get_headers())
        body = (
            "<!doctype html>\n<html lang=\"en\">\n<head><meta charset=\"utf-8\">"
            f"<title>{self.code} {escape(self.name)}</title></head>\n"
            f"<body>\n<h1>{escape(self.name)}</h1>\n<p>{escape(self.description)}</p>\n</body>\n</html>\n"
        )
        return Response(body, self.code, self.get_headers())


class RequestRedirect(HTTPException):
    """Raised by the router to redirect ``/path`` to ``/path/`` for rules with a trailing slash."""

    code = 308
    description = "This resource is available at a URL with a trailing slash."

    def __init__(self, new_url: str) -> None:
        super().__init__(headers={"Location": new_url})
        self.new_url = new_url


class BadRequest(HTTPException):
    code = 400
    description = "The browser (or proxy) sent a request that this server could not understand."


class Unauthorized(HTTPException):
    code = 401
    description = "The server could not verify that you are authorized to access this resource."


class Forbidden(HTTPException):
    code = 403
    description = "You don't have permission to access the requested resource."


class NotFound(HTTPException):
    code = 404
    description = "The requested URL was not found on the server."


class MethodNotAllowed(HTTPException):
    """405 response; carries the allowed methods and emits an ``Allow`` header."""

    code = 405
    description = "The method is not allowed for the requested URL."

    def __init__(self, valid_methods: list[str] | None = None, description: str | None = None) -> None:
        self.valid_methods = sorted(valid_methods or [])
        super().__init__(description)

    def get_headers(self) -> dict[str, str]:
        headers = super().get_headers()
        if self.valid_methods:
            headers["Allow"] = ", ".join(self.valid_methods)
        return headers


class NotAcceptable(HTTPException):
    code = 406
    description = "The resource cannot be returned in a format the client accepts."


class Conflict(HTTPException):
    code = 409
    description = "The request conflicts with the current state of the resource."


class Gone(HTTPException):
    code = 410
    description = "The requested resource is no longer available."


class PayloadTooLarge(HTTPException):
    code = 413
    description = "The data value transmitted exceeds the capacity limit."


class UnsupportedMediaType(HTTPException):
    code = 415
    description = "The server does not support the media type transmitted in the request."


class UnprocessableEntity(HTTPException):
    code = 422
    description = "The request was well-formed but contained semantic errors."


class TooManyRequests(HTTPException):
    code = 429
    description = "Too many requests were sent in a given amount of time."


class InternalServerError(HTTPException):
    code = 500
    description = (
        "The server encountered an internal error and was unable to complete your request."
    )


class NotImplementedHTTP(HTTPException):
    code = 501
    description = "The server does not support the action requested by the browser."


class ServiceUnavailable(HTTPException):
    code = 503
    description = "The server is temporarily unable to service your request."


_BY_CODE: dict[int, type[HTTPException]] = {
    cls.code: cls
    for cls in (
        BadRequest, Unauthorized, Forbidden, NotFound, MethodNotAllowed, NotAcceptable,
        Conflict, Gone, PayloadTooLarge, UnsupportedMediaType, UnprocessableEntity,
        TooManyRequests, InternalServerError, NotImplementedHTTP, ServiceUnavailable,
    )
}


def abort(status: int | Response, description: str | None = None, **kwargs: Any) -> NoReturn:
    """Stop handling the request by raising the :class:`HTTPException` for *status*.

    ``abort(404)`` raises :class:`NotFound`. Pass a :class:`Response` to send it as-is.
    Unknown 4xx/5xx codes produce a generic :class:`HTTPException` with that code.
    """
    from .response import Response

    if isinstance(status, Response):
        exc = HTTPException(response=status)
        exc.code = status.status_code
        raise exc
    cls = _BY_CODE.get(status)
    if cls is not None:
        raise cls(description=description, **kwargs)
    if not 400 <= status <= 599:
        raise ValueError(f"abort() expects a 4xx or 5xx status code, got {status}.")
    generic = HTTPException(description, **kwargs)
    generic.code = status
    raise generic
