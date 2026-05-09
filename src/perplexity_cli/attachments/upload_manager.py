"""Manages file uploads to S3 and URL generation for Perplexity attachments."""

import asyncio
import base64
import logging
import uuid
from typing import Any

import httpx

try:
    from curl_cffi.requests import AsyncSession
    from curl_cffi.requests.exceptions import RequestException

    _CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    AsyncSession = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    _CURL_CFFI_AVAILABLE = False

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

        logger.info(f"Requesting presigned URLs for {len(attachments)} file(s)")

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
                task = self._upload_to_s3(attachment, upload_data, session)
                tasks.append(task)
                uuid_list.append(file_uuid)

            # Execute all uploads in parallel
            s3_urls = await asyncio.gather(*tasks)

        logger.info(f"Successfully uploaded {len(s3_urls)} file(s)")
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
        # Build request body with file metadata
        # Keep track of UUID -> attachment mapping for later lookup
        files_metadata: dict[str, dict[str, Any]] = {}
        uuid_to_attachment: dict[str, FileAttachment] = {}

        for attachment in attachments:
            file_uuid = str(uuid.uuid4())
            # Calculate decoded file size
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

        request_body = {"files": files_metadata}

        # Build headers using shared helper (Origin, Referer, CSRF token)
        headers = build_perplexity_headers(self.token, self.cookies)

        # Make API request for presigned URLs
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
            # Log response details for debugging authentication issues
            logger.error(
                f"Upload URL request failed with status {response.status_code}. "
                f"This may indicate an invalid or expired token. "
                f"Try running 'pxcli auth' to refresh authentication."
            )
            raise_http_status_error(response)

        # Log the API response for debugging
        try:
            response_json = parse_upload_url_response(response.json())
        except ValueError as e:
            raise UpstreamSchemaError("Malformed upload URL response from upstream API") from e

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"API response for upload URLs: {redact_response_text(str(response_json))}"
            )

        # Check if API returned valid presigned URLs
        # The API may return HTTP 200 but with null fields when the account's
        # file upload quota is exhausted or the request is rate limited.
        results = require_mapping(
            response_json.get("results"),
            "Malformed upload results payload from upstream API",
            detail="missing or invalid 'results' field",
        )

        if results:
            for _file_uuid, upload_data in results.items():
                if not upload_data.get("fields") or not upload_data.get("s3_object_url"):
                    if upload_data.get("rate_limited"):
                        from perplexity_cli.config.defaults import PERPLEXITY_SETTINGS_URL

                        error_msg = (
                            "File upload quota exhausted. "
                            "Your Perplexity plan's document analysis allowance "
                            f"has been reached. Check your account at "
                            f"{PERPLEXITY_SETTINGS_URL}"
                        )
                    elif upload_data.get("error"):
                        error_msg = f"API failed to generate upload URL: {upload_data.get('error')}"
                    else:
                        error_msg = (
                            "API returned an empty presigned URL response. "
                            "This may indicate an authentication or account issue."
                        )
                    logger.error(error_msg)
                    raise AttachmentUploadError(error_msg)

        logger.info(f"Received presigned URLs for {len(files_metadata)} file(s)")
        return response_json, uuid_to_attachment

    async def _upload_to_s3(
        self,
        attachment: FileAttachment,
        upload_data: dict[str, Any],
        session: AsyncSession,
    ) -> str:
        """Upload file to S3 using presigned URL.

        Args:
            attachment: The FileAttachment to upload.
            upload_data: Presigned URL data from API (includes form fields).
            session: AsyncSession for making the request.

        Returns:
            The final S3 URL for the uploaded file.

        Raises:
            RuntimeError: If S3 upload fails.
        """
        logger.info(f"Uploading file: {redact_path(attachment.filename)}")

        # S3 presigned form uploads require multipart/form-data
        # Build form data with all policy/signature fields, then file content
        form_data = {}

        # Add all fields from the presigned URL response (contain policy, signature, etc.)
        # Handle case where API returns "fields": null (authentication/validation issue)
        fields = upload_data.get("fields") or {}
        if not isinstance(fields, dict):
            logger.warning(
                f"Unexpected fields type from API: {type(fields).__name__}. "
                f"Full upload_data: {redact_response_text(str(upload_data))}"
            )
            fields = {}

        s3_object_url = upload_data.get("s3_object_url", "")
        if s3_object_url and not isinstance(s3_object_url, str):
            raise UpstreamSchemaError("Malformed S3 object URL in upload response")

        for key, value in fields.items():
            if key not in ["file"]:
                form_data[key] = str(value)

        # Decode file content
        file_content = base64.b64decode(attachment.data)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"S3 upload form fields: {list(form_data.keys())}")
            logger.debug(f"File size: {len(file_content)} bytes")

        try:
            # curl_cffi doesn't support multipart file uploads well,
            # so httpx is used for S3 uploads (imported at module level).
            files_dict: dict[str, tuple] = {}
            for key, value in form_data.items():
                files_dict[key] = (None, value)
            files_dict["file"] = (attachment.filename, file_content, attachment.content_type)

            from perplexity_cli.config.defaults import DEFAULT_UPLOAD_TIMEOUT
            from perplexity_cli.utils.config import get_s3_bucket_url

            async with httpx.AsyncClient(timeout=DEFAULT_UPLOAD_TIMEOUT) as client:
                response = await client.post(
                    get_s3_bucket_url(),
                    files=files_dict,
                )
        except RequestException as e:
            logger.error(f"S3 request exception: {e}")
            raise AttachmentUploadError(f"Failed to upload {attachment.filename} to S3: {e}") from e
        except Exception as e:
            # Intentionally broad: multipart upload failures can come from several transport,
            # encoding, or third-party client paths. Surface them as one upload failure.
            logger.error(f"S3 upload error: {e}")
            raise AttachmentUploadError(f"Failed to upload {attachment.filename} to S3: {e}") from e

        # S3 returns 204 No Content on successful upload
        if response.status_code == 204:
            s3_url = upload_data.get("s3_object_url", "")
            if not isinstance(s3_url, str):
                raise UpstreamSchemaError("Malformed S3 object URL in upload response")
            logger.info(f"Successfully uploaded to: {s3_url}")
            return s3_url
        else:
            # Log response details for debugging
            response_text = ""
            try:
                response_text = (
                    response.text[:500] if response.text else str(response.content)[:500]
                )
            except (AttributeError, TypeError):
                pass

            logger.error(
                "S3 upload failed: status "
                f"{response.status_code}, response: {redact_response_text(response_text)}"
            )
            raise AttachmentUploadError(
                f"S3 upload failed for {attachment.filename}: status {response.status_code}"
            )
