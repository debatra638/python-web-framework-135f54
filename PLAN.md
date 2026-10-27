# Plan

1. [done] Environment inspected; package layout created (`myframework/`, `tests/`, `examples/`).
2. [partly done] HTTP primitives: `httputil.py` (status lines, header/cookie parsing, Set-Cookie builder, dates, Accept negotiation, `secure_filename`), `datastructures.py` (`MultiDict`, `Headers`, `UploadedFile`), `response.py` (`Response`, `JSONResponse`, `redirect`), `exceptions.py` (HTTP error hierarchy, `abort`). Remaining: `request.py` (environ parsing, query/form/JSON/multipart, size limits) and tests.
3. Routing engine (`routing.py`): converters, method matching, 404/405, trailing-slash redirect, `url_for`.
4. WSGI interface (`wsgi.py`, `app.py`): PEP 3333 callable, request context (`request` proxy), compliance tests with `wsgiref.validate`.
5. Development server (stdlib `wsgiref`/`http.server`) with auto-reload.
6. Middleware (WSGI + before/after hooks), template engine (`templates.py`: interpolation, inheritance, includes, auto-escaping — must provide `escape`, already imported by `response.py`/`exceptions.py`), static files (`static.py`, traversal-safe).
7. Configuration (`config.py`: env vars, TOML/py files), error handlers, logging, debug tracebacks, CLI (`cli.py`, `myframework run`).
8. Security tests and full pytest suite, incl. Gunicorn integration.
9. `pyproject.toml`, ruff/mypy config, build + install in a clean venv.
10. Examples and complete documentation.
