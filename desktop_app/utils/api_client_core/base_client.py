import requests
from typing import Optional, Dict, Any

from desktop_app.utils.errors import APIError, APIConnectionError, APIAuthenticationError, APIRateLimitError

class BaseAPIClient:
    """
    Core HTTP proxy for the PGVectorRAGIndexer API.
    Manages shared `requests.Session` execution, base URL logic, and auth headers.
    """
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None, timeout: int = 7200):
        self._session = requests.Session()
        self._timeout = timeout
        
        # Initialize properties. Base URL setter handles 'api_base' derivation as well.
        self._api_base: str = ""
        self._api_key: Optional[str] = None
        
        self.base_url = base_url
        self.api_key = api_key

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, value: Optional[str]):
        """
        Derives `api_base` when the `base_url` changes, ensuring synchronized trailing slash states.
        """
        normalized_value = value.rstrip('/') if value else value
        self._base_url = normalized_value
        
        if normalized_value:
            self._api_base = f"{normalized_value}/api/v1"
        else:
            self._api_base = normalized_value  # type: ignore

    @property
    def api_base(self) -> str:
        return self._api_base
        
    @api_base.setter
    def api_base(self, value: Optional[str]):
        """
        Manually backdoors `api_base` specifically to ensure absolute legacy runtime compatibility if 
        any production component injects this directly without touching `base_url`.
        """
        self._api_base = value.rstrip('/') if value else value # type: ignore

    @property
    def api_key(self) -> Optional[str]:
        return self._api_key

    @api_key.setter
    def api_key(self, value: Optional[str]):
        """
        Synchronizes the API Key immediately onto the shared session instance header.
        Domain clients rely entirely on `_session` and must not reconstruct this manually.
        """
        self._api_key = value
        if value:
            self._session.headers.update({"X-API-Key": value})
        else:
            self._session.headers.pop("X-API-Key", None)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Executes HTTP requests mapped via the shared session, enforcing standard timeout
        and structured legacy error translation mapping across the domain clients.
        """
        kwargs.setdefault('timeout', self._timeout)
        try:
            response = self._session.request(method, url, **kwargs)
            self._handle_response_errors(response)
            return response
        except requests.exceptions.ConnectionError as e:
            raise APIConnectionError(f"Failed to connect to API: {str(e)}")
        except requests.exceptions.Timeout as e:
            raise APIConnectionError(f"API request timed out: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise APIError(f"API request failed: {str(e)}")
            
    def _handle_response_errors(self, response: requests.Response):
        """
        Applies unified standardized error mappings.
        """
        if response.status_code >= 400:
            error_msg = f"API Error ({response.status_code})"
            try:
                error_data = response.json()
                if isinstance(error_data, dict) and "detail" in error_data:
                    error_msg = error_data["detail"]
            except ValueError:
                if response.text:
                    error_msg = f"{error_msg}: {response.text[:200]}"
                    
            if response.status_code == 401 or response.status_code == 403:
                raise APIAuthenticationError(error_msg, status_code=response.status_code)
            elif response.status_code == 429:
                raise APIRateLimitError(error_msg, status_code=response.status_code)
            else:
                raise APIError(error_msg, status_code=response.status_code)
                
    def close(self):
        """Releases the underlying session connection pool."""
        if hasattr(self, '_session'):
            self._session.close()
