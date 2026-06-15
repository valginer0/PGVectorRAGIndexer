"""
Shared document write transaction for PostgreSQL + LanceDB indexing.

This module keeps the replacement/rollback sequence in one place so the
URI indexer and HTTP upload route cannot drift on safety-critical behavior.
"""

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


ChunkTuple = tuple[str, int, str, str, Any, Optional[dict[str, Any]]]


def write_indexed_document(
    *,
    repository: Any,
    document_id: str,
    source_uri: str,
    chunks_data: Iterable[ChunkTuple],
    doc_metadata: dict[str, Any],
    replace_existing: bool,
    lancedb_enabled: bool,
    rebuild_fts: bool = True,
    operation_label: str = "document",
) -> None:
    """
    Store indexed chunks in PostgreSQL and the derived LanceDB index.

    If replacing an existing document, the old PostgreSQL chunks are backed up
    and restored if the replacement fails after deletion. LanceDB cleanup is
    best-effort; count drift then lets the repair sync restore from PostgreSQL.
    """
    chunks = list(chunks_data)
    mutation_active = bool(lancedb_enabled)
    if mutation_active:
        from retriever_v2 import begin_lancedb_mutation
        begin_lancedb_mutation()

    postgres_inserted = False
    old_deleted = False
    old_chunks_backup: list[Any] = []
    try:
        if replace_existing:
            logger.info("Removing existing document: %s", document_id)
            old_chunks_backup = repository.get_document_chunks_for_reinsert(document_id)
            repository.delete_document(document_id)
            old_deleted = True

        logger.info("Storing %s chunks in database...", len(chunks))
        repository.insert_chunks(chunks)
        postgres_inserted = True

        if lancedb_enabled:
            from services import get_lancedb_adapter
            lancedb_adapter = get_lancedb_adapter()

            lancedb_chunks = [
                (chunk_index, text_content, embedding, chunk_metadata)
                for (
                    _doc_id,
                    chunk_index,
                    text_content,
                    _chunk_source_uri,
                    embedding,
                    chunk_metadata,
                ) in chunks
            ]
            aggregated_text = "\n\n".join(item[2] for item in chunks)

            lancedb_adapter.upsert_document(
                document_id=document_id,
                source_uri=source_uri,
                chunks=lancedb_chunks,
                aggregated_text=aggregated_text,
                doc_metadata=doc_metadata,
            )
            if rebuild_fts:
                lancedb_adapter.rebuild_fts_index(parent_only=True)

        from retriever_v2 import invalidate_lancedb_cache
        invalidate_lancedb_cache()
    except Exception as e:
        logger.error(
            "Failed to index %s into LanceDB-backed stores: %s. "
            "Rolling back PostgreSQL if needed...",
            operation_label,
            e,
            exc_info=True,
        )
        if postgres_inserted or old_deleted:
            try:
                repository.delete_document(document_id)
                if old_chunks_backup:
                    repository.insert_chunks(old_chunks_backup)
                    logger.info(
                        "Restored previous version of document %s (%s chunks) "
                        "after failed replacement",
                        document_id,
                        len(old_chunks_backup),
                    )
            except Exception as rollback_err:
                logger.critical(
                    "PostgreSQL rollback failed for document %s: %s",
                    document_id,
                    rollback_err,
                    exc_info=True,
                )
            if old_chunks_backup and lancedb_enabled:
                try:
                    from services import get_lancedb_adapter
                    get_lancedb_adapter().delete_document(document_id)
                except Exception as lancedb_err:
                    logger.warning(
                        "Could not remove partial LanceDB replacement for %s: %s",
                        document_id,
                        lancedb_err,
                    )
        from retriever_v2 import invalidate_lancedb_cache
        invalidate_lancedb_cache()
        raise
    finally:
        if mutation_active:
            from retriever_v2 import end_lancedb_mutation
            end_lancedb_mutation()
