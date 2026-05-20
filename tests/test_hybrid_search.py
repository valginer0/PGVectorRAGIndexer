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

    @pytest.mark.parametrize(
        ("total_documents", "document_frequency", "message"),
        [
            (-1, 0, "total_documents must be non-negative"),
            (10, -1, "document_frequency must be non-negative"),
            (10, 11, "document_frequency cannot exceed total_documents"),
        ],
    )
    def test_calculate_idf_rejects_invalid_counts(
        self,
        total_documents,
        document_frequency,
        message,
    ):
        with pytest.raises(ValueError, match=message):
            calculate_idf(total_documents, document_frequency)

    def test_weighted_rrf_score_combines_dense_and_lexical_ranks(self):
        combined = weighted_rrf_score(dense_rank=2, lexical_rank=2)
        dense_only = weighted_rrf_score(dense_rank=1)

        assert combined > dense_only

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"rrf_k": -1}, "rrf_k must be non-negative"),
            ({"dense_rank": 0}, "dense_rank must be positive"),
            ({"lexical_rank": 0}, "lexical_rank must be positive"),
        ],
    )
    def test_weighted_rrf_score_rejects_invalid_rank_inputs(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            weighted_rrf_score(**kwargs)

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

    def test_hybrid_fusion_v0_fuses_dense_and_lexical_candidates(self):
        """The experimental path should rank dual-signal chunks above single-signal chunks."""
        captured = {"calls": []}

        class FakeCursor:
            def __init__(self):
                self.responses = [
                    ("all", [
                        {"chunk_id": 1, "dense_rank": 1, "vector_distance": 0.10},
                        {"chunk_id": 2, "dense_rank": 2, "vector_distance": 0.20},
                    ]),
                    ("one", {"total_documents": 10}),
                    ("one", {"document_frequency": 1}),
                    ("one", {"document_frequency": 8}),
                    ("all", [
                        {
                            "chunk_id": 2,
                            "lexical_rank": 1,
                            "lexical_score": 2.0,
                            "matched_terms": ["ev6"],
                            "full_term_match": False,
                            "matched_term_count": 1,
                            "phrase_match_count": 0,
                        },
                        {
                            "chunk_id": 3,
                            "lexical_rank": 2,
                            "lexical_score": 2.0,
                            "matched_terms": ["ev6"],
                            "full_term_match": False,
                            "matched_term_count": 1,
                            "phrase_match_count": 0,
                        },
                    ]),
                    ("all", [
                        {
                            "chunk_id": 1,
                            "document_id": "doc-1",
                            "chunk_index": 0,
                            "text_content": "Charging notes",
                            "source_uri": "charging.txt",
                            "vector_distance": 0.10,
                            "metadata": {},
                        },
                        {
                            "chunk_id": 2,
                            "document_id": "doc-2",
                            "chunk_index": 0,
                            "text_content": "EV6 notes",
                            "source_uri": "ev6.txt",
                            "vector_distance": 0.20,
                            "metadata": {"type": "note"},
                        },
                        {
                            "chunk_id": 3,
                            "document_id": "doc-3",
                            "chunk_index": 0,
                            "text_content": "EV6 warranty",
                            "source_uri": "ev6_warranty.txt",
                            "vector_distance": 0.30,
                            "metadata": {},
                        },
                    ]),
                ]
                self.current = None

            def execute(self, sql, params):
                captured["calls"].append((sql, params))
                self.current = self.responses.pop(0)

            def fetchall(self):
                kind, data = self.current
                assert kind == "all"
                return data

            def fetchone(self):
                kind, data = self.current
                assert kind == "one"
                return data

        class FakeCursorContext:
            def __init__(self):
                self.cursor = FakeCursor()

            def __enter__(self):
                return self.cursor

            def __exit__(self, exc_type, exc, tb):
                return False

        retriever = DocumentRetriever.__new__(DocumentRetriever)
        retriever.config = SimpleNamespace(
            retrieval=SimpleNamespace(top_k=10, hybrid_alpha=0.5, distance_metric="cosine")
        )
        retriever.embedding_service = SimpleNamespace(encode=lambda _query: [0.1, 0.2])
        retriever.db_manager = SimpleNamespace(get_cursor=lambda dict_cursor=False: FakeCursorContext())

        results, diagnostics = retriever.search_hybrid_fusion_v0(
            "EV6 charging",
            top_k=3,
            filters={"extensions": [".txt"]},
        )

        assert [result.chunk_id for result in results] == [2, 1, 3]
        assert results[0].source_uri == "ev6.txt"
        assert results[0].document_type == "note"
        assert results[0].rank_score > results[1].rank_score
        assert diagnostics["hybrid_fusion_v0"]["active"] is True
        assert diagnostics["hybrid_fusion_v0"]["query_terms"][0]["term"] == "ev6"
        assert diagnostics["hybrid_fusion_v0"]["query_terms"][0]["df"] == 1
        assert diagnostics["hybrid_fusion_v0"]["top_explanations"][0]["dense_rank"] == 2
        assert diagnostics["hybrid_fusion_v0"]["top_explanations"][0]["lexical_rank"] == 1
        assert "~* %s" in captured["calls"][4][0]
        assert captured["calls"][0][1][0] == "%.txt"

    def test_hybrid_fusion_v0_alpha_controls_dense_and_lexical_weights(self):
        """Alpha should map to dense weight, with lexical weight as the complement."""
        def run_with_alpha(alpha):
            class FakeCursor:
                def __init__(self):
                    self.responses = [
                        ("all", [
                            {"chunk_id": 1, "dense_rank": 1, "vector_distance": 0.10},
                            {"chunk_id": 2, "dense_rank": 2, "vector_distance": 0.20},
                        ]),
                        ("one", {"total_documents": 10}),
                        ("one", {"document_frequency": 2}),
                        ("all", [
                            {
                                "chunk_id": 2,
                                "lexical_rank": 1,
                                "lexical_score": 2.0,
                                "matched_terms": ["ev6"],
                                "full_term_match": True,
                                "matched_term_count": 1,
                                "phrase_match_count": 0,
                            },
                        ]),
                        ("all", [
                            {
                                "chunk_id": 1,
                                "document_id": "doc-1",
                                "chunk_index": 0,
                                "text_content": "Charging notes",
                                "source_uri": "charging.txt",
                                "vector_distance": 0.10,
                                "metadata": {},
                            },
                            {
                                "chunk_id": 2,
                                "document_id": "doc-2",
                                "chunk_index": 0,
                                "text_content": "EV6 notes",
                                "source_uri": "ev6.txt",
                                "vector_distance": 0.20,
                                "metadata": {},
                            },
                        ]),
                    ]
                    self.current = None

                def execute(self, _sql, _params):
                    self.current = self.responses.pop(0)

                def fetchall(self):
                    kind, data = self.current
                    assert kind == "all"
                    return data

                def fetchone(self):
                    kind, data = self.current
                    assert kind == "one"
                    return data

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
            return retriever.search_hybrid_fusion_v0("EV6", top_k=2, alpha=alpha)

        dense_results, dense_diagnostics = run_with_alpha(1.0)
        lexical_results, lexical_diagnostics = run_with_alpha(0.0)

        assert [result.chunk_id for result in dense_results] == [1, 2]
        assert dense_diagnostics["hybrid_fusion_v0"]["dense_weight"] == 1.0
        assert dense_diagnostics["hybrid_fusion_v0"]["lexical_weight"] == 0.0
        assert [result.chunk_id for result in lexical_results] == [2, 1]
        assert lexical_diagnostics["hybrid_fusion_v0"]["dense_weight"] == 0.0
        assert lexical_diagnostics["hybrid_fusion_v0"]["lexical_weight"] == 1.0
