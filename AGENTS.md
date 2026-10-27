# AGENTS.md

Python web framework package in `myframework/`; follow `PLAN.md` for remaining milestones.

## Architecture (so far)
- `httputil.py` – pure HTTP helpers, no framework imports.
- `datastructures.py` – `MultiDict`, `Headers` (validates against header injection), `UploadedFile`.
- `response.py` – `Response` is itself a WSGI app; handles HEAD/204/304 body stripping.
- `exceptions.py` – `HTTPException` hierarchy renders HTML or JSON; `abort()`.

## Conventions
- Standard library only at runtime; `from __future__ import annotations`, full type hints, docstrings.
- Secure defaults (HttpOnly + SameSite=Lax cookies, escaping everywhere).
- `response.py` and `exceptions.py` lazily import `escape` from `myframework/templates.py`, which must be created next.
- Dev tooling was used from a venv outside the repo; never commit venvs or build artefacts.
