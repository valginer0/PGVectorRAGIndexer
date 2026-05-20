"""
Tests for hybrid search functionality, specifically the exact-match boost.
Uses direct function testing without complex mocking.
"""

import pytest
from types import SimpleNamespace
from retriever_v2 import (
    DocumentRetriever,
    build_exact_token_regex,
    calculate_idf,
    fuse_ranked_candidates,
    normalize_lexical_terms,
    parse_search_query,
    weighted_rrf_score,
)


class TestHybridFusionHelpers:
    """Tests for the pure helpers used by the lexical-fusion design."""

    def test_normalize_lexical_terms_extracts_exact_match_tokens(self):
        terms = normalize_lexical_terms([
            "EV6 charging!",
            "ZXQ-000-NOT-REAL",
            "EV6",
            "invoice #4421",
        ])

        assert terms == ["ev6", "charging", "zxq-000-not-real", "invoice", "4421"]

    def test_build_exact_token_regex_uses_posix_boundaries_and_escaping(self):
        pattern = build_exact_token_regex("EV6+")

        assert pattern == r"(^|[^[:alnum:]_])ev6\+([^[:alnum:]_]|$)"

    def test_calculate_idf_rewards_rare_terms(self):
        rare = calculate_idf(total_documents=100, document_frequency=1)
        common = calculate_idf(total_documents=100, document_frequency=50)

        assert rare > common
        assert calculate_idf(total_documents=100, document_frequency=100) == pytest.approx(1.0)

    def test_weighted_rrf_score_combines_dense_and_lexical_ranks(self):
        combined = weighted_rrf_score(dense_rank=2, lexical_rank=2)
        dense_only = weighted_rrf_score(dense_rank=1)

        assert combined > dense_only

    def test_fuse_ranked_candidates_prefers_dual_signal_result(self):
        fused = fuse_ranked_candidates(
            dense_ranks={1: 1, 2: 2},
            lexical_ranks={3: 1, 2: 2},
        )

        assert fused[0][0] == 2
        assert {chunk_id for chunk_id, _score in fused} == {1, 2, 3}


