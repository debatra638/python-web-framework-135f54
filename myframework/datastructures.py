"""Container types used by requests and responses."""

from __future__ import annotations

import io
import os
import shutil
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import IO, Any, Generic, TypeVar, overload

from .httputil import is_token

__all__ = ["MultiDict", "Headers", "UploadedFile"]

V = TypeVar("V")
T = TypeVar("T")
_MISSING: Any = object()


class MultiDict(Mapping[str, V], Generic[V]):
    """A read-mostly mapping that can hold several values per key.

    Indexing returns the *first* value for a key, which matches how most query strings
    and forms are used. Use :meth:`getlist` to get every value.

    >>> args = MultiDict([("tag", "a"), ("tag", "b")])
    >>> args["tag"], args.getlist("tag")
    ('a', ['a', 'b'])
    """

    def __init__(self, items: Iterable[tuple[str, V]] | Mapping[str, V] | None = None) -> None:
        self._data: dict[str, list[V]] = {}
        if isinstance(items, Mapping):
            items = items.items()
        for key, value in items or ():
            self.add(key, value)

    def add(self, key: str, value: V) -> None:
        """Append *value* to the list of values for *key*."""
        self._data.setdefault(key, []).append(value)

    def __getitem__(self, key: str) -> V:
        try:
            return self._data[key][0]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.items(multi=True))!r})"

    @overload
    def get(self, key: str, /) -> V | None: ...
    @overload
    def get(self, key: str, /, default: V | T) -> V | T: ...
    @overload
    def get(self, key: str, /, default: T, type: Callable[[V], T]) -> T: ...
    @overload
    def get(self, key: str, /, *, type: Callable[[V], T]) -> T | None: ...

    def get(self, key: str, /, default: Any = None, type: Callable[[V], Any] | None = None) -> Any:
        """Return the first value for *key*, optionally converted with *type*.

        If the conversion raises :class:`ValueError` or :class:`TypeError` the
        *default* is returned instead, so ``request.args.get("page", 1, type=int)``
        never fails on bad input.
        """
        try:
            value = self[key]
        except KeyError:
            return default
        if type is None:
            return value
        try:
            return type(value)
        except (ValueError, TypeError):
            return default

    def getlist(self, key: str, type: Callable[[V], T] | None = None) -> list[Any]:
        """Return every value for *key* (an empty list if absent).

        With *type*, values that fail to convert are skipped.
        """
        values = list(self._data.get(key, ()))
        if type is None:
            return values
        converted: list[T] = []
        for value in values:
            try:
                converted.append(type(value))
            except (ValueError, TypeError):
                continue
        return converted

    def items(self, multi: bool = False) -> Any:  # type: ignore[override]
        """Return ``(key, first_value)`` pairs, or every pair when *multi* is true."""
        if multi:
            return [(key, value) for key, values in self._data.items() for value in values]
        return [(key, values[0]) for key, values in self._data.items()]

    def to_dict(self, flat: bool = True) -> dict[str, Any]:
        """Return a plain dict of first values, or of value lists when *flat* is false."""
        if flat:
            return {key: values[0] for key, values in self._data.items()}
        return {key: list(values) for key, values in self._data.items()}


def _validate_header(name: str, value: str) -> None:
    if not is_token(name):
        raise ValueError(f"Invalid header name {name!r}.")
    if any(c in value for c in "\r\n\x00"):
        raise ValueError(
            f"Header {name!r} contains a newline or NUL character; this would allow header injection."
        )


