# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin

# libreoffice-calc renders the stored declaration .xls (the ECUS print
# form) to the print-standard PDF for the declarations download.pdf merge
# endpoint. --no-install-recommends skips the JRE (Calc→PDF export does
# not need Java). Liberation/DejaVu fonts give faithful Vietnamese glyphs
# + Arial/Times metric compatibility for the official tờ khai layout.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates \
        libreoffice-calc \
        fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Release identity baked at build time. CI passes these; app/version.py
# reads them (precedence: env > pyproject+git > unknown) and the UI shows
# them in the footer badge + /version endpoint.
ARG VERSION=0.0.0
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV DATA_HUB_VERSION=$VERSION \
    DATA_HUB_GIT_SHA=$GIT_SHA \
    DATA_HUB_BUILD_TIME=$BUILD_TIME

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY db ./db
COPY scripts ./scripts
COPY data ./data
COPY CHANGELOG.md ./

EXPOSE 8754

CMD ["uvicorn", "hub.app.main:app", \
     "--host", "0.0.0.0", "--port", "8754", \
     "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
