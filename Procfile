# Render (and similar PaaS hosts) default-guess "gunicorn app:app" for any
# Python web service -- wrong here, since this is an ASGI app (FastAPI)
# meant to run under uvicorn, not the WSGI-style gunicorn default. This
# file overrides that guess with the correct command.
#
# --app-dir backend: lets this run correctly whether Render's "Root
# Directory" setting is the repo root or backend/ itself, without needing
# a `cd` first.
web: uvicorn app:app --host 0.0.0.0 --port $PORT --app-dir backend
