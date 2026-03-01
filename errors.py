from enum import Enum
from typing import Optional, Dict, Any
from fastapi import HTTPException, status

class ErrorCode(Enum):
    """
    Central registry of API error codes.
    Each code maps to an HTTP status and a default user-facing message.
    """
    # System Errors (1xxx)
    INTERNAL_SERVER_ERROR = ("SYS_1001", status.HTTP_500_INTERNAL_SERVER_ERROR, "An unexpected internal server error occurred.")
    NOT_IMPLEMENTED = ("SYS_1002", status.HTTP_501_NOT_IMPLEMENTED, "This feature is not yet implemented.")
    SERVICE_INITIALIZING = ("SYS_1003", status.HTTP_503_SERVICE_UNAVAILABLE, "Server is still initializing. Please try again in a moment.")
    SERVICE_INITIALIZATION_FAILED = ("SYS_1004", status.HTTP_500_INTERNAL_SERVER_ERROR, "Server failed to initialize properly.")
    
    # Auth & Security (2xxx)
    UNAUTHORIZED = ("AUTH_2001", status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    FORBIDDEN = ("AUTH_2002", status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action.")
    INVALID_API_KEY = ("AUTH_2003", status.HTTP_401_UNAUTHORIZED, "The provided API key is invalid or expired.")
    DEMO_MODE_RESTRICTION = ("AUTH_2004", status.HTTP_403_FORBIDDEN, "This operation is restricted in demo mode.")
    
    # License Errors (3xxx)
    LICENSE_NOT_FOUND = ("LIC_3001", status.HTTP_404_NOT_FOUND, "No license key found.")
    LICENSE_EXPIRED = ("LIC_3002", status.HTTP_403_FORBIDDEN, "Your license has expired.")
    LICENSE_INVALID = ("LIC_3003", status.HTTP_400_BAD_REQUEST, "Invalid license key format or signature.")
    LICENSE_REVOKED = ("LIC_3004", status.HTTP_403_FORBIDDEN, "This license has been revoked.")
    LICENSE_SEAT_LIMIT_REACHED = ("LIC_3005", status.HTTP_403_FORBIDDEN, "License seat limit reached.")
    
    # Document & Search Errors (4xxx)
    DOCUMENT_NOT_FOUND = ("DOC_4001", status.HTTP_404_NOT_FOUND, "The requested document was not found.")
    UNSUPPORTED_FORMAT = ("DOC_4002", status.HTTP_400_BAD_REQUEST, "This file format is not supported.")
    DOCUMENT_PROCESSING_FAILED = ("DOC_4003", status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to process the document content.")
    ENCRYPTED_PDF = ("DOC_4004", status.HTTP_400_BAD_REQUEST, "The PDF file is encrypted and cannot be processed.")
    SEARCH_TIMEOUT = ("SRCH_4101", status.HTTP_504_GATEWAY_TIMEOUT, "The search operation timed out.")
    
    # Database Errors (5xxx)
    DATABASE_CONNECTION_ERROR = ("DB_5001", status.HTTP_503_SERVICE_UNAVAILABLE, "Failed to connect to the database.")
    DATABASE_QUERY_ERROR = ("DB_5002", status.HTTP_500_INTERNAL_SERVER_ERROR, "A database query error occurred.")

    def __init__(self, code: str, status_code: int, message: str):
        self.code = code
        self.status_code = status_code
        self.message = message

def raise_api_error(error_code: ErrorCode, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
    """
    Raise a structured HTTPException using the centralized ErrorRegistry.
    """
    raise HTTPException(
        status_code=error_code.status_code,
        detail={
            "error_code": error_code.code,
            "message": message or error_code.message,
            "details": details
        }
    )
