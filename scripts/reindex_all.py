#!/usr/bin/env python3
"""
Reindex all documents in the database with current chunking settings.

This script fetches all unique source URIs from the database and reindexes
them with the current chunk size configuration.

Usage:
    cd /path/to/PGVectorRAGIndexer
    source venv/bin/activate
    python scripts/reindex_all.py [--dry-run] [--batch-size N]
"""

import argparse
import logging
import sys
from typing import List

from database import get_db_manager, DocumentRepository
from indexer_v2 import DocumentIndexer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_source_uris(repository: DocumentRepository) -> List[str]:
    """Get all unique source URIs from the database."""
    with repository.db.get_cursor(dict_cursor=True) as cursor:
        cursor.execute("""
            SELECT DISTINCT source_uri 
            FROM document_chunks 
            ORDER BY source_uri
        """)
        return [row['source_uri'] for row in cursor.fetchall()]


def reindex_all(dry_run: bool = False, batch_size: int = 10) -> dict:
    """
    Reindex all documents in the database.
    
    Args:
        dry_run: If True, only show what would be reindexed
        batch_size: Number of documents to process before logging progress
        
    Returns:
        Summary dict with success/fail counts
    """
    db_manager = get_db_manager()
    repository = DocumentRepository(db_manager)
    
    # Get all source URIs
    source_uris = get_all_source_uris(repository)
    total = len(source_uris)
    
    logger.info(f"Found {total} documents to reindex")
    
    if dry_run:
        logger.info("DRY RUN - no changes will be made")
        for uri in source_uris[:10]:
            logger.info(f"  Would reindex: {uri}")
        if total > 10:
            logger.info(f"  ... and {total - 10} more")
        return {"total": total, "dry_run": True}
    
    # Initialize indexer
    indexer = DocumentIndexer()
    
    success = 0
    failed = 0
    skipped = 0
    
    for i, source_uri in enumerate(source_uris, 1):
        try:
            result = indexer.index_document(source_uri, force_reindex=True)
            
            if result.get('status') == 'success':
                success += 1
            elif result.get('status') == 'skipped':
                skipped += 1
            else:
                failed += 1
                logger.warning(f"Unexpected result for {source_uri}: {result}")
                
        except FileNotFoundError:
            logger.warning(f"File not found (may have been deleted): {source_uri}")
            skipped += 1
        except Exception as e:
            logger.error(f"Failed to reindex {source_uri}: {e}")
            failed += 1
        
        # Progress logging
        if i % batch_size == 0:
            logger.info(f"Progress: {i}/{total} ({success} success, {failed} failed, {skipped} skipped)")
    
    # Final summary
    summary = {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped
    }
    
    logger.info(f"\n=== Reindex Complete ===")
    logger.info(f"Total: {total}")
    logger.info(f"Success: {success}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped: {skipped}")
    
    return summary


def main():
    parser = argparse.ArgumentParser(
        description='Reindex all documents with current chunking settings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview what would be reindexed
  python scripts/reindex_all.py --dry-run
  
  # Reindex all documents
  python scripts/reindex_all.py
  
  # Reindex with progress every 5 documents
  python scripts/reindex_all.py --batch-size 5
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be reindexed without making changes'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Log progress every N documents (default: 10)'
    )
    
    args = parser.parse_args()
    
    try:
        summary = reindex_all(dry_run=args.dry_run, batch_size=args.batch_size)
        
        if summary.get('failed', 0) > 0:
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("\nReindex cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
