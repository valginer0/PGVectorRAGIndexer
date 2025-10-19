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
        force_reindex: bool = False
    ) -> Dict[str, Any]:
        """
        Upload and index a document.
        
        Args:
            file_path: Path to the file to upload
            custom_source_uri: Custom source URI (full path) to preserve
            force_reindex: Whether to force reindexing if document exists
            
        Returns:
            Response data from the API
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Uploading document: {file_path}")
        
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f)}
            data = {'force_reindex': str(force_reindex).lower()}
            
            if custom_source_uri:
                data['custom_source_uri'] = custom_source_uri
            
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
        metric: str = "cosine"
    ) -> List[Dict[str, Any]]:
        """
        Search for documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum similarity score
            metric: Similarity metric to use
            
        Returns:
            List of search results
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Searching for: {query}")
        
        response = requests.post(
            f"{self.base_url}/search",
            json={
                "query": query,
                "top_k": top_k,
                "min_score": min_score,
                "metric": metric
            },
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
