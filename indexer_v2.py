"""
Improved document indexer with deduplication, metadata support, and better error handling.

This is the v2 indexer that uses the new modular architecture.
"""

import argparse
import logging
import sys
from typing import Optional, List, Dict, Any
from datetime import datetime

from config import get_config
from database import get_db_manager, DocumentRepository
from embeddings import get_embedding_service
from document_processor import DocumentProcessor, convert_windows_path, DocumentProcessingError, EncryptedPDFError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DocumentIndexer:
    """
    Main indexer class for processing and storing documents.
    
    Handles document loading, embedding generation, and database storage
    with deduplication and metadata support.
    """
    
    def __init__(self):
        """Initialize indexer with required services."""
        self.config = get_config()
        self.db_manager = get_db_manager()
        self.repository = DocumentRepository(self.db_manager)
        self.embedding_service = get_embedding_service()
        self.processor = DocumentProcessor()
    
    def _log_encrypted_pdf(self, source_uri: str):
        """Log encrypted PDF to file for headless mode tracking."""
        from pathlib import Path
        log_file = Path("encrypted_pdfs.log")
        timestamp = datetime.utcnow().isoformat()
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp}\t{source_uri}\n")
            logger.info(f"Logged encrypted PDF to {log_file}")
        except Exception as e:
            logger.warning(f"Failed to log encrypted PDF: {e}")
    
    def index_document(
        self,
        source_uri: str,
        force_reindex: bool = False,
        custom_metadata: Optional[Dict[str, Any]] = None,
        ocr_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Index a single document.
        
        Args:
            source_uri: Path or URL to document
            force_reindex: If True, reindex even if document exists
            custom_metadata: Optional custom metadata
            ocr_mode: OCR mode ('skip', 'only', 'auto', or None for config default)
            
        Returns:
            Dictionary with indexing results
        """
        try:
            # Process document
            logger.info(f"Processing document: {source_uri}")
            processed_doc = self.processor.process(source_uri, custom_metadata, ocr_mode=ocr_mode)
            
            # Check if document already exists
            existing_doc = self.repository.get_document_by_id(processed_doc.document_id)
            if existing_doc:
                if not force_reindex:
                    # Check for file hash match
                    existing_hash = existing_doc.get('metadata', {}).get('file_hash')
                    new_hash = processed_doc.metadata.get('file_hash')
                    
                    if new_hash and existing_hash and new_hash == existing_hash:
                        logger.info(
                            f"Document {processed_doc.document_id} unchanged (Hash match). Skipping."
                        )
                        return {
                            'status': 'skipped',
                            'document_id': processed_doc.document_id,
                            'reason': 'unchanged',
                            'message': 'Document content unchanged (skip)'
                        }
                    
                    if new_hash and existing_hash:
                        logger.info(f"Document content changed (Hash mismatch). Reindexing.")
                    else:
                        logger.info(f"Document exists but hash missing. Reindexing.")

                # If we are here, we are reindexing (either forced or changed)
                logger.info(f"Removing existing document: {processed_doc.document_id}")
                self.repository.delete_document(processed_doc.document_id)
            
            # Generate embeddings
            logger.info(f"Generating embeddings for {len(processed_doc.chunks)} chunks...")
            chunk_texts = processed_doc.get_chunk_texts()
            embeddings = self.embedding_service.encode_batch(
                chunk_texts,
                show_progress=True
            )
            
            # Prepare chunks for insertion
            chunks_data = []
            for i, (chunk, embedding) in enumerate(zip(processed_doc.chunks, embeddings)):
                # Extract metadata from chunk or use empty dict
                chunk_metadata = chunk.metadata if hasattr(chunk, 'metadata') else {}
                chunks_data.append((
                    processed_doc.document_id,
                    i,
                    chunk.page_content,
                    processed_doc.source_uri,
                    embedding,
                    chunk_metadata  # Add metadata as 6th element
                ))
            
            # Insert into database
            logger.info(f"Storing {len(chunks_data)} chunks in database...")
            self.repository.insert_chunks(chunks_data)
            
            logger.info(f"✓ Successfully indexed document: {processed_doc.document_id}")
            
            return {
                'status': 'success',
                'document_id': processed_doc.document_id,
                'source_uri': source_uri,
                'chunks_indexed': len(chunks_data),
                'metadata': processed_doc.metadata,
                'indexed_at': processed_doc.processed_at.isoformat()
            }
            
        except EncryptedPDFError as e:
            # Log encrypted PDFs to a separate file for headless tracking
            logger.warning(f"🔒 Encrypted PDF skipped: {source_uri}")
            self._log_encrypted_pdf(source_uri)
            return {
                'status': 'error',
                'error_type': 'encrypted_pdf',
                'source_uri': source_uri,
                'message': str(e)
            }
        except DocumentProcessingError as e:
            logger.error(f"Document processing failed: {e}")
            return {
                'status': 'error',
                'error_type': 'processing_error',
                'message': str(e)
            }
        except Exception as e:
            logger.error(f"Indexing failed: {e}", exc_info=True)
            return {
                'status': 'error',
                'error_type': 'unknown_error',
                'message': str(e)
            }
    
    def index_batch(
        self,
        source_uris: List[str],
        force_reindex: bool = False,
        custom_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Index multiple documents.
        
        Args:
            source_uris: List of paths or URLs
            force_reindex: If True, reindex existing documents
            custom_metadata: Optional custom metadata for all documents
            
        Returns:
            List of indexing results
        """
        results = []
        
        for source_uri in source_uris:
            result = self.index_document(source_uri, force_reindex, custom_metadata)
            results.append(result)
        
        # Summary
        successful = sum(1 for r in results if r['status'] == 'success')
        skipped = sum(1 for r in results if r['status'] == 'skipped')
        failed = sum(1 for r in results if r['status'] == 'error')
        
        logger.info(
            f"\nBatch indexing complete: "
            f"{successful} successful, {skipped} skipped, {failed} failed"
        )
        
        return results
    
    def list_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List indexed documents.
        
        Args:
            limit: Maximum number of documents to return
            
        Returns:
            List of document metadata
        """
        return self.repository.list_documents(limit=limit)
    
    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document by ID.
        
        Args:
            document_id: Document identifier
            
        Returns:
            True if deleted, False if not found
        """
        if not self.repository.document_exists(document_id):
            logger.warning(f"Document not found: {document_id}")
            return False
        
        deleted_count = self.repository.delete_document(document_id)
        logger.info(f"Deleted document {document_id} ({deleted_count} chunks)")
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get indexing statistics.
        
        Returns:
            Dictionary with statistics
        """
        stats = self.repository.get_statistics()
        db_health = self.db_manager.health_check()
        model_info = self.embedding_service.get_model_info()
        
        return {
            'database': stats,
            'health': db_health,
            'embedding_model': model_info,
            'configuration': {
                'chunk_size': self.config.chunking.size,
                'chunk_overlap': self.config.chunking.overlap,
                'embedding_dimension': self.config.embedding.dimension
            }
        }


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description='PGVectorRAGIndexer v2 - Index documents for semantic search',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index a single document
  python indexer_v2.py index document.pdf
  
  # Index with Windows path (auto-converted to WSL)
  python indexer_v2.py index "C:\\Users\\Name\\document.pdf"
  
  # Index a web URL
  python indexer_v2.py index https://example.com/article
  
  # Force reindex existing document
  python indexer_v2.py index document.pdf --force
  
  # List indexed documents
  python indexer_v2.py list
  
  # Delete a document
  python indexer_v2.py delete <document_id>
  
  # Show statistics
  python indexer_v2.py stats
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Index command
    index_parser = subparsers.add_parser('index', help='Index a document')
    index_parser.add_argument(
        'source',
        type=str,
        help='Path or URL to document'
    )
    index_parser.add_argument(
        '--force',
        action='store_true',
        help='Force reindex if document already exists'
    )
    index_parser.add_argument(
        '--ocr-mode',
        choices=['skip', 'only', 'auto'],
        default=None,
        help='OCR processing mode: skip=no OCR, only=OCR-required files only, auto=smart fallback (default: from config)'
    )
    
    # List command
    list_parser = subparsers.add_parser('list', help='List indexed documents')
    list_parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of documents to list'
    )
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a document')
    delete_parser.add_argument(
        'document_id',
        type=str,
        help='Document ID to delete'
    )
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize indexer
    try:
        indexer = DocumentIndexer()
    except Exception as e:
        logger.error(f"Failed to initialize indexer: {e}")
        sys.exit(1)
    
    # Execute command
    try:
        if args.command == 'index':
            # Convert Windows path if needed
            source = convert_windows_path(args.source)
            
            # Get OCR mode from args (None uses config default)
            ocr_mode = getattr(args, 'ocr_mode', None)
            
            result = indexer.index_document(source, force_reindex=args.force, ocr_mode=ocr_mode)
            
            if result['status'] == 'success':
                print(f"\n✓ Document indexed successfully!")
                print(f"  Document ID: {result['document_id']}")
                print(f"  Chunks: {result['chunks_indexed']}")
            elif result['status'] == 'skipped':
                print(f"\n⊘ {result['message']}")
            else:
                print(f"\n✗ Indexing failed: {result['message']}")
                sys.exit(1)
        
        elif args.command == 'list':
            documents = indexer.list_documents(limit=args.limit)
            
            if not documents:
                print("\nNo documents indexed yet.")
            else:
                print(f"\nIndexed Documents ({len(documents)}):")
                print("-" * 80)
                for doc in documents:
                    print(f"ID: {doc['document_id']}")
                    print(f"  Source: {doc['source_uri']}")
                    print(f"  Chunks: {doc['chunk_count']}")
                    print(f"  Indexed: {doc['indexed_at']}")
                    print()
        
        elif args.command == 'delete':
            if indexer.delete_document(args.document_id):
                print(f"\n✓ Document deleted: {args.document_id}")
            else:
                print(f"\n✗ Document not found: {args.document_id}")
                sys.exit(1)
        
        elif args.command == 'stats':
            stats = indexer.get_statistics()
            
            print("\n=== Database Statistics ===")
            print(f"Total Documents: {stats['database']['total_documents']}")
            print(f"Total Chunks: {stats['database']['total_chunks']}")
            print(f"Avg Chunks/Document: {stats['database']['avg_chunks_per_document']}")
            print(f"Database Size: {stats['database']['database_size']}")
            
            print("\n=== Embedding Model ===")
            print(f"Model: {stats['embedding_model']['model_name']}")
            print(f"Dimension: {stats['embedding_model']['dimension']}")
            print(f"Device: {stats['embedding_model']['device']}")
            print(f"Cache Size: {stats['embedding_model']['cache_size']}")
            
            print("\n=== Configuration ===")
            print(f"Chunk Size: {stats['configuration']['chunk_size']}")
            print(f"Chunk Overlap: {stats['configuration']['chunk_overlap']}")
            
            print("\n=== Health Status ===")
            print(f"Status: {stats['health']['status']}")
    
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
