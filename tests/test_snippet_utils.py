"""
Tests for snippet extraction utilities.
"""

import pytest
from desktop_app.utils.snippet_utils import extract_snippet, highlight_terms, _truncate


class TestExtractSnippet:
    """Tests for extract_snippet function."""
    
    def test_basic_single_word_match(self):
        """Test extracting snippet with a single matching word."""
        text = "The quick brown fox jumps over the lazy dog. The dog was very sleepy."
        query = "jumps"
        
        snippet = extract_snippet(text, query, window=30)
        
        assert "jumps" in snippet.lower()
        assert "..." in snippet  # Should have ellipsis since truncated
    
    def test_match_at_beginning(self):
        """Test when match is at the beginning of text."""
        text = "Python is a great programming language for beginners and experts alike."
        query = "Python"
        
        snippet = extract_snippet(text, query, window=40)
        
        assert snippet.startswith("Python")
        assert "..." in snippet  # Should have trailing ellipsis
    
    def test_match_at_end(self):
        """Test when match is at the end of text."""
        text = "This is a long text that talks about many things including Python."
        query = "Python"
        
        snippet = extract_snippet(text, query, window=40)
        
        assert "Python" in snippet
        assert snippet.endswith("Python.") or snippet.endswith("Python")
    
    def test_multi_word_query_finds_first_match(self):
        """Test that multi-word query finds the first matching word."""
        text = "AAA BBB CCC DDD EEE FFF GGG HHH insurance III JJJ KKK policy LLL MMM"
        query = "policy insurance"  # "insurance" appears first in text
        
        snippet = extract_snippet(text, query, window=40)
        
        # Should find "insurance" which appears first
        assert "insurance" in snippet.lower()
    
    def test_no_match_returns_beginning(self):
        """Test fallback to beginning when no match found."""
        text = "The quick brown fox jumps over the lazy dog."
        query = "elephant"
        
        snippet = extract_snippet(text, query, window=20)
        
        assert snippet.startswith("The quick")
        assert "..." in snippet
    
    def test_empty_text_returns_empty(self):
        """Test empty text input."""
        assert extract_snippet("", "query") == ""
    
    def test_empty_query_returns_beginning(self):
        """Test empty query returns beginning of text."""
        text = "Some long text that should be truncated at the beginning."
        
        snippet = extract_snippet(text, "", window=20)
        
        assert snippet.startswith("Some")
    
    def test_short_text_no_truncation(self):
        """Test that short text is returned as-is."""
        text = "Short text"
        query = "short"
        
        snippet = extract_snippet(text, query, window=100)
        
        assert snippet == "Short text"
        assert "..." not in snippet
    
    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        text = "The UPPERCASE word appears here."
        query = "uppercase"
        
        snippet = extract_snippet(text, query, window=50)
        
        assert "UPPERCASE" in snippet
    
    def test_skips_very_short_words(self):
        """Test that very short query words (< 2 chars) are skipped."""
        text = "The a an it is at on to for helpful example here."
        query = "a helpful"  # "a" should be skipped, "helpful" should match
        
        snippet = extract_snippet(text, query, window=40)
        
        assert "helpful" in snippet.lower()


class TestTruncate:
    """Tests for _truncate helper function."""
    
    def test_no_truncation_needed(self):
        """Test text shorter than limit."""
        assert _truncate("short", 10) == "short"
    
    def test_truncation_with_ellipsis(self):
        """Test truncation adds ellipsis."""
        result = _truncate("this is a long text", 10)
        assert result.endswith("...")
        assert len(result) <= 13  # 10 chars + "..."
    
    def test_custom_ellipsis(self):
        """Test custom ellipsis string."""
        result = _truncate("long text here", 8, ellipsis="…")
        assert result.endswith("…")


class TestHighlightTerms:
    """Tests for highlight_terms function."""
    
    def test_basic_highlighting(self):
        """Test basic term highlighting."""
        text = "The quick brown fox"
        query = "quick"
        
        result = highlight_terms(text, query)
        
        assert "**quick**" in result
    
    def test_multiple_terms(self):
        """Test highlighting multiple terms."""
        text = "The quick brown fox jumps"
        query = "quick fox"
        
        result = highlight_terms(text, query)
        
        assert "**quick**" in result
        assert "**fox**" in result
    
    def test_case_preserved(self):
        """Test that original case is preserved."""
        text = "The QUICK brown Fox"
        query = "quick fox"
        
        result = highlight_terms(text, query)
        
        assert "**QUICK**" in result
        assert "**Fox**" in result
    
    def test_custom_markers(self):
        """Test custom before/after markers."""
        text = "The quick brown fox"
        query = "quick"
        
        result = highlight_terms(text, query, before="<b>", after="</b>")
        
        assert "<b>quick</b>" in result
    
    def test_empty_text_returns_empty(self):
        """Test empty text input."""
        assert highlight_terms("", "query") == ""
    
    def test_empty_query_returns_text(self):
        """Test empty query returns original text."""
        text = "Some text"
        assert highlight_terms(text, "") == text
