"""
Utility functions for extracting relevant snippets from text.
"""

import re
from typing import List, Optional


def extract_snippet(
    text: str,
    query: str,
    window: int = 100,
    ellipsis: str = "..."
) -> str:
    """
    Extract a relevant snippet from text around query terms.
    
    Finds the first occurrence of any query term in the text and returns
    a window of text around it. Falls back to the first `window` characters
    if no match is found.
    
    Args:
        text: Full text content to extract from
        query: Search query (can be multiple words)
        window: Number of characters to show (centered on match if possible)
        ellipsis: String to add when text is truncated
        
    Returns:
        Extracted snippet with ellipsis if truncated
    """
    if not text:
        return ""
    
    if not query:
        # No query - just return beginning of text
        return _truncate(text, window, ellipsis)
    
    # Tokenize query into words (simple whitespace split, filter empty)
    query_words = [w.strip().lower() for w in query.split() if w.strip()]
    
    if not query_words:
        return _truncate(text, window, ellipsis)
    
    text_lower = text.lower()
    
    # Find the first matching query word
    best_pos = -1
    best_word = ""
    
    for word in query_words:
        # Skip very short words (they match too much)
        if len(word) < 2:
            continue
            
        pos = text_lower.find(word)
        if pos != -1 and (best_pos == -1 or pos < best_pos):
            best_pos = pos
            best_word = word
    
    if best_pos == -1:
        # No match found - return beginning
        return _truncate(text, window, ellipsis)
    
    # Calculate window around the match
    half_window = window // 2
    
    # Center the window on the match
    start = max(0, best_pos - half_window)
    end = min(len(text), best_pos + len(best_word) + half_window)
    
    # Adjust if we hit boundaries
    if start == 0:
        end = min(len(text), window)
    elif end == len(text):
        start = max(0, len(text) - window)
    
    snippet = text[start:end]
    
    # Add ellipsis
    prefix = ellipsis if start > 0 else ""
    suffix = ellipsis if end < len(text) else ""
    
    return f"{prefix}{snippet.strip()}{suffix}"


def _truncate(text: str, length: int, ellipsis: str = "...") -> str:
    """Truncate text to length, adding ellipsis if needed."""
    if len(text) <= length:
        return text
    return text[:length].strip() + ellipsis


def highlight_terms(text: str, query: str, before: str = "**", after: str = "**") -> str:
    """
    Highlight query terms in text using markers.
    
    This is useful for rich text display where you want to bold/highlight
    the matching terms.
    
    Args:
        text: Text to highlight terms in
        query: Search query
        before: String to insert before each match
        after: String to insert after each match
        
    Returns:
        Text with query terms wrapped in before/after markers
    """
    if not text or not query:
        return text
    
    query_words = [w.strip() for w in query.split() if w.strip() and len(w.strip()) >= 2]
    
    if not query_words:
        return text
    
    result = text
    for word in query_words:
        # Case-insensitive replacement while preserving original case
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        result = pattern.sub(lambda m: f"{before}{m.group()}{after}", result)
    
    return result
