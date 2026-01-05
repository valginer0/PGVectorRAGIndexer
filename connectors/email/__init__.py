# Email Connector Package (Provider-Agnostic Base)
# This module provides reusable infrastructure for email indexing.
# Provider-specific implementations (Gmail, Outlook, IMAP) extend this base.

from .processor import EmailProcessor
from .retriever import EmailSearchResult, search_emails

__all__ = ['EmailProcessor', 'EmailSearchResult', 'search_emails']