class Headers:
    """An ordered, case-insensitive, multi-valued collection of HTTP headers.

    Assigning with ``headers[name] = value`` replaces existing values; :meth:`add`
    appends. Names and values are validated so a stray ``\\r\\n`` can never inject
    extra headers into a response.
    """

    def __init__(self, items: Mapping[str, str] | Iterable[tuple[str, str]] | Headers | None = None) -> None:
        self._items: list[tuple[str, str]] = []
        if items is None:
            return
        if isinstance(items, Headers):
            pairs: Iterable[tuple[str, str]] = items.items()
        elif isinstance(items, Mapping):
            pairs = items.items()
        else:
            pairs = items
        for name, value in pairs:
            self.add(name, value)

    def add(self, name: str, value: Any) -> None:
        """Append a header without removing existing headers of the same name."""
        value = str(value)
        _validate_header(name, value)
        self._items.append((name, value))

    def set(self, name: str, value: Any) -> None:
        """Replace all headers named *name* with a single value."""
        value = str(value)
        _validate_header(name, value)
        lower = name.lower()
        self._items = [(k, v) for k, v in self._items if k.lower() != lower]
        self._items.append((name, value))

    def setdefault(self, name: str, value: Any) -> str:
        """Set *name* to *value* only if it is not already present; return the effective value."""
        existing = self.get(name)
        if existing is not None:
            return existing
        self.set(name, value)
        return str(value)

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return the first value for *name* (case-insensitive) or *default*."""
        lower = name.lower()
        for key, value in self._items:
            if key.lower() == lower:
                return value
        return default

    def getlist(self, name: str) -> list[str]:
        """Return every value for *name*."""
        lower = name.lower()
        return [value for key, value in self._items if key.lower() == lower]

    def remove(self, name: str) -> None:
        """Remove every header named *name*; missing names are ignored."""
        lower = name.lower()
        self._items = [(k, v) for k, v in self._items if k.lower() != lower]

    def items(self) -> list[tuple[str, str]]:
        """Return all ``(name, value)`` pairs in insertion order."""
        return list(self._items)

    def keys(self) -> list[str]:
        return [key for key, _ in self._items]

    def __getitem__(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def __setitem__(self, name: str, value: Any) -> None:
        self.set(name, value)

    def __delitem__(self, name: str) -> None:
        if name not in self:
            raise KeyError(name)
        self.remove(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.get(name) is not None

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(list(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Headers):
            return [(k.lower(), v) for k, v in self._items] == [(k.lower(), v) for k, v in other._items]
        return NotImplemented

    def __repr__(self) -> str:
        return f"Headers({self._items!r})"

    def copy(self) -> Headers:
        return Headers(self)

    def to_wsgi_list(self) -> list[tuple[str, str]]:
        """Return headers as the list of native-string tuples PEP 3333 requires.

        Values must be encodable as ISO-8859-1; non-Latin-1 text raises a clear error.
        """
        result: list[tuple[str, str]] = []
        for name, value in self._items:
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                raise ValueError(
                    f"Header {name!r} contains characters outside ISO-8859-1; "
                    "percent-encode or RFC 2047-encode the value."
                ) from None
            result.append((name, value))
        return result


class UploadedFile:
    """A file received in a ``multipart/form-data`` request.

    The file is held in memory (uploads are bounded by ``MAX_CONTENT_LENGTH``).
    ``filename`` is exactly what the client sent and must not be trusted as a path:
    use :func:`myframework.secure_filename` before saving under that name.
    """

    def __init__(
        self,
        data: bytes,
        *,
        name: str,
        filename: str,
        content_type: str = "application/octet-stream",
        headers: Headers | None = None,
    ) -> None:
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.headers = headers or Headers()
        self._data = data
        self.stream: IO[bytes] = io.BytesIO(data)

    @property
    def size(self) -> int:
        """Size of the uploaded file in bytes."""
        return len(self._data)

    def read(self, size: int = -1) -> bytes:
        """Read from the file stream."""
        return self.stream.read(size)

    def save(self, destination: str | os.PathLike[str] | IO[bytes]) -> None:
        """Write the uploaded content to a path or a binary file object."""
        self.stream.seek(0)
        if isinstance(destination, (str, os.PathLike)):
            with Path(destination).open("wb") as fh:
                shutil.copyfileobj(self.stream, fh)
        else:
            shutil.copyfileobj(self.stream, destination)

    def __repr__(self) -> str:
        return f"<UploadedFile {self.filename!r} ({self.content_type}, {self.size} bytes)>"