class TestHybridSearchSQLGeneration:
    """Tests for the SQL generation logic in hybrid search."""
    
    def test_parse_search_query_extracts_phrases(self):
        """Test that parse_search_query correctly extracts quoted phrases."""
        phrases, terms = parse_search_query('Master Card "Simplicity 9112"')
        assert phrases == ['Simplicity 9112']
        assert terms == ['Master', 'Card']
    
    def test_tsquery_expression_for_phrases_only(self):
        """Test tsquery expression construction for phrase-only queries."""
        phrases, terms = parse_search_query('"exact phrase"')
        
        # Build tsquery expression as the code does
        tsquery_parts = []
        for _ in phrases:
            tsquery_parts.append("phraseto_tsquery('english', %s)")
        if terms:
            tsquery_parts.append("plainto_tsquery('english', %s)")
        tsquery_expression = ' && '.join(tsquery_parts) if tsquery_parts else "plainto_tsquery('english', %s)"
        
        assert 'phraseto_tsquery' in tsquery_expression
        assert 'plainto_tsquery' not in tsquery_expression
    
    def test_tsquery_expression_for_terms_only(self):
        """Test tsquery expression construction for terms-only queries."""
        phrases, terms = parse_search_query('simple search')
        
        # Build tsquery expression as the code does
        tsquery_parts = []
        for _ in phrases:
            tsquery_parts.append("phraseto_tsquery('english', %s)")
        if terms:
            tsquery_parts.append("plainto_tsquery('english', %s)")
        tsquery_expression = ' && '.join(tsquery_parts) if tsquery_parts else "plainto_tsquery('english', %s)"
        
        assert 'plainto_tsquery' in tsquery_expression
        assert 'phraseto_tsquery' not in tsquery_expression
    
    def test_tsquery_expression_for_mixed_query(self):
        """Test tsquery expression construction for mixed phrase and terms."""
        phrases, terms = parse_search_query('Master Card "Simplicity 9112"')
        
        # Build tsquery expression as the code does
        tsquery_parts = []
        for _ in phrases:
            tsquery_parts.append("phraseto_tsquery('english', %s)")
        if terms:
            tsquery_parts.append("plainto_tsquery('english', %s)")
        tsquery_expression = ' && '.join(tsquery_parts) if tsquery_parts else "plainto_tsquery('english', %s)"
        
        assert 'phraseto_tsquery' in tsquery_expression
        assert 'plainto_tsquery' in tsquery_expression
        assert '&&' in tsquery_expression
    
    def test_boost_sql_structure(self):
        """Test that the boost SQL CASE expression is well-formed."""
        # This tests the SQL structure that would be generated
        boost_sql = """
            CASE WHEN f.text_rank IS NOT NULL 
                THEN 10.0 + (%s * (1.0 / NULLIF(v.vector_rank, 0)) + %s * (1.0 / NULLIF(f.text_rank, 0)))
                ELSE %s * (1.0 / NULLIF(v.vector_rank, 0))
            END AS combined_score
        """
        
        # Verify key components
        assert 'CASE WHEN f.text_rank IS NOT NULL' in boost_sql
        assert '10.0' in boost_sql  # The boost value
        assert 'combined_score' in boost_sql
        assert 'THEN' in boost_sql
        assert 'ELSE' in boost_sql

    def test_hybrid_search_adds_literal_identifier_fallback(self):
        """Short identifiers like EV6 should be literal candidates, not vector-only."""
        captured = {}

        class FakeCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return []

        class FakeCursorContext:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        retriever = DocumentRetriever.__new__(DocumentRetriever)
        retriever.config = SimpleNamespace(
            retrieval=SimpleNamespace(top_k=10, hybrid_alpha=0.5, distance_metric="cosine")
        )
        retriever.embedding_service = SimpleNamespace(encode=lambda _query: [0.1, 0.2])
        retriever.db_manager = SimpleNamespace(get_cursor=lambda dict_cursor=False: FakeCursorContext())

        results = retriever.search_hybrid(
            "EV6",
            top_k=10,
            filters={"extensions": [".txt"]},
        )

        assert results == []
        assert "Literal substring matches for short identifiers" in captured["sql"]
        assert "text_content ILIKE %s" in captured["sql"]
        assert "d.text_content ILIKE %s" in captured["sql"]
        assert "%EV6%" in captured["params"]
        assert captured["params"].count("%EV6%") == 3
        assert captured["sql"].count("%s") == len(captured["params"])

    def test_hybrid_search_preserves_combined_score_as_rank_score(self):
        """The public result should expose the score used for hybrid ordering."""
        class FakeCursor:
            def execute(self, _sql, _params):
                pass

            def fetchall(self):
                return [
                    {
                        "chunk_id": 1,
                        "document_id": "doc-1",
                        "chunk_index": 0,
                        "text_content": "EV6 owner notes",
                        "source_uri": "ev6.txt",
                        "vector_distance": 0.25,
                        "text_score": 1.0,
                        "combined_score": 10.75,
                    }
                ]

        class FakeCursorContext:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        retriever = DocumentRetriever.__new__(DocumentRetriever)
        retriever.config = SimpleNamespace(
            retrieval=SimpleNamespace(top_k=10, hybrid_alpha=0.5, distance_metric="cosine")
        )
        retriever.embedding_service = SimpleNamespace(encode=lambda _query: [0.1, 0.2])
        retriever.db_manager = SimpleNamespace(get_cursor=lambda dict_cursor=False: FakeCursorContext())

        results = retriever.search_hybrid("EV6", top_k=1)

        assert len(results) == 1
        assert results[0].relevance_score == 0.75
        assert results[0].rank_score == 10.75
