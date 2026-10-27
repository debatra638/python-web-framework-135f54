# myframework

An original, dependency-free Python web framework with native WSGI (PEP 3333) support and a Flask-like API.

**Status: early development.** The HTTP primitives (headers, cookies, responses, HTTP errors) exist; routing, the request object, the WSGI app, templates, static files, CLI and packaging are not yet built. See `PLAN.md` for the roadmap.

## Target API

```python
from myframework import App, request, Response

app = App()

@app.route("/users/<username>")
def user_profile(username):
    return f"<h1>Hello, {username}</h1>"

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
```

## Technologies
Python 3.10+ standard library only; pytest, ruff, mypy and Gunicorn for development/testing.

## Local development
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pytest ruff mypy gunicorn
```
(`pip install -e .` becomes available once `pyproject.toml` is added.)

## Roadmap
Request parsing, routing + `url_for`, WSGI app and request context, dev server with reload, middleware, template engine with auto-escaping and inheritance, safe static files, config system, CLI, tests, packaging, examples.
