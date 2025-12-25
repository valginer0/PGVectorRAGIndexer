"""
Tests for search query parsing functionality.
"""

import pytest
from retriever_v2 import parse_search_query


class TestParseSearchQuery:
    """Tests for the parse_search_query function."""
    
    def test_double_quoted_phrase(self):
        """Test extraction of double-quoted phrases."""
        phrases, terms = parse_search_query('Master Card "Simplicity 9112"')
        assert phrases == ['Simplicity 9112']
        assert terms == ['Master', 'Card']
    
    def test_single_quoted_phrase(self):
        """Test extraction of single-quoted phrases."""
        phrases, terms = parse_search_query("Master Card 'Simplicity 9112'")
        assert phrases == ['Simplicity 9112']
        assert terms == ['Master', 'Card']
    
    def test_no_quotes(self):
        """Test query with no quoted phrases."""
        phrases, terms = parse_search_query('Master Card Simplicity 9112')
        assert phrases == []
        assert terms == ['Master', 'Card', 'Simplicity', '9112']
    
    def test_multiple_phrases(self):
        """Test extraction of multiple quoted phrases."""
        phrases, terms = parse_search_query('"phrase one" and "phrase two"')
        assert phrases == ['phrase one', 'phrase two']
        assert terms == ['and']
    
    def test_phrase_only_query(self):
        """Test query with only a quoted phrase."""
        phrases, terms = parse_search_query('"exact match"')
        assert phrases == ['exact match']
        assert terms == []
    
    def test_curly_double_quotes(self):
        """Test smart/curly double quotes from word processors."""
        phrases, terms = parse_search_query('search \u201cexact phrase\u201d here')
        assert phrases == ['exact phrase']
        assert terms == ['search', 'here']
    
    def test_curly_single_quotes(self):
        """Test smart/curly single quotes from word processors."""
        phrases, terms = parse_search_query("search \u2018exact phrase\u2019 here")
        assert phrases == ['exact phrase']
        assert terms == ['search', 'here']
    
    def test_empty_query(self):
        """Test empty query string."""
        phrases, terms = parse_search_query('')
        assert phrases == []
        assert terms == []
    
    def test_whitespace_handling(self):
        """Test that whitespace in phrases is preserved."""
        phrases, terms = parse_search_query('"  spaced  phrase  "')
        assert phrases == ['spaced  phrase']  # Internal whitespace preserved, edges trimmed
        assert terms == []
