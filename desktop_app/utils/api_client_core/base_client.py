import logging
import time
from typing import Optional, Dict, Any

import requests

from desktop_app.utils.errors import APIError, APIConnectionError, APIAuthenticationError, APIRateLimitError

logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_AFTER_HEADER = "Retry-After"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
DEFAULT_RATE_LIMIT_RETRIES = 6
MAX_RATE_LIMIT_SLEEP_SECONDS = 65.0

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
        retry_on_rate_limit = bool(kwargs.pop("retry_on_rate_limit", False))
        max_rate_limit_retries = int(
            kwargs.pop("max_rate_limit_retries", DEFAULT_RATE_LIMIT_RETRIES)
        )
        kwargs.setdefault('timeout', self._timeout)
        attempts = 0

        try:
            while True:
                response = self._session.request(method, url, **kwargs)

                if (
                    response.status_code == 429
                    and retry_on_rate_limit
                    and attempts < max_rate_limit_retries
                ):
                    attempts += 1
                    delay = _rate_limit_retry_delay(response, attempts)
                    logger.warning(
                        "Rate limited during %s %s; retrying in %.1fs "
                        "(attempt %d/%d)",
                        method,
                        url,
                        delay,
                        attempts,
                        max_rate_limit_retries,
                    )
                    _rewind_request_files(kwargs.get("files"))
                    time.sleep(delay)
                    continue

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
                if isinstance(error_data, dict):
                    if "message" in error_data:
                        error_msg = error_data["message"]
                    elif "detail" in error_data:
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


def _rate_limit_retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get(RATE_LIMIT_RETRY_AFTER_HEADER)
    if retry_after:
        try:
            return _clamp_retry_delay(float(retry_after))
        except ValueError:
            pass

    reset_at = response.headers.get(RATE_LIMIT_RESET_HEADER)
    if reset_at:
        try:
            return _clamp_retry_delay(float(reset_at) - time.time() + 0.25)
        except ValueError:
            pass

    return _clamp_retry_delay(2 ** max(0, attempt - 1))


def _clamp_retry_delay(delay: float) -> float:
    return max(0.0, min(delay, MAX_RATE_LIMIT_SLEEP_SECONDS))


def _rewind_request_files(files: Any) -> None:
    """Reset file-like request bodies before retrying a multipart upload."""
    if not files:
        return

    values = files.values() if isinstance(files, dict) else files
    for value in values:
        _rewind_file_value(value)


def _rewind_file_value(value: Any) -> bool:
    if hasattr(value, "seek"):
        try:
            value.seek(0)
            return True
        except Exception:
            logger.debug("Could not rewind request file for retry", exc_info=True)
            return False

    if isinstance(value, (list, tuple)):
        rewound = False
        for item in value:
            rewound = _rewind_file_value(item) or rewound
        return rewound

    return False
