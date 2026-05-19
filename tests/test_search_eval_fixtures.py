from pathlib import Path

import pytest
import yaml


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "search_eval"
VALID_QUERY_CLASSES = {
    "literal",
    "contextual",
    "hybrid",
    "filtered",
    "chunk_crowding",
    "negative",
}
QUERY_FILE_FIELDS = ("expected_files", "relevant_files", "forbidden_files")


@pytest.fixture(scope="module")
def manifest():
    return yaml.safe_load((FIXTURE_ROOT / "manifest.yaml").read_text())


@pytest.fixture(scope="module")
def queries():
    return yaml.safe_load((FIXTURE_ROOT / "queries.yaml").read_text())


def test_manifest_documents_exist_and_use_eval_namespace(manifest):
    assert manifest["namespace"] == "search_eval_v0"
    assert manifest["default_metadata"]["namespace"] == "search_eval_v0"
    assert manifest["default_metadata"]["category"] == "search_eval"

    document_paths = [doc["path"] for doc in manifest["documents"]]
    assert len(document_paths) == len(set(document_paths))

    for path in document_paths:
        document_path = FIXTURE_ROOT / path
        assert document_path.exists(), f"manifest references missing file: {path}"
        assert document_path.is_file(), f"manifest path is not a file: {path}"
        assert document_path.read_text().strip(), f"fixture file is empty: {path}"


def test_queries_have_unique_ids_and_valid_classes(queries):
    query_items = queries["queries"]
    query_ids = [item["id"] for item in query_items]

    assert queries["default_filters"] == {"namespace": "search_eval_v0"}
    assert queries["default_top_k_files"] == 5
    assert queries["default_backend_top_k"] >= queries["default_top_k_files"]
    assert len(query_ids) == len(set(query_ids))

    for item in query_items:
        assert item["class"] in VALID_QUERY_CLASSES
        assert item["query"].strip()
        assert item.get("assertions"), f"query has no assertions: {item['id']}"


def test_query_file_references_exist_in_manifest(manifest, queries):
    manifest_paths = {doc["path"] for doc in manifest["documents"]}

    for item in queries["queries"]:
        for field in QUERY_FILE_FIELDS:
            for path in item.get(field, []) or []:
                assert path in manifest_paths, (
                    f"{item['id']} {field} references a file not listed "
                    f"in manifest.yaml: {path}"
                )


def test_query_extension_filters_match_expected_files(queries):
    for item in queries["queries"]:
        extensions = (item.get("filters") or {}).get("extensions")
        if not extensions:
            continue

        assert all(ext.startswith(".") for ext in extensions)

        for path in item.get("expected_files", []) or []:
            assert Path(path).suffix in extensions, (
                f"{item['id']} expects {path}, but filter only allows {extensions}"
            )


def test_eval_corpus_preserves_literal_and_negative_contracts():
    ev6_text = (
        FIXTURE_ROOT / "corpus" / "vehicles" / "ev6_owner_notes.txt"
    ).read_text()
    crowding_text = (
        FIXTURE_ROOT / "corpus" / "vehicles" / "ev6_chunk_crowding.txt"
    ).read_text()
    niro_text = (
        FIXTURE_ROOT / "corpus" / "vehicles" / "niro_service_bulletin.txt"
    ).read_text()
    banana_text = (
        FIXTURE_ROOT / "corpus" / "noise" / "banana_bread_recipe.txt"
    ).read_text()

    assert "EV6" in ev6_text
    assert crowding_text.count("EV6") >= 8
    assert "does not mention the EV6" in niro_text
    assert "EV6" not in banana_text
