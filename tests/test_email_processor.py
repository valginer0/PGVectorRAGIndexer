"""
Unit tests for Email Processor.

Tests thread cleaning, HTML conversion, and metadata enrichment.
"""

import pytest
from datetime import datetime
from connectors.email.processor import EmailProcessor, ProcessedEmail


class TestEmailProcessor:
    """Tests for EmailProcessor class."""
    
    @pytest.fixture
    def processor(self):
        """Create a processor instance."""
        return EmailProcessor(chunk_size=500, chunk_overlap=50)
    
    # =========================================================================
    # HTML to Text Conversion
    # =========================================================================
    
    def test_html_to_text_basic(self, processor):
        """Test basic HTML to text conversion."""
        html = "<p>Hello <strong>World</strong></p>"
        result = processor.html_to_text(html)
        assert "Hello" in result
        assert "World" in result
        assert "<p>" not in result
    
    def test_html_to_text_empty(self, processor):
        """Test empty HTML returns empty string."""
        assert processor.html_to_text("") == ""
        assert processor.html_to_text(None) == ""
    
    def test_html_to_text_removes_scripts(self, processor):
        """Test that script and style tags are removed."""
        html = """
        <html>
        <head><style>body { color: red; }</style></head>
        <body>
        <script>alert('bad');</script>
        <p>Actual content</p>
        </body>
        </html>
        """
        result = processor.html_to_text(html)
        assert "Actual content" in result
        assert "alert" not in result
        assert "color: red" not in result
    
    # =========================================================================
    # Thread Cleaning
    # =========================================================================
    
    def test_clean_thread_removes_from_header(self, processor):
        """Test that 'From:' headers are removed."""
        text = """Hi,

Let's meet tomorrow.

From: John Doe
Sent: Monday, January 1, 2024
To: Jane Smith
Subject: Re: Meeting

Previous message content here."""
        
        result = processor.clean_thread(text)
        assert "Let's meet tomorrow" in result
        assert "From: John Doe" not in result
    
    def test_clean_thread_removes_original_message_separator(self, processor):
        """Test that Outlook separators are removed."""
        text = """Reply content here.

-----Original Message-----
From: Someone
The original message."""
        
        result = processor.clean_thread(text)
        assert "Reply content" in result
        # The original message marker and content after should be cleaned
        assert "-----Original Message-----" not in result
    
    def test_clean_thread_removes_quoted_lines(self, processor):
        """Test that quoted lines (>) are removed."""
        text = """My response.

> Previous quoted text
> More quoted text
>> Double quoted"""
        
        result = processor.clean_thread(text)
        assert "My response" in result
        assert "> Previous" not in result
    
    def test_clean_thread_preserves_normal_content(self, processor):
        """Test that regular content is preserved."""
        text = """Hello,

This is a normal email without any reply chains.

Best regards,
Alice"""
        
        result = processor.clean_thread(text)
        assert "Hello" in result
        assert "normal email" in result
        assert "Alice" in result
    
    # =========================================================================
    # Metadata Enrichment
    # =========================================================================
    
    def test_enrich_chunk_with_all_metadata(self, processor):
        """Test chunk enrichment with all metadata."""
        chunk = "Sure, let's do 5pm."
        result = processor.enrich_chunk(
            chunk,
            sender="Irena <irena@example.com>",
            subject="Birthday Dinner",
            received_at=datetime(2025, 10, 11, 14, 30)
        )
        
        assert "From: Irena" in result
        assert "Date: 2025-10-11" in result
        assert "Subject: Birthday Dinner" in result
        assert "Sure, let's do 5pm" in result
    
    def test_enrich_chunk_with_partial_metadata(self, processor):
        """Test chunk enrichment with only some metadata."""
        chunk = "Meeting confirmed."
        result = processor.enrich_chunk(
            chunk,
            sender=None,
            subject="Meeting",
            received_at=None
        )
        
        assert "Subject: Meeting" in result
        assert "Meeting confirmed" in result
        assert "From:" not in result
        assert "Date:" not in result
    
    def test_enrich_chunk_no_metadata(self, processor):
        """Test chunk enrichment with no metadata returns original."""
        chunk = "Just the content."
        result = processor.enrich_chunk(
            chunk,
            sender=None,
            subject=None,
            received_at=None
        )
        assert result == chunk
    
    # =========================================================================
    # Full Processing Pipeline
    # =========================================================================
    
    def test_process_email_full_pipeline(self, processor):
        """Test complete email processing pipeline."""
        raw_email = {
            'id': 'msg-123',
            'thread_id': 'thread-456',
            'sender': 'alice@example.com',
            'subject': 'Project Update',
            'body': '<p>The project is on track.</p>',
            'received_at': datetime(2025, 1, 15, 10, 0),
            'has_attachments': False,
            'is_read': True,
        }
        
        result = processor.process(raw_email)
        
        assert isinstance(result, ProcessedEmail)
        assert result.message_id == 'msg-123'
        assert result.thread_id == 'thread-456'
        assert len(result.chunks) >= 1
        assert "project is on track" in result.chunks[0].lower()
    
    def test_process_email_empty_body(self, processor):
        """Test processing email with empty body."""
        raw_email = {
            'id': 'msg-empty',
            'thread_id': None,
            'sender': None,
            'subject': None,
            'body': '',
            'received_at': None,
        }
        
        result = processor.process(raw_email)
        
        assert result.chunks == []
        assert result.metadata.get('skipped') is True
    
    def test_process_email_long_body_chunked(self, processor):
        """Test that long emails are split into chunks."""
        # Create content longer than chunk_size (500)
        long_content = "This is a sentence. " * 100  # ~2000 chars
        
        raw_email = {
            'id': 'msg-long',
            'thread_id': None,
            'sender': 'sender@test.com',
            'subject': 'Long Email',
            'body': f'<p>{long_content}</p>',
            'received_at': datetime.now(),
        }
        
        result = processor.process(raw_email)
        
        # Should have multiple chunks
        assert len(result.chunks) > 1
        assert result.metadata.get('chunk_count') > 1
