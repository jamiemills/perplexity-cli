"""Manages file uploads to S3 and URL generation for Perplexity attachments."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import Coroutine, Mapping
from typing import TYPE_CHECKING, Final, Protocol, TypedDict

import httpx

try:
    from curl_cffi.requests.exceptions import RequestException
except ImportError:  # pragma: no cover
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession
    from curl_cffi.requests.models import Response as CurlResponse

from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    AttachmentUploadError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import raise_http_status_error
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.logging import get_logger, redact_path, redact_response_text
from perplexity_cli.utils.upstream_contracts import parse_upload_url_response, require_mapping

logger: logging.Logger = get_logger()
_S3_UPLOAD_SUCCESS_STATUS: Final = 204


class UploadMetadataEntry(TypedDict):
    """Metadata payload for a single upload URL request entry."""

    filename: str
    content_type: str
    source: str
    file_size: int
    force_image: bool
    search_mode: str


type UploadMetadata = dict[str, UploadMetadataEntry]
type MultipartFormValue = tuple[None, str] | tuple[str, bytes, str]


class _UploadUrlResponse(Protocol):
    """Typed subset of the curl_cffi response used here."""

    @property
    def ok(self) -> bool: ...

    @property
    def status_code(self) -> int: ...

    @property
    def url(self) -> object: ...

    @property
    def headers(self) -> object: ...

    @property
    def content(self) -> object: ...

    def json(self) -> object: ...


def _require_upload_mapping(
    value: object, context: str, detail: str | None = None
) -> dict[str, object]:
    """Require a string-keyed mapping for upload payloads."""
    return require_mapping(value, context, detail=detail)


def _extract_upload_results(response_json: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Extract validated upload results keyed by file UUID."""
    results = _require_upload_mapping(
        response_json.get("results"),
        "Malformed upload results payload from upstream API",
        detail="missing or invalid 'results' field",
    )

    return {
        file_uuid: _require_upload_mapping(
            upload_data,
            "Malformed upload result entry from upstream API",
            detail=f"file_uuid={file_uuid}",
        )
        for file_uuid, upload_data in results.items()
    }


def _load_response_json(response: _UploadUrlResponse) -> object:
    """Load the JSON payload from an upload URL response."""
    return response.json()


def _get_httpx_async_client_factory() -> type[httpx.AsyncClient]:
    """Return the async HTTP client factory used for S3 uploads."""
    return httpx.AsyncClient


def _diagnose_upload_entry_error(upload_data: Mapping[str, object]) -> str:
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


def _normalise_upload_fields(upload_data: Mapping[str, object]) -> dict[str, object]:
    """Extract and normalise the fields dictionary from upload data.

    Args:
        upload_data: Presigned URL data from the API.

    Returns:
        A dictionary of upload fields, or an empty dict if invalid.
    """
    raw_fields = upload_data.get("fields")
    if not raw_fields:
        return {}

    if not isinstance(raw_fields, dict):
        logger.warning(
            "Unexpected fields type from API: %s. Full upload_data: %s",
            type(raw_fields).__name__,
            redact_response_text(str(upload_data)),
        )
        return {}
    return require_mapping(raw_fields, "Malformed upload fields payload")


def _validate_s3_object_url(upload_data: Mapping[str, object]) -> None:
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
    def _create_async_session(timeout: int | None = None) -> AsyncSession[CurlResponse]:
        """Create an AsyncSession with Chrome TLS impersonation."""
        from curl_cffi.requests import AsyncSession as CurlAsyncSession

        if timeout is None:
            from perplexity_cli.config.defaults import DEFAULT_REQUEST_TIMEOUT

            timeout = DEFAULT_REQUEST_TIMEOUT

        return CurlAsyncSession(impersonate="chrome", timeout=timeout)

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

        upload_timeout: int = DEFAULT_UPLOAD_TIMEOUT

        session_manager: AsyncSession[CurlResponse] = self._create_async_session(
            timeout=upload_timeout
        )
        async with session_manager as session:
            upload_urls_response, uuid_to_attachment = await self._request_upload_urls(
                attachments, session
            )

            # Step 2: Upload files to S3 in parallel
            results = _extract_upload_results(upload_urls_response)
            tasks: list[Coroutine[object, object, str]] = []
            for file_uuid, attachment in uuid_to_attachment.items():
                upload_data = results.get(file_uuid)
                validated_upload_data = _require_upload_mapping(
                    upload_data,
                    "Malformed upload result entry from upstream API",
                    detail=f"file_uuid={file_uuid}",
                )
                task = self._upload_to_s3(attachment, validated_upload_data)
                tasks.append(task)

            # Execute all uploads in parallel
            s3_urls = list(await asyncio.gather(*tasks))

        logger.info("Successfully uploaded %s file(s)", len(s3_urls))
        return s3_urls

    async def _request_upload_urls(
        self, attachments: list[FileAttachment], session: AsyncSession[CurlResponse]
    ) -> tuple[dict[str, object], dict[str, FileAttachment]]:
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
        request_body: dict[str, UploadMetadata] = {"files": files_metadata}
        headers = build_perplexity_headers(self.token, self.cookies)

        try:
            from perplexity_cli.utils.config import get_upload_url_endpoint

            upload_url_endpoint: str = get_upload_url_endpoint()
            response: _UploadUrlResponse = await session.post(
                upload_url_endpoint,
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
                "Try running 'pxcli auth login' to refresh authentication.",
                response.status_code,
            )
            raise_http_status_error(response)

        try:
            response_payload: object = _load_response_json(response)
            response_json = _require_upload_mapping(
                parse_upload_url_response(response_payload),
                "Malformed upload URL response from upstream API",
            )
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
    ) -> tuple[UploadMetadata, dict[str, FileAttachment]]:
        """Build file metadata and UUID mapping for upload URL requests.

        Args:
            attachments: List of FileAttachment objects.

        Returns:
            Tuple of (files_metadata dict, uuid_to_attachment mapping).
        """
        files_metadata: UploadMetadata = {}
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
    def _validate_upload_response(response_json: Mapping[str, object]) -> None:
        """Validate that the upload URL response contains usable presigned URLs.

        Args:
            response_json: Parsed API response.

        Raises:
            AttachmentUploadError: If any upload entry is missing fields or rate limited.
            UpstreamSchemaError: If the results payload is malformed.
        """
        results = _extract_upload_results(response_json)
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
        upload_data: dict[str, object],
        _session: AsyncSession[CurlResponse] | None = None,
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
    def _build_s3_form_data(upload_data: Mapping[str, object]) -> dict[str, str]:
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
        files_dict: dict[str, MultipartFormValue] = {}
        for key, value in form_data.items():
            files_dict[key] = (None, value)
        files_dict["file"] = (attachment.filename, file_content, attachment.content_type)

        try:
            from perplexity_cli.config.defaults import DEFAULT_UPLOAD_TIMEOUT
            from perplexity_cli.utils.config import get_s3_bucket_url

            upload_timeout: int = DEFAULT_UPLOAD_TIMEOUT
            s3_bucket_url: str = get_s3_bucket_url()
            async_client_factory = _get_httpx_async_client_factory()
            async with async_client_factory(timeout=upload_timeout) as client:
                return await client.post(s3_bucket_url, files=files_dict)
        except Exception as e:
            logger.error("S3 upload error: %s", e)
            raise AttachmentUploadError(f"Failed to upload {attachment.filename} to S3: {e}") from e

    @staticmethod
    def _handle_s3_response(
        response: httpx.Response,
        upload_data: Mapping[str, object],
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
        if response.status_code == _S3_UPLOAD_SUCCESS_STATUS:
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
