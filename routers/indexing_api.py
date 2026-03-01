"""
Indexing and Document Locking routes for PGVectorRAGIndexer.
"""

import logging
import os
import tempfile
import hashlib
from datetime import datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Request, Query

from api_models import IndexRequest, IndexResponse
from services import get_indexer, encrypted_pdfs_encountered
from auth import require_api_key
from document_processor import UnsupportedFormatError, DocumentProcessingError, EncryptedPDFError

logger = logging.getLogger(__name__)

indexing_router = APIRouter(tags=["Indexing"])


@indexing_router.post("/index", response_model=IndexResponse, dependencies=[Depends(require_api_key)])
async def index_document(request: IndexRequest):
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


@indexing_router.post("/upload-and-index", response_model=IndexResponse, dependencies=[Depends(require_api_key)])
async def upload_and_index(
    file: UploadFile = File(...),
    force_reindex: Any = Form(default=False),
    custom_source_uri: Optional[str] = Form(default=None),
    document_type: Optional[str] = Form(default=None),
    ocr_mode: Optional[str] = Form(default=None)
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
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            # Write uploaded content to temp file
            content = await file.read()
            temp_file.write(content)
        
        logger.info(f"Uploaded file: {file.filename} ({len(content)} bytes) -> {temp_path}")
        
        # Determine the source URI to use (custom path or filename)
        display_name = custom_source_uri if custom_source_uri else file.filename
        logger.info(f"upload_and_index: force_reindex={force_reindex} (type={type(force_reindex)})")
        
        # Process the file using temp path, but with custom source_uri for document_id
        idx = get_indexer()
        
        # Process document from temp file
        metadata = {
            'upload_method': 'http_upload',
            'original_filename': file.filename,
            'temp_path': temp_path
        }
        
        # Add document type if provided
        if document_type:
            metadata['type'] = document_type
        
        processed_doc = idx.processor.process(
            source_uri=temp_path,
            custom_metadata=metadata,
            ocr_mode=ocr_mode  # Pass OCR mode to processor
        )
        
        # Regenerate document_id based on the display name (not temp path)
        processed_doc.document_id = hashlib.sha256(display_name.encode()).hexdigest()[:16]
        processed_doc.source_uri = display_name
        processed_doc.metadata['source_uri'] = display_name
        processed_doc.metadata['document_id'] = processed_doc.document_id
        if custom_source_uri:
            processed_doc.metadata['custom_source_uri'] = custom_source_uri
        
        # Check if document already exists
        if not force_reindex and idx.repository.document_exists(processed_doc.document_id):
            complete_run(run_id, status="success", files_scanned=1, files_skipped=1)
            return IndexResponse(
                status='skipped',
                document_id=processed_doc.document_id,
                source_uri=processed_doc.source_uri,
                chunks_indexed=0,
                message='Document already indexed (use force_reindex=true to reindex)'
            )
        
        # Delete existing if force reindex
        if force_reindex and idx.repository.document_exists(processed_doc.document_id):
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
        
        # Insert into database
        logger.info(f"Storing {len(chunks_data)} chunks in database...")
        idx.repository.insert_chunks(chunks_data)
        
        logger.info(f"✓ Successfully indexed document: {processed_doc.document_id}")
        
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
            "detected_at": datetime.utcnow().isoformat()
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
        
        if (
            file.filename
            and file.filename.lower().endswith(".doc")
            and "convert" not in error_message.lower()
        ):
            error_message = (
                "Legacy .doc format is not supported automatically. "
                "Please install LibreOffice/soffice for conversion or convert the document to .docx."
            )
        
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
