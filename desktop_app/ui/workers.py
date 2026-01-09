import logging
import time
from PySide6.QtCore import QThread, Signal
from desktop_app.utils.hashing import calculate_file_hash

logger = logging.getLogger(__name__)

class SearchWorker(QThread):
    """Worker thread for performing searches."""
    finished = Signal(bool, object)

    def __init__(self, api_client, query, top_k, min_score, metric, document_type=None):
        super().__init__()
        self.api_client = api_client
        self.query = query
        self.top_k = top_k
        self.min_score = min_score
        self.metric = metric
        self.document_type = document_type

    def run(self):
        try:
            results = self.api_client.search(
                self.query,
                top_k=self.top_k,
                min_score=self.min_score,
                metric=self.metric,
                document_type=self.document_type
            )
            self.finished.emit(True, results)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            self.finished.emit(False, str(e))

class DocumentsWorker(QThread):
    """Worker thread for loading documents."""
    finished = Signal(bool, object)

    def __init__(self, api_client, params):
        super().__init__()
        self.api_client = api_client
        self.params = params

    def run(self):
        try:
            results = self.api_client.list_documents(**self.params)
            self.finished.emit(True, results)
        except Exception as e:
            logger.error(f"Load documents failed: {e}")
            self.finished.emit(False, str(e))

class DeleteWorker(QThread):
    """Worker thread for deleting a document."""
    finished = Signal(bool, str)

    def __init__(self, api_client, document_id):
        super().__init__()
        self.api_client = api_client
        self.document_id = document_id

    def run(self):
        try:
            self.api_client.delete_document(self.document_id)
            self.finished.emit(True, "Document deleted successfully")
        except Exception as e:
            logger.error(f"Delete document failed: {e}")
            self.finished.emit(False, str(e))

class UploadWorker(QThread):
    """Worker thread for uploading multiple documents."""
    file_finished = Signal(int, bool, str)  # index, success, message
    all_finished = Signal()
    progress = Signal(str)

    def __init__(self, api_client, files_data):
        """
        Initialize worker.
        
        Args:
            api_client: API client instance
            files_data: List of dicts containing:
                - path: Path object
                - full_path: str
                - force_reindex: bool
                - document_type: str (optional)
                - ocr_mode: str (optional) - 'auto', 'skip', or 'only'
        """
        super().__init__()
        self.api_client = api_client
        self.files_data = files_data
        self.is_cancelled = False

    def run(self):
        # Timing instrumentation
        total_metadata_time = 0.0
        total_hash_time = 0.0
        total_upload_time = 0.0
        skipped_count = 0
        uploaded_count = 0
        
        for i, file_data in enumerate(self.files_data):
            if self.is_cancelled:
                break
                
            file_path = file_data['path']
            full_path = file_data['full_path']
            force_reindex = file_data['force_reindex']
            document_type = file_data.get('document_type')
            ocr_mode = file_data.get('ocr_mode', 'auto')
            
            try:
                # Check if exists and compare hash
                needs_force_reindex = force_reindex  # Start with user's setting
                if not force_reindex:
                    # Get remote document metadata
                    t0 = time.perf_counter()
                    doc = self.api_client.get_document_metadata(full_path)
                    total_metadata_time += time.perf_counter() - t0
                    
                    if doc:
                        # Check hash
                        metadata = doc.get('metadata') or {}
                        remote_hash = metadata.get('file_hash')
                        remote_type = metadata.get('type')
                        
                        # Calculate local hash
                        self.progress.emit(f"Checking existing document: {file_path.name}...")
                        t0 = time.perf_counter()
                        local_hash = calculate_file_hash(file_path)
                        total_hash_time += time.perf_counter() - t0
                        
                        hash_match = (remote_hash and remote_hash == local_hash)
                        
                        # If user specified a type, ensure it matches remote, otherwise we must update
                        type_match = True
                        if document_type:
                            type_match = (remote_type == document_type)

                        if hash_match and type_match:
                            self.file_finished.emit(i, True, "Document unchanged (skipped)")
                            skipped_count += 1
                            continue
                        
                        # Hash or type mismatch detected - force reindex for this file
                        needs_force_reindex = True
                    # If document doesn't exist (doc is None), no need to force reindex

                self.progress.emit(f"Uploading {file_path.name}...")
                
                # Upload (use needs_force_reindex which is True if hash/type mismatch detected)
                file_start_time = time.perf_counter()
                self.api_client.upload_document(
                    file_path=file_path,
                    custom_source_uri=full_path,
                    force_reindex=needs_force_reindex,
                    document_type=document_type,
                    ocr_mode=ocr_mode
                )
                file_elapsed = time.perf_counter() - file_start_time
                total_upload_time += file_elapsed
                uploaded_count += 1
                
                # Include timing in success message
                if file_elapsed < 60:
                    time_str = f"{file_elapsed:.1f}s"
                else:
                    time_str = f"{file_elapsed/60:.1f}m"
                self.file_finished.emit(i, True, f"Upload successful ({time_str})")
                
            except Exception as e:
                error_msg = str(e)
                is_encrypted = False
                
                # For HTTP errors, check response body for encrypted_pdf error type
                # because exception message doesn't include response content
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        response_json = e.response.json()
                        detail = response_json.get('detail', {})
                        if isinstance(detail, dict):
                            error_type = detail.get('error_type', '')
                            if error_type == 'encrypted_pdf':
                                is_encrypted = True
                                error_msg = detail.get('message', error_msg)
                    except Exception:
                        pass  # Response wasn't JSON
                
                # Fallback: check message for encrypted/password keywords
                if not is_encrypted and "403" in str(e):
                    if "encrypted" in error_msg.lower() or "password" in error_msg.lower():
                        is_encrypted = True
                
                if is_encrypted:
                    error_msg = f"[ENCRYPTED_PDF]{full_path}|{error_msg}"
                
                logger.error(f"Upload failed for {file_path}: {e}")
                self.file_finished.emit(i, False, error_msg)
        
        # Log timing summary
        total_files = len(self.files_data)
        logger.info(f"\n=== UPLOAD TIMING SUMMARY ===")
        logger.info(f"Total files: {total_files} (uploaded: {uploaded_count}, skipped: {skipped_count})")
        logger.info(f"Metadata API calls: {total_metadata_time:.2f}s ({total_metadata_time/max(total_files,1)*1000:.1f}ms avg)")
        logger.info(f"Local hash calc:    {total_hash_time:.2f}s ({total_hash_time/max(skipped_count,1)*1000:.1f}ms avg per skipped)")
        logger.info(f"Actual uploads:     {total_upload_time:.2f}s ({total_upload_time/max(uploaded_count,1)*1000:.1f}ms avg)")
        logger.info(f"=============================\n")
        
        # Also emit to UI
        self.progress.emit(f"⏱️ Timing: metadata={total_metadata_time:.1f}s, hash={total_hash_time:.1f}s, upload={total_upload_time:.1f}s")
        
        self.all_finished.emit()

    def cancel(self):
        self.is_cancelled = True

class StatsWorker(QThread):
    """Worker thread for loading database statistics."""
    finished = Signal(bool, object)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        try:
            stats = self.api_client.get_statistics()
            self.finished.emit(True, stats)
        except Exception as e:
            logger.error(f"Load statistics failed: {e}")
            self.finished.emit(False, str(e))

    def cancel(self):
        self.is_cancelled = True
