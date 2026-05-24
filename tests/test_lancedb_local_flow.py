from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("pyarrow")

from desktop_app.lancedb_engine import LocalLanceDBEngine  # noqa: E402
from desktop_app.lancedb_ingestion import ingest_local_text_paths  # noqa: E402


class FlowKeywordEmbedder:
    def __init__(self):
        self.tokens = ["ev6", "battery", "diagnostic", "banana", "recipe"]

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


def test_local_text_ingestion_builds_searchable_parent_child_index(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    ev6_file = corpus_dir / "ev6_service.txt"
    noise_file = corpus_dir / "banana_recipe.md"
    unsupported_file = corpus_dir / "ignored.png"

    ev6_file.write_text(
        "EV6 high voltage battery diagnostic notes and charging service procedure.",
        encoding="utf-8",
    )
    noise_file.write_text("Banana bread recipe with cinnamon and walnuts.", encoding="utf-8")
    unsupported_file.write_text("EV6 text in an unsupported file should not be indexed.", encoding="utf-8")

    with LocalLanceDBEngine(tmp_path / "lancedb", embedder=FlowKeywordEmbedder()) as engine:
        ingest_result = ingest_local_text_paths(engine, [corpus_dir], chunk_size=400)
        search_results, telemetry = engine.search_parent_child(
            "EV6 battery diagnostic",
            parent_limit=1,
            child_limit=3,
        )

    assert ingest_result.indexed_documents == 2
    assert ingest_result.stats.source_count == 2
    assert [skipped.reason for skipped in ingest_result.skipped_files] == ["unsupported_extension"]
    assert search_results
    assert {Path(result.source_uri).name for result in search_results} == {"ev6_service.txt"}
    assert Path(telemetry.matched_parents[0]).name == "ev6_service.txt"
