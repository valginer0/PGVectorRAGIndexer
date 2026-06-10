"""
Indexing and Document Locking routes for PGVectorRAGIndexer.
"""

import logging
import os
import tempfile
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Any
import xxhash
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Request, Query

from api_models import IndexRequest, IndexResponse
from services import get_indexer, encrypted_pdfs_encountered
from auth import require_api_key
from document_processor import (
    UnsupportedFormatError,
    DocumentProcessingError,
    EncryptedPDFError,
)

logger = logging.getLogger(__name__)

indexing_router = APIRouter(tags=["Indexing"])


def _assign_owner_if_authenticated(key_record: Optional[dict], document_id: Optional[str]) -> None:
    """Auto-assign document ownership to the uploading user (auth mode only).

    Best-effort: a failure leaves the document with the default shared
    visibility (same as before this feature) and must not fail the indexing
    that already succeeded.
    """
    if not document_id:
        return
    try:
        from document_visibility import resolve_user_id_for_key_record, set_document_owner
        user_id = resolve_user_id_for_key_record(key_record)
        if user_id:
            set_document_owner(document_id, user_id)
            logger.info(f"Assigned owner {user_id} to document {document_id}")
    except Exception as e:
        logger.warning(f"Could not auto-assign owner for document {document_id}: {e}")


