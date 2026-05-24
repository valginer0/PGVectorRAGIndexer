from __future__ import annotations

from pathlib import Path

import pytest

from desktop_app.lancedb_engine import IngestionStats, LocalDocument
from desktop_app.lancedb_ingestion import (
    LocalTextIngestionError,
    build_local_text_corpus,
    ingest_local_text_paths,
)


class FakeLanceDBEngine:
    def __init__(self):
        self.documents: list[LocalDocument] = []
        self.kwargs = {}

    def ingest_documents(self, documents, **kwargs):
        self.documents = list(documents)
        self.kwargs = kwargs
        return IngestionStats(
            source_count=len(self.documents),
            chunk_count=len(self.documents) * 2,
            db_path="/tmp/fake-lancedb",
        )


def test_build_local_text_corpus_recurses_and_skips_non_text(tmp_path):
    root = tmp_path / "corpus"
    nested = root / "nested"
    nested.mkdir(parents=True)
    good_txt = root / "ev6.txt"
    good_md = nested / "notes.md"
    blank = root / "blank.txt"
    unsupported = root / "image.png"
    temp_office = root / "~$draft.txt"

    good_txt.write_text("EV6 battery notes", encoding="utf-8")
    good_md.write_text("# Charging\nEV6 charging context", encoding="utf-8")
    blank.write_text(" \n ", encoding="utf-8")
    unsupported.write_text("not really an image", encoding="utf-8")
    temp_office.write_text("office lock file", encoding="utf-8")

    corpus = build_local_text_corpus([root])

    assert [Path(doc.source_uri).name for doc in corpus.documents] == ["ev6.txt", "notes.md"]
    assert corpus.document_count == 2
    assert corpus.skipped_count == 3
    assert {skipped.reason for skipped in corpus.skipped_files} == {
        "empty_text",
        "temporary_office_file",
        "unsupported_extension",
    }
    assert corpus.documents[0].metadata["ingestion_source"] == "local_text_adapter"


def test_build_local_text_corpus_reads_windows_encoding(tmp_path):
    path = tmp_path / "windows.md"
    path.write_bytes("caf\xe9 EV6".encode("cp1252"))

    corpus = build_local_text_corpus([path])

    assert corpus.documents[0].text == "café EV6"
    assert corpus.documents[0].metadata["encoding"] == "cp1252"


def test_build_local_text_corpus_can_disable_recursion(tmp_path):
    root = tmp_path / "corpus"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "top.txt").write_text("top", encoding="utf-8")
    (nested / "nested.txt").write_text("nested", encoding="utf-8")

    corpus = build_local_text_corpus([root], recursive=False)

    assert [Path(doc.source_uri).name for doc in corpus.documents] == ["top.txt"]


def test_ingest_local_text_paths_delegates_to_engine(tmp_path):
    path = tmp_path / "ev6.txt"
    path.write_text("EV6 battery diagnostic", encoding="utf-8")
    engine = FakeLanceDBEngine()

    result = ingest_local_text_paths(
        engine,
        [path],
        chunk_size=20,
        chunk_overlap=2,
    )

    assert result.indexed_documents == 1
    assert result.stats.source_count == 1
    assert result.stats.chunk_count == 2
    assert engine.documents[0].text == "EV6 battery diagnostic"
    assert engine.kwargs == {
        "chunk_size": 20,
        "chunk_overlap": 2,
        "mode": "overwrite",
    }
    assert result.to_dict()["db_path"] == "/tmp/fake-lancedb"


def test_ingest_local_text_paths_rejects_empty_corpus(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text(" ", encoding="utf-8")

    with pytest.raises(LocalTextIngestionError, match="no supported"):
        ingest_local_text_paths(FakeLanceDBEngine(), [path])
