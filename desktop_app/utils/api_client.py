"""
REST API client for communicating with the backend.
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class APIClient:
    """Client for interacting with the PGVectorRAGIndexer REST API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL of the API
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = 30
    
    def is_api_available(self) -> bool:
        """Check if the API is available."""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def upload_document(
        self,
        file_path: Path,
        custom_source_uri: Optional[str] = None,
        force_reindex: bool = False,
        document_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload and index a document.
        
        Args:
            file_path: Path to the file to upload
            custom_source_uri: Custom source URI (full path) to preserve
            force_reindex: Whether to force reindexing if document exists
            document_type: Optional document type/category (e.g., 'resume', 'policy', 'report')
            
        Returns:
            Response data from the API
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Uploading document: {file_path} (type: {document_type})")
        
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f)}
            data = {'force_reindex': str(force_reindex).lower()}
            
            if custom_source_uri:
                data['custom_source_uri'] = custom_source_uri
            
            if document_type:
                data['document_type'] = document_type
            
            response = requests.post(
                f"{self.base_url}/upload-and-index",
                files=files,
                data=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.5,
        metric: str = "cosine",
        document_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum similarity score
            metric: Similarity metric to use
            document_type: Optional filter by document type (deprecated, use filters)
            filters: Optional filter dictionary
            
        Returns:
            List of search results
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Searching for: {query} (filters: {filters or document_type})")
        
        payload = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "metric": metric
        }
        
        # Add filters if specified
        if filters:
            payload["filters"] = filters
        elif document_type:
            # Backward compatibility
            payload["filters"] = {"type": document_type}
        
        response = requests.post(
            f"{self.base_url}/search",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["results"]
    
    def list_documents(self) -> List[Dict[str, Any]]:
        """
        Get list of all documents.
        
        Returns:
            List of documents
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/documents",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_document(self, document_id: str) -> Dict[str, Any]:
        """
        Get a specific document by ID.
        
        Args:
            document_id: Document ID
            
        Returns:
            Document data
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/documents/{document_id}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document.
        
        Args:
            document_id: Document ID to delete
            
        Returns:
            Response data
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Deleting document: {document_id}")
        
        response = requests.delete(
            f"{self.base_url}/documents/{document_id}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Statistics data
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/statistics",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def bulk_delete_preview(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Preview what documents would be deleted with given filters.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Preview data with document count and samples
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters, "preview": True}
        logger.info(f"bulk_delete_preview payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/bulk-delete",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def bulk_delete(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Actually delete documents matching filters.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Delete result with chunks_deleted count
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters, "preview": False}
        logger.info(f"bulk_delete payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/bulk-delete",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def export_documents(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Export documents matching filters as backup.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Export data with backup_data
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters}
        logger.info(f"export_documents payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/export",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def restore_documents(self, backup_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Restore documents from backup.
        
        Args:
            backup_data: Backup data from export_documents
            
        Returns:
            Restore result with chunks_restored count
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.post(
            f"{self.base_url}/documents/restore",
            json={"backup_data": backup_data},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_metadata_keys(self, pattern: Optional[str] = None) -> List[str]:
        """
        Get all unique metadata keys.
        
        Args:
            pattern: Optional SQL LIKE pattern to filter keys
            
        Returns:
            List of metadata keys
            
        Raises:
            requests.RequestException: If the request fails
        """
        params = {}
        if pattern:
            params['pattern'] = pattern
        
        response = requests.get(
            f"{self.base_url}/metadata/keys",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_metadata_values(self, key: str) -> List[str]:
        """
        Get all unique values for a metadata key.
        
        Args:
            key: Metadata key to get values for
            
        Returns:
            List of unique values
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/metadata/values",
            params={"key": key},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
