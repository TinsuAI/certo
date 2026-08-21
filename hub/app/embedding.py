"""Embedding configuration + OpenRouter client (Feature 4 P5b).

2-tier config: global defaults in `hub.app_settings` keyed under
`embedding.*` + per-client overrides in `hub.clients.embedding_config`
(JSONB shallow merge over global at read time).

The OpenRouter API is OpenAI-compatible — POST /embeddings with
`{model, input: [text, ...]}`. Wrapper batches input within the
configured batch_size to avoid request-size limits.

Settings keys (in `hub.app_settings`):
- `embedding.openrouter_api_key`        — secret; required for live calls
- `embedding.openrouter_base_url`       — default https://openrouter.ai/api/v1
- `embedding.model`                     — default openai/text-embedding-3-small
- `embedding.dim`                       — default 1536
- `embedding.text_template`             — Python str.format() template
- `embedding.batch_size`                — texts per POST
- `embedding.score_threshold`           — cosine threshold for substitute
- `embedding.timeout_seconds`           — HTTP timeout
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Iterable

import urllib.request
import urllib.error

from hub.app import settings_store
from hub.app.database import connect


logger = logging.getLogger(__name__)


_DEFAULTS: dict[str, str] = {
    "embedding.openrouter_api_key":   "",
    "embedding.openrouter_base_url":  "https://openrouter.ai/api/v1",
    "embedding.model":                "openai/text-embedding-3-small",
    "embedding.dim":                  "1536",
    "embedding.text_template": (
        "{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}."
    ),
    "embedding.batch_size":           "100",
    "embedding.score_threshold":      "0.7",
    "embedding.timeout_seconds":      "30",
}


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    base_url: str
    model: str
    dim: int
    text_template: str
    batch_size: int
    score_threshold: float
    timeout_seconds: int

    @property
    def is_live(self) -> bool:
        return bool(self.api_key)


def _coerce_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def _coerce_float(s: str, default: float) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def get_global_config() -> EmbeddingConfig:
    """Read embedding settings from `hub.app_settings`, fall back to
    constants when keys are missing."""
    keys = list(_DEFAULTS.keys())
    raw = settings_store.get_many(keys)
    eff = {k: raw.get(k) or _DEFAULTS[k] for k in keys}
    return EmbeddingConfig(
        api_key=eff["embedding.openrouter_api_key"],
        base_url=eff["embedding.openrouter_base_url"],
        model=eff["embedding.model"],
        dim=_coerce_int(eff["embedding.dim"], 1536),
        text_template=eff["embedding.text_template"],
        batch_size=_coerce_int(eff["embedding.batch_size"], 100),
        score_threshold=_coerce_float(eff["embedding.score_threshold"], 0.7),
        timeout_seconds=_coerce_int(eff["embedding.timeout_seconds"], 30),
    )


def get_client_config(client_id: str) -> EmbeddingConfig:
    """Per-client override merged over global defaults."""
    base = get_global_config()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select embedding_config from hub.clients where client_id=%s",
            (client_id,),
        )
        row = cur.fetchone()
    overrides = (row[0] if row else None) or {}
    if not overrides:
        return base
    return EmbeddingConfig(
        api_key=overrides.get("openrouter_api_key", base.api_key),
        base_url=overrides.get("base_url", base.base_url),
        model=overrides.get("model", base.model),
        dim=int(overrides.get("dim", base.dim)),
        text_template=overrides.get("text_template", base.text_template),
        batch_size=int(overrides.get("batch_size", base.batch_size)),
        score_threshold=float(
            overrides.get("score_threshold", base.score_threshold)
        ),
        timeout_seconds=int(
            overrides.get("timeout_seconds", base.timeout_seconds)
        ),
    )


def save_global_config(values: dict[str, str], *, updated_by: str | None = None) -> None:
    """Persist embedding settings. Only keys starting with `embedding.`
    are accepted to keep the settings namespace clean."""
    cleaned: dict[str, str] = {}
    for k, v in values.items():
        if not k.startswith("embedding."):
            continue
        cleaned[k] = "" if v is None else str(v)
    if cleaned:
        settings_store.set_many(cleaned, updated_by=updated_by)


# ── text composition ──────────────────────────────────────────────


def build_embedding_text(material: dict, template: str) -> str:
    """Compose the text fed into the embedding model. Missing fields
    render as empty string (not 'None')."""
    return template.format(
        name=material.get("name") or "",
        material_code=material.get("material_code") or "",
        hs_code=material.get("hs_code") or "",
        unit=material.get("unit") or "",
        country_origin=material.get("country_origin") or "",
        category=material.get("category") or "",
        notes=material.get("notes") or "",
    )


def text_hash(text: str, model: str) -> str:
    """Stable hash combining text + model (so model swap forces re-embed)."""
    return hashlib.sha256(
        f"{model}\n{text}".encode("utf-8")
    ).hexdigest()


# ── OpenRouter client ────────────────────────────────────────────


class EmbeddingError(Exception):
    """Raised when the API call fails or returns malformed data."""


class OpenRouterClient:
    """Minimal embedding client using urllib (no extra dep). Mirrors the
    OpenAI embeddings API shape."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed up to `batch_size` texts in one request."""
        if not self.config.is_live:
            raise EmbeddingError(
                "no OpenRouter API key configured "
                "(set embedding.openrouter_api_key in app_settings)"
            )
        if not texts:
            return []
        payload = json.dumps({
            "model": self.config.model,
            "input": texts,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/embeddings",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://data-hub.local",
                "X-Title": "Data Hub embedding",
            },
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.config.timeout_seconds,
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(
                f"OpenRouter HTTP {exc.code}: {body[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EmbeddingError(
                f"OpenRouter request failed: {type(exc).__name__}: {exc}"
            ) from exc
        items = data.get("data") or []
        if len(items) != len(texts):
            raise EmbeddingError(
                f"embedding count mismatch: sent {len(texts)}, "
                f"received {len(items)}"
            )
        out: list[list[float]] = []
        for it in items:
            v = it.get("embedding")
            if not isinstance(v, list):
                raise EmbeddingError(
                    f"malformed embedding row: {str(it)[:200]}"
                )
            out.append([float(x) for x in v])
        return out

    def embed_chunked(
        self, texts: list[str], *, on_progress=None,
    ) -> list[list[float]]:
        """Embed any number of texts by chunking to batch_size."""
        out: list[list[float]] = []
        for i in range(0, len(texts), self.config.batch_size):
            chunk = texts[i:i + self.config.batch_size]
            t0 = time.monotonic()
            vectors = self.embed(chunk)
            out.extend(vectors)
            if on_progress is not None:
                on_progress(i + len(chunk), len(texts), time.monotonic() - t0)
        return out


def vector_to_pg(vec: list[float]) -> str:
    """pgvector accepts vectors as `[x,y,z]` text — psycopg's default
    adapter for `list` doesn't match the vector type, so we send text."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
