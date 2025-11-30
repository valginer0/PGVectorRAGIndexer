import logging
from PySide6.QtCore import QThread, Signal

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
        """
        super().__init__()
        self.api_client = api_client
        self.files_data = files_data
        self.is_cancelled = False

    def run(self):
        for i, file_data in enumerate(self.files_data):
            if self.is_cancelled:
                break
                
            file_path = file_data['path']
            full_path = file_data['full_path']
            force_reindex = file_data['force_reindex']
            document_type = file_data.get('document_type')
            
            try:
                # Check if exists
                if not force_reindex:
                    exists = self.api_client.check_document_exists(full_path)
                    if exists:
                        self.file_finished.emit(i, True, "Document already exists (skipped)")
                        continue

                self.progress.emit(f"Uploading {file_path.name}...")
                
                # Upload
                self.api_client.upload_document(
                    file_path=file_path,
                    custom_source_uri=full_path,
                    force_reindex=force_reindex,
                    document_type=document_type
                )
                
                self.file_finished.emit(i, True, "Upload successful")
                
            except Exception as e:
                logger.error(f"Upload failed for {file_path}: {e}")
                self.file_finished.emit(i, False, str(e))
        
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
