import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from license import (
    LicenseInfo,
    LicenseError,
    get_current_license,
    get_license_dir,
    get_license_file_path,
    reset_license,
    resolve_verification_context,
    secure_license_file,
    validate_license_key,
)
from desktop_app.utils.edition import get_edition_display, open_pricing_page
from desktop_app.utils.license_dto import LicenseDisplayDTO

logger = logging.getLogger(__name__)

@dataclass
class LicenseServiceError(Exception):
    """Domain error representing a failure during a license operation."""
    message: str
    is_network_error: bool = False
    is_invalid_key_error: bool = False

class LicenseService:
    """
    Service layer facade for license operations.
    Encapsulates core `license.py` operations and raw API/filesystem interactions,
    catching low-level exceptions and returning structured `LicenseServiceError` dataclasses.
    """

    def __init__(self, api_client=None):
        self.api_client = api_client

    def fetch_license_info(self) -> tuple[LicenseDisplayDTO, bool]:
        """
        Fetches license information, checking the remote server if an API client is available.
        Returns a tuple containing the LicenseDisplayDTO and a boolean indicating if a server error occurred.
        """
        remote_data = None
        server_error = False
        from desktop_app.utils import app_config
        
        # Try to fetch from server if remote mode is active
        if self.api_client and app_config.get_backend_mode() == app_config.BACKEND_MODE_REMOTE:
            if self.api_client.is_api_available():
                try:
                    # remote_data will be a dict from LicenseInfo.to_dict()
                    remote_data = self.api_client.get_license_info()
                except Exception as e:
                    logger.debug("Failed to fetch license from server: %s", e)
                    # We do NOT raise here. Falling back to local/community is expected.
                    # The controller handles `server_error` flagging.
                    server_error = True
            else:
                server_error = True

        try:
            return get_edition_display(remote_data), server_error
        except Exception as e:
            logger.debug("Could not load license info: %s", e)
            raise LicenseServiceError(f"Failed to load local license details: {e}")

    def install_license(self, key_string: str) -> None:
        """
        Validates, backs up the old key, and writes a new license key to disk.
        
        Raises:
            LicenseServiceError: If validation, disk I/O, or backup fails.
        """
        if not key_string:
            raise LicenseServiceError("No license key provided.", is_invalid_key_error=True)
            
        try:
            # 1. Validate in-memory first
            signing_secret, algorithms = resolve_verification_context()
            validate_license_key(key_string, signing_secret, algorithms)
        except LicenseError as le:
            raise LicenseServiceError(str(le), is_invalid_key_error=True)
        except Exception as e:
            raise LicenseServiceError(f"Unexpected validation error: {e}")

        # 2. Key is valid, prepare to write
        dest_dir = get_license_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "license.key"
        logger.info("Installing license: resolved_path=%s", dest_file)
         
        # 3. Create backup of existing key if it exists
        backup_file = None
        if dest_file.exists():
            backup_file = dest_file.with_suffix(".key.bak")
        logger.info(
            "License install preflight: exists=%s backup_path=%s canonical_path=%s",
            dest_file.exists(),
            backup_file if backup_file else None,
            get_license_file_path(),
        )
        if dest_file.exists():
            try:
                shutil.copy2(dest_file, backup_file)
            except Exception as b_err:
                logger.warning("Could not create license backup: %s", b_err)

        # 4. Write new key (with rollback)
        try:
            dest_file.write_text(key_string, encoding="utf-8")
            logger.info(
                "License file written: path=%s size=%d",
                dest_file,
                dest_file.stat().st_size,
            )
        except Exception as write_err:
            logger.error("License write failed: path=%s error=%s", dest_file, write_err, exc_info=True)
            # ROLLBACK
            rollback_success = False
            if backup_file and backup_file.exists():
                try:
                    shutil.copy2(backup_file, dest_file)
                    logger.info("Restored license from backup after write failure.")
                    logger.warning("License rollback executed: restored_from=%s", backup_file)
                    rollback_success = True
                except Exception as r_err:
                    logger.error("CRITICAL: Failed to restore license backup: %s", r_err)
            
            if rollback_success:
                reset_license()
                raise LicenseServiceError(
                    f"An error occurred while saving the new license key:\n{write_err}\n\n"
                    "Your previous license has been successfully restored from backup."
                )
            raise LicenseServiceError(f"Critical write error saving license key: {write_err}")
        
        try:
            secure_license_file(dest_file)
        except Exception as e:
            logger.warning(f"Could not secure license file permissions: {e}")

        # 4b. On Windows, also write to the Docker mount path (~/.pgvector-license/)
        #     so the backend container can read the key from its filesystem mount.
        import platform
        if platform.system() == "Windows":
            try:
                docker_license_dir = Path.home() / ".pgvector-license"
                docker_license_dir.mkdir(parents=True, exist_ok=True)
                docker_license_file = docker_license_dir / "license.key"
                docker_license_file.write_text(key_string, encoding="utf-8")
                logger.info("Synced license to Docker mount path: %s", docker_license_file)
            except Exception as e:
                logger.warning("Could not sync license to Docker mount: %s", e)

        # 5. Reload license locally
        reset_license()
        current = get_current_license()
        logger.info(
            "Local license reload complete: edition=%s org=%s seats=%s exp=%s",
            current.edition.value,
            current.org_name,
            current.seats,
            current.expiry_timestamp,
        )
         
        # 6. Tell the backend to reload its cached license from disk
        if self.api_client:
            try:
                install_url = f"{self.api_client._base.api_base}/license/install"
                reload_url = f"{self.api_client._base.api_base}/license/reload"
                logger.info("Triggering backend license sync: url=%s", install_url)
                install_resp = self.api_client._base.request(
                    "POST",
                    install_url,
                    json={"license_key": key_string},
                )
                logger.info("Backend license sync finished: status=%s", getattr(install_resp, "status_code", None))
                logger.info("Triggering backend reload: url=%s", reload_url)
                resp = self.api_client._base.request("POST", reload_url)
                logger.info("Backend reload finished: status=%s", getattr(resp, "status_code", None))
                logger.info("Backend license cache reloaded successfully")
            except Exception as e:
                logger.warning("Failed to trigger remote backend license reload: %s", e)

    def get_current_license_info(self) -> LicenseInfo:
        """Gets the currently active loaded license object."""
        return get_current_license()

    def open_pricing(self) -> None:
        """Opens the pricing webpage."""
        open_pricing_page()
