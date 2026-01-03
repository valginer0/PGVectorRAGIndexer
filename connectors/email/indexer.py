"""
Email Indexer for storing processed emails in the database.

Handles:
- Embedding generation
- Database insertion into email_chunks table
- Idempotency (skip already indexed emails)
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from .ingestor import CloudIngestor
from .processor import EmailProcessor, ProcessedEmail

logger = logging.getLogger(__name__)


class EmailIndexer:
    """
    Indexes processed emails into the database.
    
    Pipeline: CloudIngestor -> EmailProcessor -> Embeddings -> Database
    """
    
    def __init__(
        self,
        ingestor: CloudIngestor,
        processor: Optional[EmailProcessor] = None,
        embedding_manager=None,
        database_manager=None
    ):
        """
        Initialize the Email Indexer.
        
        Args:
            ingestor: CloudIngestor instance (authenticated)
            processor: EmailProcessor instance (optional, uses defaults)
            embedding_manager: EmbeddingManager from embeddings.py
            database_manager: DatabaseManager from database.py
        """
        self.ingestor = ingestor
        self.processor = processor or EmailProcessor()
        self.embedding_manager = embedding_manager
        self.database_manager = database_manager
        
        # Stats
        self._indexed_count = 0
        self._skipped_count = 0
        self._error_count = 0
    
    def _get_existing_message_ids(self) -> set:
        """Get set of already indexed message IDs."""
        if not self.database_manager:
            return set()
        
        try:
            with self.database_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT message_id FROM email_chunks")
                    return {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching existing message IDs: {e}")
            return set()
    
    def _insert_chunks(self, email: ProcessedEmail, embeddings: List[List[float]]) -> int:
        """
        Insert email chunks into the database.
        
        Args:
            email: Processed email with chunks
            embeddings: List of embedding vectors
        
        Returns:
            Number of chunks inserted
        """
        if not self.database_manager:
            logger.warning("No database manager configured, skipping insert")
            return 0
        
        if not email.chunks:
            return 0
        
        try:
            with self.database_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    for idx, (chunk, embedding) in enumerate(zip(email.chunks, embeddings)):
                        cur.execute("""
                            INSERT INTO email_chunks 
                            (message_id, thread_id, sender, subject, received_at, 
                             chunk_index, text_content, embedding, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (message_id, chunk_index) DO UPDATE SET
                                text_content = EXCLUDED.text_content,
                                embedding = EXCLUDED.embedding,
                                indexed_at = NOW()
                        """, (
                            email.message_id,
                            email.thread_id,
                            email.sender,
                            email.subject,
                            email.received_at,
                            idx,
                            chunk,
                            embedding,
                            email.metadata
                        ))
                conn.commit()
            return len(email.chunks)
        except Exception as e:
            logger.error(f"Error inserting email chunks: {e}")
            raise
    
    def index_folder(
        self,
        folder: str = 'Inbox',
        limit: int = 100,
        since: Optional[datetime] = None,
        skip_existing: bool = True
    ) -> Dict[str, int]:
        """
        Index emails from a mailbox folder.
        
        Args:
            folder: Folder name (Inbox, Sent Items, etc.)
            limit: Maximum emails to process
            since: Only index emails after this date
            skip_existing: Skip already indexed emails
        
        Returns:
            Dict with stats: indexed, skipped, errors
        """
        logger.info(f"Starting indexing of '{folder}' (limit={limit})")
        
        # Get existing IDs for deduplication
        existing_ids = set()
        if skip_existing:
            existing_ids = self._get_existing_message_ids()
            logger.info(f"Found {len(existing_ids)} already indexed emails")
        
        self._indexed_count = 0
        self._skipped_count = 0
        self._error_count = 0
        
        for raw_email in self.ingestor.get_messages(folder=folder, limit=limit, since=since):
            message_id = raw_email.get('id')
            
            # Skip if already indexed
            if message_id in existing_ids:
                self._skipped_count += 1
                continue
            
            try:
                # Process the email
                processed = self.processor.process(raw_email)
                
                if not processed.chunks:
                    self._skipped_count += 1
                    continue
                
                # Generate embeddings
                if self.embedding_manager:
                    embeddings = self.embedding_manager.embed_texts(processed.chunks)
                else:
                    # Placeholder if no embedding manager
                    embeddings = [[0.0] * 384 for _ in processed.chunks]
                    logger.warning("No embedding manager, using zero vectors")
                
                # Insert into database
                inserted = self._insert_chunks(processed, embeddings)
                self._indexed_count += inserted
                
                logger.debug(f"Indexed email: {processed.subject} ({inserted} chunks)")
                
            except Exception as e:
                logger.error(f"Error indexing email {message_id}: {e}")
                self._error_count += 1
        
        stats = {
            'indexed': self._indexed_count,
            'skipped': self._skipped_count,
            'errors': self._error_count
        }
        logger.info(f"Indexing complete: {stats}")
        return stats
    
    def index_all_folders(
        self,
        folders: Optional[List[str]] = None,
        limit_per_folder: int = 100,
        since: Optional[datetime] = None
    ) -> Dict[str, Dict[str, int]]:
        """
        Index multiple folders.
        
        Args:
            folders: List of folder names. If None, indexes Inbox + Sent.
            limit_per_folder: Max emails per folder
            since: Only index emails after this date
        
        Returns:
            Dict mapping folder name to stats
        """
        if folders is None:
            folders = ['Inbox', 'Sent Items']
        
        results = {}
        for folder in folders:
            try:
                results[folder] = self.index_folder(
                    folder=folder,
                    limit=limit_per_folder,
                    since=since
                )
            except Exception as e:
                logger.error(f"Error indexing folder '{folder}': {e}")
                results[folder] = {'indexed': 0, 'skipped': 0, 'errors': 1}
        
        return results
