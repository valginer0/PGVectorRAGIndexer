import subprocess
from pathlib import Path

from langchain_core.documents import Document

from document_processor import OfficeDocumentLoader, LoaderError


def test_convert_doc_to_docx_uses_libreoffice(monkeypatch, tmp_path):
    doc_path = tmp_path / "sample.doc"
    doc_path.write_text("dummy content")

    fake_binary = tmp_path / "soffice.exe"
    fake_binary.write_text("")
    monkeypatch.setenv("LIBREOFFICE_PATH", str(fake_binary))

    def fake_run(cmd, check, stdout, stderr):
        output_dir = Path(cmd[cmd.index("--outdir") + 1])
        expected = output_dir / (Path(cmd[-1]).stem + ".docx")
        expected.write_text("converted")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    loader = OfficeDocumentLoader()
    converted_path = loader._convert_doc_to_docx(str(doc_path))

    assert converted_path is not None
    assert converted_path.suffix == ".docx"
    assert Path(converted_path).exists()


def test_load_word_document_converts_legacy_doc(monkeypatch, tmp_path):
    legacy_path = tmp_path / "legacy.doc"
    legacy_path.write_text("legacy")

    loader = OfficeDocumentLoader()

    converted_path = tmp_path / "legacy.docx"
    converted_path.write_text("converted text")

    monkeypatch.setattr(
        loader,
        "_convert_doc_to_docx",
        lambda source: converted_path
    )

    call_count = {"count": 0}

    def fake_extract(path, original_source=None):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise LoaderError("cannot open original doc")
        assert path == str(converted_path)
        return [Document(page_content="converted text", metadata={"source": original_source})]

    monkeypatch.setattr(loader, "_extract_docx_documents", fake_extract)

    documents = loader._load_word_document(str(legacy_path))

    assert len(documents) == 1
    assert documents[0].page_content == "converted text"
    assert call_count["count"] == 2


def test_load_doc_uses_word_loader(monkeypatch):
    loader = OfficeDocumentLoader()

    capture = {}

    def fake_word_loader(source_uri, original_source=None):
        capture["source"] = source_uri
        capture["original"] = original_source
        return [Document(page_content="converted", metadata={"source": source_uri})]

    monkeypatch.setattr(loader, "_load_word_document", fake_word_loader)

    result = loader.load("sample.doc")

    assert capture == {"source": "sample.doc", "original": None}
    assert len(result) == 1
    assert result[0].page_content == "converted"


def test_load_docx_uses_word_loader(monkeypatch):
    loader = OfficeDocumentLoader()

    capture = {}

    def fake_word_loader(source_uri, original_source=None):
        capture["source"] = source_uri
        capture["original"] = original_source
        return [Document(page_content="docx text", metadata={"source": source_uri})]

    monkeypatch.setattr(loader, "_load_word_document", fake_word_loader)

    result = loader.load("sample.docx")

    assert capture == {"source": "sample.docx", "original": None}
    assert len(result) == 1
    assert result[0].page_content == "docx text"


def test_load_html_uses_unstructured(monkeypatch):
    loader = OfficeDocumentLoader()
    called = {}

    def fake_unstructured(source_uri):
        called["source"] = source_uri
        return [Document(page_content="html text", metadata={"source": source_uri})]

    monkeypatch.setattr(loader, "_load_doc_with_unstructured", fake_unstructured)

    result = loader.load("sample.HTML")

    assert called == {"source": "sample.HTML"}
    assert len(result) == 1
    assert result[0].page_content == "html text"
