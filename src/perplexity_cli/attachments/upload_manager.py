"""Manages file uploads to S3 and URL generation for Perplexity attachments."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import TYPE_CHECKING, Any

import httpx

try:
    from curl_cffi.requests.exceptions import RequestException

    _CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    _CURL_CFFI_AVAILABLE = False

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession

from perplexity_cli.api.contracts import parse_upload_url_response, require_mapping
from perplexity_cli.api.models import FileAttachment
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    AttachmentUploadError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import raise_http_status_error
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.logging import get_logger, redact_path, redact_response_text

logger = get_logger()


def _diagnose_upload_entry_error(upload_data: dict[str, Any]) -> str:
    """Determine the appropriate error message for a failed upload entry.

    Args:
        upload_data: The upload data entry from the API response.

    Returns:
        Human-readable error message string.
    """
    if upload_data.get("rate_limited"):
        from perplexity_cli.config.defaults import PERPLEXITY_SETTINGS_URL

        return (
            "File upload quota exhausted. "
            "Your Perplexity plan's document analysis allowance "
            f"has been reached. Check your account at "
            f"{PERPLEXITY_SETTINGS_URL}"
        )
    if upload_data.get("error"):
        return f"API failed to generate upload URL: {upload_data.get('error')}"
    return (
        "API returned an empty presigned URL response. "
        "This may indicate an authentication or account issue."
    )


def _extract_error_response_text(response: httpx.Response) -> str:
    """Extract a truncated text representation from an error response.

    Args:
        response: The httpx Response to extract text from.

    Returns:
        Truncated response text (up to 500 characters).
    """
    try:
        return response.text[:500] if response.text else str(response.content)[:500]
    except (AttributeError, TypeError):
        return ""


def _normalise_upload_fields(upload_data: dict[str, Any]) -> dict:
    """Extract and normalise the fields dictionary from upload data.

    Args:
        upload_data: Presigned URL data from the API.

    Returns:
        A dictionary of upload fields, or an empty dict if invalid.
    """
    fields = upload_data.get("fields") or {}
    if not isinstance(fields, dict):
        logger.warning(
            "Unexpected fields type from API: %s. Full upload_data: %s",
            type(fields).__name__,
            redact_response_text(str(upload_data)),
        )
        return {}
    return fields


def _validate_s3_object_url(upload_data: dict[str, Any]) -> None:
    """Validate the s3_object_url field in upload data.

    Args:
        upload_data: Presigned URL data from the API.

    Raises:
        UpstreamSchemaError: If the S3 object URL is present but not a string.
    """
    s3_object_url = upload_data.get("s3_object_url", "")
    if s3_object_url and not isinstance(s3_object_url, str):
        raise UpstreamSchemaError("Malformed S3 object URL in upload response")


class AttachmentUploader:
    """Manages file uploads to S3 and URL generation.

    This class handles the complete workflow of uploading files to S3:
    1. Request presigned upload URLs from Perplexity API
    2. Upload files to S3 using presigned credentials
    3. Return final S3 URLs for use in queries
    """

    def __init__(
        self,
        token: str,
        cookies: dict[str, str] | None = None,
        base_url: str | None = None,
    ):
        """Initialise the uploader with authentication token and cookies.

        Args:
            token: JWT authentication token for API requests.
            cookies: Optional browser cookies for Cloudflare bypass and session auth.
            base_url: Base URL for Perplexity API (default from configuration).
        """
        if base_url is None:
            from perplexity_cli.utils.config import get_perplexity_base_url

            base_url = get_perplexity_base_url()

        self.token = token
        self.cookies = cookies
        self.base_url = base_url

    @staticmethod
    def _create_async_session(timeout: int | None = None) -> AsyncSession:
        """Create an AsyncSession with Chrome TLS impersonation.

        Args:
            timeout: Request timeout in seconds (default from config/defaults).

        Returns:
            An AsyncSession configured for Chrome impersonation.

        Raises:
            RuntimeError: If curl_cffi is not installed.
        """
        from perplexity_cli.utils.session_factory import create_async_session

        return create_async_session(timeout=timeout)

    async def upload_files(self, attachments: list[FileAttachment]) -> list[str]:
        """Upload files to S3 and return final S3 URLs.

        This method orchestrates the complete upload process:
        1. Requests presigned URLs from the API
        2. Uploads each file to S3 in parallel
        3. Returns the final S3 URLs ready for query submission

        Args:
            attachments: List of FileAttachment objects to upload.

        Returns:
            List of S3 URLs in the same order as input attachments.

        Raises:
            PerplexityHTTPStatusError: If presigned URL request fails.
            RuntimeError: If S3 upload fails.
        """
        if not attachments:
            return []

        logger.info("Requesting presigned URLs for %s file(s)", len(attachments))

        # Step 1: Request presigned upload URLs from API
        # Returns both the API response and UUID->attachment mapping
        # Use a single session for both the presigned URL request and S3 uploads
        from perplexity_cli.config.defaults import DEFAULT_UPLOAD_TIMEOUT

        async with self._create_async_session(timeout=DEFAULT_UPLOAD_TIMEOUT) as session:
            upload_urls_response, uuid_to_attachment = await self._request_upload_urls(
                attachments, session
            )

            # Step 2: Upload files to S3 in parallel
            tasks = []
            uuid_list = []
            for file_uuid, attachment in uuid_to_attachment.items():
                results = require_mapping(
                    upload_urls_response.get("results"),
                    "Malformed upload results payload from upstream API",
                    detail="missing or invalid 'results' field",
                )
                upload_data = results.get(file_uuid)
                upload_data = require_mapping(
                    upload_data,
                    "Malformed upload result entry from upstream API",
                    detail=f"file_uuid={file_uuid}",
                )
                task = self._upload_to_s3(attachment, upload_data)
                tasks.append(task)
                uuid_list.append(file_uuid)

            # Execute all uploads in parallel
            s3_urls = await asyncio.gather(*tasks)

        logger.info("Successfully uploaded %s file(s)", len(s3_urls))
        return s3_urls

    async def _request_upload_urls(
        self, attachments: list[FileAttachment], session: AsyncSession
    ) -> tuple[dict[str, Any], dict[str, FileAttachment]]:
        """Request presigned S3 upload URLs from Perplexity API.

        Args:
            attachments: List of FileAttachment objects.
            session: The shared AsyncSession to use for the request.

        Returns:
            Tuple of (API response, UUID to FileAttachment mapping).

        Raises:
            PerplexityHTTPStatusError: If API request fails.
        """
        files_metadata, uuid_to_attachment = self._build_upload_metadata(attachments)
        request_body = {"files": files_metadata}
        headers = build_perplexity_headers(self.token, self.cookies)

        try:
            from perplexity_cli.utils.config import get_upload_url_endpoint

            response = await session.post(
                get_upload_url_endpoint(),
                json=request_body,
                headers=headers,
                cookies=to_curl_cffi_cookies(self.cookies),
            )
        except RequestException as e:
            raise AttachmentUploadError(f"Failed to request upload URLs: {e}") from e

        if not response.ok:
            logger.error(
                "Upload URL request failed with status %s. "
                "This may indicate an invalid or expired token. "
                "Try running 'pxcli auth' to refresh authentication.",
                response.status_code,
            )
            raise_http_status_error(response)

        try:
            response_json = parse_upload_url_response(response.json())
        except ValueError as e:
            raise UpstreamSchemaError("Malformed upload URL response from upstream API") from e

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "API response for upload URLs: %s",
                redact_response_text(str(response_json)),
            )

        self._validate_upload_response(response_json)

        logger.info("Received presigned URLs for %s file(s)", len(files_metadata))
        return response_json, uuid_to_attachment

    @staticmethod
    def _build_upload_metadata(
        attachments: list[FileAttachment],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, FileAttachment]]:
        """Build file metadata and UUID mapping for upload URL requests.

        Args:
            attachments: List of FileAttachment objects.

        Returns:
            Tuple of (files_metadata dict, uuid_to_attachment mapping).
        """
        files_metadata: dict[str, dict[str, Any]] = {}
        uuid_to_attachment: dict[str, FileAttachment] = {}

        for attachment in attachments:
            file_uuid = str(uuid.uuid4())
            decoded_size = len(base64.b64decode(attachment.data))
            files_metadata[file_uuid] = {
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "source": "default",
                "file_size": decoded_size,
                "force_image": False,
                "search_mode": "search",
            }
            uuid_to_attachment[file_uuid] = attachment

        return files_metadata, uuid_to_attachment

    @staticmethod
    def _validate_upload_response(response_json: dict[str, Any]) -> None:
        """Validate that the upload URL response contains usable presigned URLs.

        Args:
            response_json: Parsed API response.

        Raises:
            AttachmentUploadError: If any upload entry is missing fields or rate limited.
            UpstreamSchemaError: If the results payload is malformed.
        """
        results = require_mapping(
            response_json.get("results"),
            "Malformed upload results payload from upstream API",
            detail="missing or invalid 'results' field",
        )
        if not results:
            return
        for _file_uuid, upload_data in results.items():
            if upload_data.get("fields") and upload_data.get("s3_object_url"):
                continue
            error_msg = _diagnose_upload_entry_error(upload_data)
            logger.error(error_msg)
            raise AttachmentUploadError(error_msg)

    async def _upload_to_s3(
        self,
        attachment: FileAttachment,
        upload_data: dict[str, Any],
        _session: AsyncSession | None = None,
    ) -> str:
        """Upload file to S3 using presigned URL.

        Args:
            attachment: The FileAttachment to upload.
            upload_data: Presigned URL data from API (includes form fields).
            _session: Unused compatibility parameter kept for older tests and callers.

        Returns:
            The final S3 URL for the uploaded file.

        Raises:
            RuntimeError: If S3 upload fails.
        """
        logger.info("Uploading file: %s", redact_path(attachment.filename))

        form_data = self._build_s3_form_data(upload_data)
        file_content = base64.b64decode(attachment.data)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("S3 upload form fields: %s", list(form_data.keys()))
            logger.debug("File size: %s bytes", len(file_content))

        response = await self._execute_s3_upload(form_data, attachment, file_content)
        return self._handle_s3_response(response, upload_data, attachment)

    @staticmethod
    def _build_s3_form_data(upload_data: dict[str, Any]) -> dict[str, str]:
        """Build the form data dictionary for an S3 presigned upload.

        Args:
            upload_data: Presigned URL data from the API.

        Returns:
            Dictionary of form fields for the multipart upload.

        Raises:
            UpstreamSchemaError: If the S3 object URL is malformed.
        """
        fields = _normalise_upload_fields(upload_data)
        _validate_s3_object_url(upload_data)
        return {key: str(value) for key, value in fields.items() if key != "file"}

    @staticmethod
    async def _execute_s3_upload(
        form_data: dict[str, str],
        attachment: FileAttachment,
        file_content: bytes,
    ) -> httpx.Response:
        """Execute the multipart upload to S3.

        Args:
            form_data: Form fields for the presigned upload.
            attachment: The FileAttachment being uploaded.
            file_content: Decoded file content bytes.

        Returns:
            The httpx Response object.

        Raises:
            AttachmentUploadError: If the upload request fails.
        """
        files_dict: dict[str, tuple] = {}
        for key, value in form_data.items():
            files_dict[key] = (None, value)
        files_dict["file"] = (attachment.filename, file_content, attachment.content_type)

        try:
            from perplexity_cli.config.defaults import DEFAULT_UPLOAD_TIMEOUT
            from perplexity_cli.utils.config import get_s3_bucket_url

            async with httpx.AsyncClient(timeout=DEFAULT_UPLOAD_TIMEOUT) as client:
                return await client.post(get_s3_bucket_url(), files=files_dict)
        except Exception as e:
            logger.error("S3 upload error: %s", e)
            raise AttachmentUploadError(f"Failed to upload {attachment.filename} to S3: {e}") from e

    @staticmethod
    def _handle_s3_response(
        response: httpx.Response,
        upload_data: dict[str, Any],
        attachment: FileAttachment,
    ) -> str:
        """Process the S3 upload response and return the final URL.

        Args:
            response: The httpx Response from S3.
            upload_data: Original presigned URL data.
            attachment: The FileAttachment that was uploaded.

        Returns:
            The S3 object URL string.

        Raises:
            UpstreamSchemaError: If the S3 object URL is malformed.
            AttachmentUploadError: If the upload was not successful.
        """
        if response.status_code == 204:
            s3_url = upload_data.get("s3_object_url", "")
            if not isinstance(s3_url, str):
                raise UpstreamSchemaError("Malformed S3 object URL in upload response")
            logger.info("Successfully uploaded to: %s", s3_url)
            return s3_url

        response_text = _extract_error_response_text(response)
        logger.error(
            "S3 upload failed: status %s, response: %s",
            response.status_code,
            redact_response_text(response_text),
        )
        raise AttachmentUploadError(
            f"S3 upload failed for {attachment.filename}: status {response.status_code}"
        )
