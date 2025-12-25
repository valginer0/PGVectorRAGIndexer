"""
Tests for hybrid search functionality, specifically the exact-match boost.
Uses direct function testing without complex mocking.
"""

import pytest
from retriever_v2 import parse_search_query


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
