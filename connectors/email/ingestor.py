"""
Cloud Ingestor for Microsoft Graph API using MSAL (Official Microsoft Stack).

Uses device-code flow for authentication (best for desktop apps).
No client_secret required - uses public client flow.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Iterator, Optional, List, Dict, Any
from datetime import datetime

try:
    import msal
    import requests
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False
    msal = None
    requests = None

logger = logging.getLogger(__name__)

# Graph API endpoints
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
AUTHORITY_BASE = "https://login.microsoftonline.com"

# Default scopes for email access
DEFAULT_SCOPES = ["https://graph.microsoft.com/Mail.Read"]


class CloudIngestorError(Exception):
    """Base exception for Cloud Ingestor errors."""
    pass


class AuthenticationError(CloudIngestorError):
    """Raised when authentication fails."""
    pass


class ThrottlingError(CloudIngestorError):
    """Raised when API rate limit is hit."""
    pass


class CloudIngestor:
    """
    Fetches emails from Microsoft 365 via Graph API using MSAL.
    
    Authentication uses device-code flow:
    1. User receives a code and URL
    2. User authenticates in their browser
    3. Tokens are cached for future use
    
    No client_secret required (public client flow).
    """
    
    def __init__(
        self,
        client_id: str,
        tenant_id: Optional[str] = None,
        cache_dir: Optional[str] = None
    ):
        """
        Initialize the Cloud Ingestor.
        
        Args:
            client_id: Azure App Registration Client ID
            tenant_id: Optional Tenant ID (defaults to 'common' for multi-tenant)
            cache_dir: Optional directory for token cache (defaults to ~/.pgvector-email)
        """
        if not MSAL_AVAILABLE:
            raise CloudIngestorError(
                "MSAL library not installed. Run: pip install msal requests"
            )
        
        self.client_id = client_id
        self.tenant_id = tenant_id or 'common'
        self.authority = f"{AUTHORITY_BASE}/{self.tenant_id}"
        
        # Token cache location
        self.cache_dir = Path(cache_dir or os.path.expanduser("~/.pgvector-email"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "msal_token_cache.json"
        
        # Initialize MSAL cache
        self._cache = msal.SerializableTokenCache()
        if self.cache_file.exists():
            self._cache.deserialize(self.cache_file.read_text())
        
        # Create public client application (no secret)
        self._app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            token_cache=self._cache
        )
        
        self._access_token: Optional[str] = None
    
    def _save_cache(self):
        """Persist token cache to disk."""
        if self._cache.has_state_changed:
            self.cache_file.write_text(self._cache.serialize())
    
    def authenticate(self, scopes: Optional[List[str]] = None) -> bool:
        """
        Authenticate with Microsoft Graph API using device-code flow.
        
        On first run, user will receive a code to enter at https://microsoft.com/devicelogin
        Subsequent runs use cached tokens (refresh token handled automatically).
        
        Args:
            scopes: Optional list of scopes. Defaults to ['Mail.Read']
        
        Returns:
            True if authentication succeeds
        """
        scopes = scopes or DEFAULT_SCOPES
        
        # Try to get token from cache first (silent auth)
        accounts = self._app.get_accounts()
        if accounts:
            logger.info("Found cached account, attempting silent authentication...")
            result = self._app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._save_cache()
                logger.info("Silent authentication successful")
                return True
        
        # No cached token, use device-code flow
        logger.info("Starting device-code authentication flow...")
        flow = self._app.initiate_device_flow(scopes=scopes)
        
        if "user_code" not in flow:
            raise AuthenticationError(
                f"Failed to create device flow: {flow.get('error_description', 'unknown error')}"
            )
        
        # Display instructions to user
        print("\n" + "=" * 60)
        print("OUTLOOK EMAIL CONNECTOR - AUTHENTICATION REQUIRED")
        print("=" * 60)
        print(f"\nTo authorize access to your email:")
        print(f"1. Open: {flow['verification_uri']}")
        print(f"2. Enter code: {flow['user_code']}")
        print(f"\nWaiting for you to complete authentication...\n")
        
        # Wait for user to authenticate
        result = self._app.acquire_token_by_device_flow(flow)
        
        if "access_token" in result:
            self._access_token = result["access_token"]
            self._save_cache()
            logger.info("Device-code authentication successful")
            print("✓ Authentication successful!\n")
            return True
        else:
            error_msg = result.get("error_description", result.get("error", "Unknown error"))
            raise AuthenticationError(f"Authentication failed: {error_msg}")
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 5
    ) -> Dict[str, Any]:
        """
        Make a request to Graph API with throttle handling.
        
        Args:
            endpoint: API endpoint (relative to GRAPH_BASE_URL)
            params: Optional query parameters
            max_retries: Maximum retries on throttling
        
        Returns:
            JSON response data
        """
        if not self._access_token:
            raise CloudIngestorError("Not authenticated. Call authenticate() first.")
        
        url = f"{GRAPH_BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout, attempt {attempt + 1}/{max_retries}")
                time.sleep(5 * (attempt + 1))
                continue
            
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 429:
                # Throttled - respect Retry-After header with exponential backoff
                retry_after = int(response.headers.get("Retry-After", 30))
                # Add exponential backoff on top
                backoff = retry_after + (attempt * 10)
                logger.warning(f"Throttled by Graph API, waiting {backoff}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(backoff)
                continue
            
            elif response.status_code == 401:
                # Token expired, try to refresh
                logger.info("Token expired, attempting refresh...")
                if self.authenticate():
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    continue
                else:
                    raise AuthenticationError("Failed to refresh token")
            
            else:
                raise CloudIngestorError(
                    f"Graph API error {response.status_code}: {response.text}"
                )
        
        raise ThrottlingError(f"Max retries ({max_retries}) exceeded due to throttling. Try fetching fewer emails.")
    
    def get_messages(
        self,
        folder: str = 'inbox',
        limit: int = 100,
        since: Optional[datetime] = None,
        delta_token: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch messages from the specified folder.
        
        Supports delta queries for incremental sync.
        
        Args:
            folder: Mailbox folder name (inbox, sentitems, etc.)
            limit: Maximum number of messages to fetch
            since: Only fetch messages received after this datetime
            delta_token: Token from previous sync for incremental updates
        
        Yields:
            Dict with message data: id, thread_id, sender, subject, body, received_at
        """
        # Build endpoint
        if delta_token:
            # Use delta endpoint for incremental sync
            endpoint = f"/me/mailFolders/{folder}/messages/delta"
            params = {"$deltatoken": delta_token}
        else:
            endpoint = f"/me/mailFolders/{folder}/messages"
            params = {
                "$select": "id,conversationId,sender,subject,body,receivedDateTime,hasAttachments,isRead",
                "$orderby": "receivedDateTime desc",
                "$top": min(limit, 50)  # API max is usually 50 per page
            }
            
            if since:
                params["$filter"] = f"receivedDateTime ge {since.isoformat()}Z"
        
        fetched = 0
        next_link = None
        
        while fetched < limit:
            if next_link:
                # Handle pagination
                response = requests.get(
                    next_link,
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if response.status_code != 200:
                    logger.error(f"Pagination error: {response.status_code}")
                    break
                data = response.json()
            else:
                data = self._make_request(endpoint, params)
            
            messages = data.get("value", [])
            
            for message in messages:
                if fetched >= limit:
                    break
                
                try:
                    yield {
                        'id': message.get('id'),
                        'thread_id': message.get('conversationId'),
                        'sender': self._format_sender(message.get('sender')),
                        'subject': message.get('subject'),
                        'body': message.get('body', {}).get('content', ''),
                        'received_at': self._parse_datetime(message.get('receivedDateTime')),
                        'has_attachments': message.get('hasAttachments', False),
                        'is_read': message.get('isRead', True),
                    }
                    fetched += 1
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
            
            # Check for more pages
            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
        
        logger.info(f"Fetched {fetched} messages from '{folder}'")
    
    def _format_sender(self, sender: Optional[Dict]) -> Optional[str]:
        """Format sender object to string."""
        if not sender:
            return None
        email_address = sender.get("emailAddress", {})
        name = email_address.get("name", "")
        address = email_address.get("address", "")
        if name and address:
            return f"{name} <{address}>"
        return address or name or None
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            # Remove trailing 'Z' and parse
            clean_str = dt_str.rstrip('Z')
            return datetime.fromisoformat(clean_str)
        except (ValueError, TypeError):
            return None
    
    def get_folders(self) -> List[Dict[str, str]]:
        """Get list of available mail folders."""
        data = self._make_request("/me/mailFolders")
        folders = []
        for folder in data.get("value", []):
            folders.append({
                'id': folder.get('id'),
                'name': folder.get('displayName'),
                'total_items': folder.get('totalItemCount', 0)
            })
        return folders
    
    def logout(self):
        """Clear cached tokens (logout)."""
        if self.cache_file.exists():
            self.cache_file.unlink()
        self._cache = msal.SerializableTokenCache()
        self._access_token = None
        logger.info("Logged out and cleared token cache")
