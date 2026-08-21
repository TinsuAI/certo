"""Tests for app.embedding."""
from __future__ import annotations

import pytest

from app import embedding


def test_get_global_config_uses_defaults_when_unset():
    c = embedding.get_global_config()
    assert c.model.startswith("openai/") or c.model
    assert c.dim == 1536
    assert c.batch_size > 0
    assert 0 <= c.score_threshold <= 1


def test_save_global_config_filters_namespace():
    embedding.save_global_config({
        "embedding.model": "test/dummy-model",
        "unrelated.key": "should-not-write",
    })
    c = embedding.get_global_config()
    assert c.model == "test/dummy-model"
    # restore default
    embedding.save_global_config({
        "embedding.model": "openai/text-embedding-3-small",
    })


def test_build_embedding_text_default_template():
    text = embedding.build_embedding_text(
        {"name": "Plastic bottle", "hs_code": "39233010",
         "unit": "pcs", "country_origin": "VN"},
        "{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.",
    )
    assert text == "Plastic bottle. HS=39233010. UoM=pcs. Origin=VN."


def test_build_embedding_text_missing_fields():
    text = embedding.build_embedding_text(
        {"name": "Bracket"},
        "{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.",
    )
    assert text == "Bracket. HS=. UoM=. Origin=."


def test_text_hash_stable():
    h1 = embedding.text_hash("hello", "model-a")
    h2 = embedding.text_hash("hello", "model-a")
    assert h1 == h2


def test_text_hash_changes_with_model():
    h1 = embedding.text_hash("hello", "model-a")
    h2 = embedding.text_hash("hello", "model-b")
    assert h1 != h2


def test_text_hash_changes_with_text():
    h1 = embedding.text_hash("hello", "m")
    h2 = embedding.text_hash("world", "m")
    assert h1 != h2


def test_openrouter_client_no_key_raises():
    cfg = embedding.EmbeddingConfig(
        api_key="", base_url="x", model="m", dim=1536,
        text_template="t", batch_size=10,
        score_threshold=0.7, timeout_seconds=30,
    )
    client = embedding.OpenRouterClient(cfg)
    with pytest.raises(embedding.EmbeddingError, match="no OpenRouter API key"):
        client.embed(["test"])


def test_vector_to_pg_format():
    assert embedding.vector_to_pg([1.0, 2.5, -0.5]) == "[1.0,2.5,-0.5]"
    assert embedding.vector_to_pg([]) == "[]"
