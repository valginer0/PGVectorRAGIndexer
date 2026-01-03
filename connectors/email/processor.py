"""
Email Processor for cleaning and enriching email content.

Handles:
- Thread cleaning (removing reply chains)
- HTML to text conversion
- Metadata enrichment for better search
"""

import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


# Common patterns for reply chain headers
REPLY_CHAIN_PATTERNS = [
    # "From: John Doe <john@example.com>"
    r'^\s*From:\s+.+$',
    # "Sent: Monday, January 1, 2024 10:00 AM"
    r'^\s*Sent:\s+.+$',
    # "To: recipient@example.com"
    r'^\s*To:\s+.+$',
    # "Cc: someone@example.com"
    r'^\s*Cc:\s+.+$',
    # "Subject: Re: Original Subject"
    r'^\s*Subject:\s+.+$',
    # "-----Original Message-----"
    r'^-{3,}\s*Original Message\s*-{3,}$',
    # "On Jan 1, 2024, at 10:00 AM, John Doe wrote:"
    r'^On\s+.+wrote:$',
    # "> quoted text"
    r'^>+\s*.*$',
    # "________________________________" (Outlook separator)
    r'^_{10,}$',
]

# Compiled regex for performance
REPLY_CHAIN_REGEX = re.compile(
    '|'.join(REPLY_CHAIN_PATTERNS),
    re.MULTILINE | re.IGNORECASE
)


@dataclass
class ProcessedEmail:
    """Represents a processed email ready for indexing."""
    message_id: str
    thread_id: Optional[str]
    sender: Optional[str]
    subject: Optional[str]
    received_at: Optional[datetime]
    chunks: List[str]  # List of enriched text chunks
    metadata: Dict[str, Any]


class EmailProcessor:
    """
    Processes raw email content for indexing.
    
    Responsibilities:
    - Convert HTML body to clean text
    - Remove reply chains to avoid duplicate indexing
    - Split long emails into chunks
    - Enrich chunks with metadata for better search
    """
    
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        clean_reply_chains: bool = True
    ):
        """
        Initialize the Email Processor.
        
        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between chunks
            clean_reply_chains: Whether to remove reply chain content
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.clean_reply_chains = clean_reply_chains
        
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
    
    def html_to_text(self, html_content: str) -> str:
        """
        Convert HTML email body to plain text.
        
        Args:
            html_content: HTML string
        
        Returns:
            Clean text content
        """
        if not html_content:
            return ""
        
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for element in soup(['script', 'style', 'head']):
                element.decompose()
            
            # Get text and normalize whitespace
            text = soup.get_text(separator='\n')
        else:
            # Fallback: basic HTML tag removal
            text = re.sub(r'<[^>]+>', '', html_content)
        
        # Normalize whitespace
        lines = [line.strip() for line in text.splitlines()]
        text = '\n'.join(line for line in lines if line)
        
        return text
    
    def clean_thread(self, text: str) -> str:
        """
        Remove reply chain content from email text.
        
        This prevents duplicate indexing of forwarded/replied content.
        
        Args:
            text: Email body text
        
        Returns:
            Cleaned text with reply chains removed
        """
        if not self.clean_reply_chains:
            return text
        
        lines = text.splitlines()
        cleaned_lines = []
        in_reply_chain = False
        
        for line in lines:
            # Check if this line starts a reply chain
            if REPLY_CHAIN_REGEX.match(line):
                in_reply_chain = True
                continue
            
            # Skip lines that are part of the reply chain
            if in_reply_chain:
                # Check if we've exited the reply chain (blank line after headers)
                if not line.strip():
                    continue
                # If we see normal content after blank lines, we might still be in chain
                if line.startswith('>'):
                    continue
            
            # Reset if we see a clear separator
            if line.strip() == '':
                in_reply_chain = False
            
            if not in_reply_chain:
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def enrich_chunk(
        self,
        chunk: str,
        sender: Optional[str],
        subject: Optional[str],
        received_at: Optional[datetime]
    ) -> str:
        """
        Enrich a text chunk with metadata for better search.
        
        Bad chunk: "Sure, let's do 5pm."
        Good chunk: "From: Irena. Date: 2025-10-11. Subject: Birthday Dinner. Content: Sure, let's do 5pm."
        
        Args:
            chunk: Raw text chunk
            sender: Email sender
            subject: Email subject
            received_at: When email was received
        
        Returns:
            Enriched text chunk
        """
        parts = []
        
        if sender:
            # Extract just the name/email, not full address object
            sender_str = str(sender).split('<')[0].strip() or str(sender)
            parts.append(f"From: {sender_str}")
        
        if received_at:
            date_str = received_at.strftime("%Y-%m-%d")
            parts.append(f"Date: {date_str}")
        
        if subject:
            parts.append(f"Subject: {subject}")
        
        if parts:
            prefix = ". ".join(parts) + ". Content: "
            return prefix + chunk
        
        return chunk
    
    def process(self, raw_email: Dict[str, Any]) -> ProcessedEmail:
        """
        Process a raw email into chunks ready for indexing.
        
        Args:
            raw_email: Dict with keys: id, thread_id, sender, subject, body, received_at
        
        Returns:
            ProcessedEmail with enriched chunks
        """
        message_id = raw_email.get('id')
        thread_id = raw_email.get('thread_id')
        sender = raw_email.get('sender')
        subject = raw_email.get('subject')
        received_at = raw_email.get('received_at')
        body_html = raw_email.get('body', '')
        
        # Convert HTML to text
        body_text = self.html_to_text(body_html)
        
        # Clean reply chains
        cleaned_text = self.clean_thread(body_text)
        
        # Skip if no meaningful content
        if not cleaned_text or len(cleaned_text.strip()) < 10:
            logger.debug(f"Skipping email {message_id}: no meaningful content")
            return ProcessedEmail(
                message_id=message_id,
                thread_id=thread_id,
                sender=sender,
                subject=subject,
                received_at=received_at,
                chunks=[],
                metadata={'skipped': True, 'reason': 'no_content'}
            )
        
        # Split into chunks if needed
        if len(cleaned_text) <= self.chunk_size:
            raw_chunks = [cleaned_text]
        else:
            raw_chunks = self._splitter.split_text(cleaned_text)
        
        # Enrich each chunk
        enriched_chunks = [
            self.enrich_chunk(chunk, sender, subject, received_at)
            for chunk in raw_chunks
        ]
        
        return ProcessedEmail(
            message_id=message_id,
            thread_id=thread_id,
            sender=sender,
            subject=subject,
            received_at=received_at,
            chunks=enriched_chunks,
            metadata={
                'has_attachments': raw_email.get('has_attachments', False),
                'is_read': raw_email.get('is_read', True),
                'chunk_count': len(enriched_chunks),
            }
        )
