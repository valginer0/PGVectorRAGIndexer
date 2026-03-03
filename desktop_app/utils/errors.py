"""
Semantic domain errors for the API Client.
"""

class APIError(Exception):
    """Base exception for all API-related errors."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

class APIConnectionError(APIError):
    """Raised when the API is unreachable or a request times out."""
    pass

class APIAuthenticationError(APIError):
    """Raised when the API key is missing, invalid, or expired (401/403)."""
    pass

class APIRateLimitError(APIError):
    """Raised when the API rate limit is exceeded (429)."""
    pass