@indexing_router.post("/index", response_model=IndexResponse)
async def index_document(
    request: IndexRequest,
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Index a document from URI."""
    from indexing_runs import start_run, complete_run
    run_id = start_run(trigger="api", source_uri=request.source_uri)
    try:
        idx = get_indexer()
        result = idx.index_document(
            source_uri=request.source_uri,
            force_reindex=request.force_reindex,
            custom_metadata=request.metadata
        )

        if result['status'] == 'error':
            complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                         errors=[{"source_uri": request.source_uri, "error": result.get('message', '')}])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result['message']
            )

        added = 1 if result.get('status') == 'success' else 0
        skipped = 1 if result.get('status') == 'skipped' else 0
        if added:
            _assign_owner_if_authenticated(key_record, result.get('document_id'))
        complete_run(run_id, status="success", files_scanned=1,
                     files_added=added, files_skipped=skipped)
        return IndexResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": request.source_uri, "error": str(e)}])
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Indexing failed: {str(e)}"
        )


@indexing_router.post("/upload-and-index", response_model=IndexResponse)
async def upload_and_index(
    file: UploadFile = File(...),
    force_reindex: Any = Form(default=False),
    custom_source_uri: Optional[str] = Form(default=None),
    document_type: Optional[str] = Form(default=None),
    metadata_json: Optional[str] = Form(default=None, alias="metadata"),
    ocr_mode: Optional[str] = Form(default=None),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """
    Upload a file and index it immediately.
    """
    from indexing_runs import start_run, complete_run

    # Robust bool conversion for Form data
    if isinstance(force_reindex, str):
        force_reindex = force_reindex.lower() in ("true", "1", "t", "y", "yes")

    source = custom_source_uri or file.filename or "upload"
    run_id = start_run(trigger="upload", source_uri=source)
    temp_path = None
    try:
        # Create temporary file with original extension
        suffix = os.path.splitext(file.filename)[1] if file.filename else '.tmp'
        bytes_written = 0
        hasher = xxhash.xxh64()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                hasher.update(chunk)
                temp_file.write(chunk)
        uploaded_file_hash = hasher.hexdigest()

        logger.info(f"Uploaded file: {file.filename} ({bytes_written} bytes) -> {temp_path}")

        # Determine the source URI to use (custom path or filename)
        display_name = custom_source_uri or file.filename or "upload"
        logger.info(f"upload_and_index: force_reindex={force_reindex} (type={type(force_reindex)})")

        # Process the file using temp path, but with custom source_uri for document_id
        idx = get_indexer()
        document_id = hashlib.sha256(display_name.encode()).hexdigest()[:16]

        user_metadata: dict[str, Any] = {}
        if metadata_json:
            try:
                parsed_metadata = json.loads(metadata_json)
                if not isinstance(parsed_metadata, dict):
                    raise ValueError("metadata must be a JSON object")
                user_metadata = parsed_metadata
            except (TypeError, ValueError, json.JSONDecodeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid metadata JSON: {e}",
                )
        if (
            document_type
            and user_metadata.get("type") is not None
            and user_metadata.get("type") != document_type
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="document_type conflicts with metadata.type",
            )

        metadata = dict(user_metadata)
        metadata.update({
            'upload_method': 'http_upload',
            'original_filename': file.filename,
            'display_name': display_name,
            'file_hash': uploaded_file_hash,
            'temp_path': temp_path
        })
        if custom_source_uri:
            metadata['custom_source_uri'] = custom_source_uri

        # document_type is the explicit form-field override for metadata.type.
        if document_type:
            metadata['type'] = document_type

        existing_doc = idx.repository.get_document_by_id(document_id)
        if not force_reindex and existing_doc:
            existing_hash = (existing_doc.get('metadata') or {}).get('file_hash')
            if existing_hash and existing_hash == uploaded_file_hash:
                complete_run(run_id, status="success", files_scanned=1, files_skipped=1)
                return IndexResponse(
                    status='skipped',
                    document_id=document_id,
                    source_uri=display_name,
                    chunks_indexed=0,
                    message='Document already indexed with matching file hash'
                )
            logger.info(
                "Existing upload %s will be reindexed because file hash changed or is missing",
                document_id,
            )

        # Process document from temp file
        processed_doc = idx.processor.process(
            source_uri=temp_path,
            custom_metadata=metadata,
            ocr_mode=ocr_mode  # Pass OCR mode to processor
        )

        # Regenerate document_id based on the display name (not temp path)
        processed_doc.document_id = document_id
        processed_doc.source_uri = display_name
        processed_doc.metadata['source_uri'] = display_name
        processed_doc.metadata['document_id'] = processed_doc.document_id
        if custom_source_uri:
            processed_doc.metadata['custom_source_uri'] = custom_source_uri

        # Delete existing document before replacing it when force reindexing or
        # when the uploaded file hash differs from the indexed metadata.
        if existing_doc:
            logger.info(f"Removing existing document: {processed_doc.document_id}")
            idx.repository.delete_document(processed_doc.document_id)

        # Generate embeddings
        logger.info(f"Generating embeddings for {len(processed_doc.chunks)} chunks...")
        chunk_texts = processed_doc.get_chunk_texts()
        embeddings = idx.embedding_service.encode_batch(chunk_texts, show_progress=False)

        # Prepare chunks for insertion
        chunks_data = []
        for i, (chunk, embedding) in enumerate(zip(processed_doc.chunks, embeddings)):
            chunks_data.append((
                processed_doc.document_id,
                i,
                chunk.page_content,
                processed_doc.source_uri,  # This is now the original filename
                embedding,
                processed_doc.metadata  # Include metadata
            ))

        from config import get_config
        config = get_config()
        mutation_active = bool(getattr(config.retrieval, "lancedb_enabled", False))
        if mutation_active:
            from retriever_v2 import begin_lancedb_mutation
            begin_lancedb_mutation()
        postgres_inserted = False
        try:
            # Insert into database
            logger.info(f"Storing {len(chunks_data)} chunks in database...")
            idx.repository.insert_chunks(chunks_data)
            postgres_inserted = True

            # Dual-write to LanceDB if enabled
            if getattr(config.retrieval, "lancedb_enabled", False):
                from services import get_lancedb_adapter
                lancedb_adapter = get_lancedb_adapter()

                lancedb_chunks = []
                for item in chunks_data:
                    # item format: (doc_id, chunk_index, text_content, source_uri, embedding, chunk_metadata)
                    lancedb_chunks.append((item[1], item[2], item[4], item[5]))

                aggregated_text = "\n\n".join(item[2] for item in chunks_data)

                lancedb_adapter.upsert_document(
                    document_id=processed_doc.document_id,
                    source_uri=processed_doc.source_uri,
                    chunks=lancedb_chunks,
                    aggregated_text=aggregated_text,
                    doc_metadata=processed_doc.metadata
                )
                # Rebuild FTS index on parent table for freshness
                lancedb_adapter.rebuild_fts_index(parent_only=True)

            # Invalidate readiness cache on successful write
            from retriever_v2 import invalidate_lancedb_cache
            invalidate_lancedb_cache()
        except Exception as e:
            logger.error(f"Failed to index uploaded document into LanceDB-backed stores: {e}. Rolling back PostgreSQL if needed...", exc_info=True)
            if postgres_inserted:
                try:
                    idx.repository.delete_document(processed_doc.document_id)
                except Exception as rollback_err:
                    logger.critical(f"PostgreSQL rollback delete failed for document {processed_doc.document_id}: {rollback_err}", exc_info=True)
            from retriever_v2 import invalidate_lancedb_cache
            invalidate_lancedb_cache()
            raise
        finally:
            if mutation_active:
                from retriever_v2 import end_lancedb_mutation
                end_lancedb_mutation()

        logger.info(f"✓ Successfully indexed document: {processed_doc.document_id}")

        _assign_owner_if_authenticated(key_record, processed_doc.document_id)
        complete_run(run_id, status="success", files_scanned=1,
                     files_added=1 if not force_reindex else 0,
                     files_updated=1 if force_reindex else 0)
        return IndexResponse(
            status='success',
            document_id=processed_doc.document_id,
            source_uri=processed_doc.source_uri,
            chunks_indexed=len(chunks_data)
        )

    except HTTPException:
        raise
    except EncryptedPDFError as e:
        from errors import raise_api_error, ErrorCode
        # Return 403 with specific error type for encrypted PDFs
        source = custom_source_uri or file.filename
        logger.warning(f"Encrypted PDF detected: {source}")

        # Record for later querying
        encrypted_pdfs_encountered.append({
            "source_uri": source,
            "filename": file.filename,
            "detected_at": datetime.now(timezone.utc).isoformat()
        })

        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": "encrypted_pdf"}])

        raise_api_error(
            ErrorCode.ENCRYPTED_PDF,
            message=str(e),
            details={"source_uri": source}
        )
    except (UnsupportedFormatError, DocumentProcessingError) as e:
        from errors import raise_api_error, ErrorCode
        error_message = str(e) if str(e) else ""

        # Check if this is an OCR mode "only" skip (not an error, just skipped)
        if error_message.startswith("Skipped:"):
            logger.info(f"File skipped due to OCR mode: {file.filename}")
            # Return success with 0 chunks to indicate skip
            complete_run(run_id, status="success", files_scanned=1, files_skipped=1)
            return IndexResponse(
                status='skipped',
                document_id='',
                source_uri=custom_source_uri if custom_source_uri else (file.filename or ''),
                chunks_indexed=0,
                message=error_message
            )

        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": error_message}])
        logger.error(f"Upload and index failed: {e}")

        raise_api_error(
            ErrorCode.UNSUPPORTED_FORMAT if isinstance(e, UnsupportedFormatError) else ErrorCode.DOCUMENT_PROCESSING_FAILED,
            message=error_message,
            details={"source_uri": source}
        )
    except Exception as e:
        from errors import raise_api_error, ErrorCode
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": str(e)}])
        logger.error(f"Upload and index failed: {e}")
        raise_api_error(
            ErrorCode.DOCUMENT_PROCESSING_FAILED,
            message=f"Upload and index failed: {str(e)}",
            details={"source_uri": source}
        )
    finally:
        # Clean up temporary file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_path}: {e}")


@indexing_router.post("/documents/locks/acquire", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def acquire_document_lock(request: Request):
    """Acquire a lock on a document for indexing."""
    from document_locks import acquire_lock
    try:
        body = await request.json()
        source_uri = body.get("source_uri")
        client_id = body.get("client_id")
        if not source_uri or not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_uri and client_id are required",
            )
        result = acquire_lock(
            source_uri=source_uri,
            client_id=client_id,
            ttl_minutes=body.get("ttl_minutes", 10),
            lock_reason=body.get("lock_reason", "indexing"),
        )
        if result["ok"]:
            return result
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to acquire lock: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to acquire lock: {str(e)}",
        )


@indexing_router.post("/documents/locks/release", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def release_document_lock(request: Request):
    """Release a lock on a document."""
    from document_locks import release_lock
    try:
        body = await request.json()
        source_uri = body.get("source_uri")
        client_id = body.get("client_id")
        if not source_uri or not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_uri and client_id are required",
            )
        if release_lock(source_uri, client_id):
            return {"ok": True}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No lock found for {source_uri} by client {client_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to release lock: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release lock: {str(e)}",
        )


@indexing_router.post("/documents/locks/force-release", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def force_release_document_lock(request: Request):
    """Force-release a lock regardless of holder."""
    from document_locks import force_release_lock
    try:
        body = await request.json()
        source_uri = body.get("source_uri")
        if not source_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_uri is required",
            )
        success = force_release_lock(source_uri=source_uri)
        return {"ok": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to force-release lock: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to force-release lock: {str(e)}",
        )


@indexing_router.get("/documents/locks", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def list_document_locks(
    client_id: Optional[str] = Query(default=None),
):
    """List all active document locks."""
    from document_locks import list_locks
    try:
        locks = list_locks(client_id=client_id)
        return {"locks": locks, "count": len(locks)}
    except Exception as e:
        logger.error(f"Failed to list locks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list locks: {str(e)}",
        )


@indexing_router.get("/documents/locks/check", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def check_document_lock(
    source_uri: str = Query(...),
):
    """Check if a specific document is locked."""
    from document_locks import check_lock
    try:
        lock = check_lock(source_uri=source_uri)
        return {"locked": lock is not None, "lock": lock}
    except Exception as e:
        logger.error(f"Failed to check lock: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check lock: {str(e)}",
        )


@indexing_router.post("/documents/locks/cleanup", tags=["Document Locks"], dependencies=[Depends(require_api_key)])
async def cleanup_expired_document_locks():
    """Remove all expired locks."""
    from document_locks import cleanup_expired_locks
    try:
        deleted = cleanup_expired_locks()
        return {"deleted": deleted, "ok": True}
    except Exception as e:
        logger.error(f"Failed to cleanup locks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup locks: {str(e)}",
        )
