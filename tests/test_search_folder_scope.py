"""Tests for folder-scoped search filters (path_prefixes / excluded_path_prefixes).

Covers:
- path_prefix_like_patterns normalization, escaping, and folder-boundary suffix
- Postgres CTE construction for include / exclude / combined prefix filters
- LanceDB filter-clause construction (both slash directions via starts_with)
- Unsupported-key error message lists the new keys
"""

import os
import sys

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# path_prefix_like_patterns
# ===========================================================================


class TestPathPrefixLikePatterns:
    def test_folder_boundary_suffix(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["ProjectA"]) == ["ProjectA/%"]

    def test_boundary_prevents_sibling_overmatch(self):
        # 'ProjectA/%' must not match 'ProjectAB/doc.pdf'
        from retriever_v2 import path_prefix_like_patterns
        pattern = path_prefix_like_patterns(["ProjectA"])[0]
        assert pattern == "ProjectA/%"
        assert not "ProjectAB/doc.pdf".startswith(pattern[:-1])

    def test_trailing_slash_stripped(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["ProjectA/"]) == ["ProjectA/%"]

    def test_windows_backslashes_normalized(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["C:\\Docs\\Legal"]) == ["C:/Docs/Legal/%"]

    def test_like_wildcards_escaped(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["my_folder"]) == [r"my\_folder/%"]
        assert path_prefix_like_patterns(["100% done"]) == [r"100\% done/%"]

    def test_root_and_empty_prefixes_dropped(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["/", "", "//"]) == []

    def test_mixed_valid_and_root(self):
        from retriever_v2 import path_prefix_like_patterns
        assert path_prefix_like_patterns(["/", "Docs"]) == ["Docs/%"]


# ===========================================================================
# Postgres CTE construction
# ===========================================================================


def _cte(filters):
    from retriever_v2 import DocumentRetriever
    ret = DocumentRetriever.__new__(DocumentRetriever)
    return ret._build_filtered_docs_context(filters)


class TestPostgresPathPrefixFilters:
    def test_include_single_prefix(self):
        from path_utils import NORMALIZED_URI_SQL
        cte, source, params = _cte({"path_prefixes": ["ProjectA"]})
        assert source == "filtered_docs"
        assert f"{NORMALIZED_URI_SQL} LIKE %s" in cte
        assert params == ["ProjectA/%"]

    def test_include_multiple_prefixes_ord(self):
        cte, source, params = _cte({"path_prefixes": ["A", "B"]})
        assert cte.count("LIKE %s") == 2
        assert " OR " in cte
        assert params == ["A/%", "B/%"]

    def test_exclude_prefix_negated(self):
        cte, source, params = _cte({"excluded_path_prefixes": ["Archive"]})
        assert "NOT (" in cte
        assert params == ["Archive/%"]

    def test_include_and_exclude_combined(self):
        cte, source, params = _cte({
            "path_prefixes": ["Docs"],
            "excluded_path_prefixes": ["Docs/old"],
        })
        assert "NOT (" in cte
        assert " AND " in cte
        assert params == ["Docs/%", "Docs/old/%"]

    def test_empty_lists_are_noop(self):
        cte, source, params = _cte({
            "path_prefixes": [],
            "excluded_path_prefixes": [],
        })
        assert cte == ""
        assert source == "document_chunks"
        assert params == []

    def test_root_only_prefix_is_noop(self):
        cte, source, params = _cte({"path_prefixes": ["/"]})
        assert cte == ""
        assert source == "document_chunks"

    def test_composes_with_other_filters(self):
        cte, source, params = _cte({
            "path_prefixes": ["Docs"],
            "extensions": [".pdf"],
        })
        assert "source_uri ILIKE %s" in cte
        assert "LIKE %s" in cte
        assert "%.pdf" in params
        assert "Docs/%" in params

    def test_unsupported_key_error_lists_new_keys(self):
        with pytest.raises(ValueError) as exc_info:
            _cte({"bogus_key": "x"})
        assert "path_prefixes" in str(exc_info.value)
        assert "excluded_path_prefixes" in str(exc_info.value)

    def test_search_hybrid_shares_clause_builder(self):
        # search_hybrid delegates to the same _build_chunk_filter_clauses,
        # so prefix support cannot drift between the two hybrid variants.
        from retriever_v2 import DocumentRetriever
        ret = DocumentRetriever.__new__(DocumentRetriever)
        clauses, params = ret._build_chunk_filter_clauses(
            {"path_prefixes": ["Docs"]}
        )
        assert len(clauses) == 1
        assert params == ["Docs/%"]


# ===========================================================================
# LanceDB filter clause
# ===========================================================================


def _lancedb_clause(filters):
    from lancedb_adapter import BackendLanceDBAdapter
    adapter = BackendLanceDBAdapter.__new__(BackendLanceDBAdapter)
    return adapter._build_lancedb_filter_clause(filters)


class TestLanceDBPathPrefixFilters:
    def test_include_matches_both_slash_directions(self):
        clause = _lancedb_clause({"path_prefixes": ["Docs/Legal"]})
        assert "starts_with(source_uri, 'Docs/Legal/')" in clause
        assert "starts_with(source_uri, 'Docs\\Legal\\')" in clause
        assert " OR " in clause

    def test_exclude_negated(self):
        clause = _lancedb_clause({"excluded_path_prefixes": ["Archive"]})
        assert clause.startswith("NOT (")
        assert "starts_with(source_uri, 'Archive/')" in clause

    def test_windows_prefix_normalized_then_both_directions(self):
        clause = _lancedb_clause({"path_prefixes": ["C:\\Docs"]})
        assert "starts_with(source_uri, 'C:/Docs/')" in clause
        assert "starts_with(source_uri, 'C:\\Docs\\')" in clause

    def test_quotes_escaped(self):
        clause = _lancedb_clause({"path_prefixes": ["O'Brien Case"]})
        assert "O''Brien Case/" in clause
        assert "O'Brien Case/" not in clause.replace("O''Brien", "")

    def test_root_only_prefix_yields_no_clause(self):
        assert _lancedb_clause({"path_prefixes": ["/"]}) is None

    def test_composes_with_document_id(self):
        clause = _lancedb_clause({
            "path_prefixes": ["Docs"],
            "document_id": "abc",
        })
        assert "document_id = 'abc'" in clause
        assert " AND " in clause
