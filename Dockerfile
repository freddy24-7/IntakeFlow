# One image for the web application and the worker. The command decides which runs.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.22 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/.venv/bin:$PATH"
WORKDIR /srv

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --python-preference only-system

COPY alembic.ini ./
COPY migrations migrations
COPY prompts prompts
COPY reports/extraction-latest.json reports/extraction-latest.json
COPY app app
RUN uv sync --locked --no-dev --python-preference only-system

RUN useradd --system --uid 10001 --home-dir /srv intakeflow && chown -R intakeflow /srv
USER intakeflow
EXPOSE 8000

# The web application applies migrations on start. The worker overrides this command.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
