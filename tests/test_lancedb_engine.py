from __future__ import annotations

import math

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("pyarrow")

from desktop_app.lancedb_engine import (  # noqa: E402
    CHUNK_TABLE,
    EmbeddingModelError,
    LocalDocument,
    LocalLanceDBEngine,
    split_text,
)


class KeywordEmbedder:
    def __init__(self):
        self.tokens = ["battery", "diagnostic", "ev6", "laptop", "banana", "charging"]

    @property
    def dimension(self) -> int:
        return len(self.tokens)

    def encode(self, text: str) -> list[float]:
        lowered = (text or "").lower()
        values = [float(lowered.count(token)) for token in self.tokens]
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            values[0] = 0.01
            norm = 0.01
        return [value / norm for value in values]


class ZeroVectorEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    def encode(self, text: str) -> list[float]:
        return [0.0, 0.0, 0.0]


class AxisEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    def encode(self, text: str) -> list[float]:
        return [0.0, 1.0] if "beta" in (text or "").lower() else [1.0, 0.0]


def sample_documents() -> list[LocalDocument]:
    return [
        LocalDocument(
            source_uri="docs/ev6_service.txt",
            text=(
                "EV6 charging service notes. High voltage battery diagnostic "
                "cell balancing procedure for the electric vehicle pack."
            ),
        ),
        LocalDocument(
            source_uri="docs/laptop_battery.txt",
            text=(
                "Laptop battery diagnostic replacement procedure. UPS battery "
                "storage and desktop power troubleshooting."
            ),
        ),
        LocalDocument(
            source_uri="docs/banana_recipe.txt",
            text="Banana bread recipe with walnuts, flour, sugar, and cinnamon.",
        ),
    ]


def test_ingests_reopens_and_searches_parent_child(tmp_path):
    with LocalLanceDBEngine(tmp_path / "lancedb", embedder=KeywordEmbedder()) as engine:
        stats = engine.ingest_documents(sample_documents(), chunk_size=400)

        assert stats.source_count == 3
        assert stats.chunk_count == 3
        assert engine.is_indexed()

    reopened = LocalLanceDBEngine(tmp_path / "lancedb", embedder=KeywordEmbedder())
    assert reopened.is_indexed()

    results, telemetry = reopened.search_parent_child(
        "EV6 battery diagnostic",
        parent_limit=1,
        child_limit=3,
    )

    assert results
    assert results[0].score_label.startswith("Cosine similarity:")
    assert telemetry.query_type == "parent_child"
    assert telemetry.matched_parents == ["docs/ev6_service.txt"]
    assert telemetry.matched_parent_details[0]["rank"] == 1
    assert telemetry.matched_parent_details[0]["source_uri"] == "docs/ev6_service.txt"
    assert telemetry.matched_parent_details[0]["fts_score"] > 0
    assert telemetry.to_dict()["matched_parent_details"] == telemetry.matched_parent_details
    assert {result.source_uri for result in results} == {"docs/ev6_service.txt"}


def test_parent_child_scopes_away_flat_global_noise(tmp_path):
    engine = LocalLanceDBEngine(tmp_path / "lancedb", embedder=KeywordEmbedder())
    engine.ingest_documents(sample_documents(), chunk_size=400)

    flat_results, _ = engine.search_flat_global_hybrid("EV6 battery diagnostic", top_k=3)
    parent_results, telemetry = engine.search_parent_child(
        "EV6 battery diagnostic",
        parent_limit=1,
        child_limit=3,
    )

    assert any(result.source_uri == "docs/laptop_battery.txt" for result in flat_results)
    assert telemetry.matched_parents == ["docs/ev6_service.txt"]
    assert parent_results
    assert all(result.source_uri == "docs/ev6_service.txt" for result in parent_results)


def test_vector_search_uses_cosine_metric(tmp_path):
    engine = LocalLanceDBEngine(tmp_path / "lancedb", embedder=AxisEmbedder())
    engine.ingest_documents(
        [
            LocalDocument(source_uri="docs/alpha.txt", text="alpha"),
            LocalDocument(source_uri="docs/beta.txt", text="beta"),
        ],
        chunk_size=400,
    )

    rows = (
        engine._vector_search(engine.db.open_table(CHUNK_TABLE), [1.0, 0.0])
        .limit(2)
        .to_arrow()
        .to_pylist()
    )
    distances = {row["source_uri"]: row["_distance"] for row in rows}

    assert distances["docs/alpha.txt"] == pytest.approx(0.0)
    assert distances["docs/beta.txt"] == pytest.approx(1.0)


def test_zero_vector_embeddings_are_rejected(tmp_path):
    engine = LocalLanceDBEngine(tmp_path / "lancedb", embedder=ZeroVectorEmbedder())

    with pytest.raises(EmbeddingModelError, match="all-zero vector"):
        engine.ingest_documents([LocalDocument(source_uri="docs/a.txt", text="EV6 battery")])


def test_empty_document_text_is_rejected_before_embedding(tmp_path):
    engine = LocalLanceDBEngine(tmp_path / "lancedb", embedder=ZeroVectorEmbedder())

    with pytest.raises(ValueError, match="document text"):
        engine.ingest_documents([LocalDocument(source_uri="docs/blank.txt", text="  \n ")])


def test_split_text_uses_stable_overlap():
    chunks = split_text("abcdefghij", chunk_size=4, chunk_overlap=1)

    assert chunks == ["abcd", "defg", "ghij"]


def test_split_text_rejects_invalid_overlap():
    with pytest.raises(ValueError, match="chunk_overlap"):
        split_text("abc", chunk_size=3, chunk_overlap=3)


def test_search_rejects_empty_query(tmp_path):
    engine = LocalLanceDBEngine(tmp_path / "lancedb", embedder=KeywordEmbedder())
    engine.ingest_documents(sample_documents(), chunk_size=400)

    with pytest.raises(ValueError, match="query"):
        engine.search_parent_child(" ")
