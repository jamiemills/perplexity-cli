"""Manages file uploads to S3 and URL generation for Perplexity attachments."""

import asyncio
import base64
import logging
import uuid
from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from perplexity_cli.api.models import FileAttachment
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, SimpleRequest, SimpleResponse

logger = logging.getLogger(__name__)


class AttachmentUploader:
    """Manages file uploads to S3 and URL generation.

    This class handles the complete workflow of uploading files to S3:
    1. Request presigned upload URLs from Perplexity API
    2. Upload files to S3 using presigned credentials
    3. Return final S3 URLs for use in queries
    """

    S3_BUCKET_URL = "https://ppl-ai-file-upload.s3.amazonaws.com/"
    UPLOAD_URL_ENDPOINT = "/rest/uploads/batch_create_upload_urls"

    def __init__(self, token: str, base_url: str = "https://www.perplexity.ai"):
        """Initialize the uploader with authentication token.

        Args:
            token: JWT authentication token for API requests.
            base_url: Base URL for Perplexity API (default: https://www.perplexity.ai).
        """
        self.token = token
        self.base_url = base_url

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
        upload_urls_response = await self._request_upload_urls(attachments)

        # Step 2: Upload files to S3 in parallel
        async with AsyncSession(impersonate="chrome", timeout=300) as session:
            tasks = []
            for attachment in attachments:
                # Map attachment to its UUID from response
                file_uuid = self._find_uuid_for_attachment(attachment, upload_urls_response)
                if not file_uuid:
                    raise RuntimeError(f"Failed to find upload URL for {attachment.filename}")

                upload_data = upload_urls_response["results"][file_uuid]
                task = self._upload_to_s3(attachment, upload_data, session)
                tasks.append(task)

            # Execute all uploads in parallel
            s3_urls = await asyncio.gather(*tasks)

        logger.info(f"Successfully uploaded {len(s3_urls)} file(s)")
        return s3_urls

    async def _request_upload_urls(self, attachments: list[FileAttachment]) -> dict[str, Any]:
        """Request presigned S3 upload URLs from Perplexity API.

        Args:
            attachments: List of FileAttachment objects.

        Returns:
            API response containing presigned upload URLs and form fields.

        Raises:
            PerplexityHTTPStatusError: If API request fails.
        """
        # Build request body with file metadata
        files_metadata: dict[str, dict[str, Any]] = {}
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

        request_body = {"files": files_metadata}

        # Make API request for presigned URLs
        async with AsyncSession(impersonate="chrome", timeout=30) as session:
            try:
                response = await session.post(
                    f"{self.base_url}{self.UPLOAD_URL_ENDPOINT}",
                    json=request_body,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            except RequestException as e:
                raise RuntimeError(f"Failed to request upload URLs: {e}") from e

            if not response.ok:
                self._raise_http_status_error(response)

        logger.info(f"Received presigned URLs for {len(files_metadata)} file(s)")
        return response.json()

    async def _upload_to_s3(
        self, attachment: FileAttachment, upload_data: dict[str, Any], session: AsyncSession
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
        logger.info(f"Uploading file: {attachment.filename}")

        # Prepare multipart form data for S3
        form_data: dict[str, Any] = {}

        # Add all fields from the presigned URL response
        fields = upload_data["fields"]
        for key, value in fields.items():
            if key not in ["file"]:
                form_data[key] = value

        # Add the actual file content (last field per S3 spec)
        form_data["file"] = (
            attachment.filename,
            base64.b64decode(attachment.data),
            attachment.content_type,
        )

        try:
            response = await session.post(
                self.S3_BUCKET_URL,
                data=form_data,
            )
        except RequestException as e:
            raise RuntimeError(f"Failed to upload {attachment.filename} to S3: {e}") from e

        # S3 returns 204 No Content on successful upload
        if response.status_code == 204:
            s3_url = upload_data["s3_object_url"]
            logger.info(f"Successfully uploaded to: {s3_url}")
            return s3_url
        else:
            raise RuntimeError(
                f"S3 upload failed for {attachment.filename}: " f"status {response.status_code}"
            )

    @staticmethod
    def _find_uuid_for_attachment(
        attachment: FileAttachment, upload_urls_response: dict[str, Any]
    ) -> str | None:
        """Find the UUID for an attachment in the API response.

        The API response maps UUIDs to file metadata. We need to find which UUID
        corresponds to our attachment by matching filename and content type.

        Args:
            attachment: The FileAttachment to find.
            upload_urls_response: API response containing the mapping.

        Returns:
            The UUID string if found, None otherwise.
        """
        for file_uuid, upload_info in upload_urls_response["results"].items():
            if (
                upload_info.get("filename") == attachment.filename
                # Note: API response might not include content_type, so we can't rely on it
            ):
                return file_uuid
        return None

    @staticmethod
    def _raise_http_status_error(response: Any) -> None:
        """Raise PerplexityHTTPStatusError from a failed HTTP response.

        Args:
            response: The HTTP response object from curl_cffi.

        Raises:
            PerplexityHTTPStatusError: Always raised with response details.
        """
        simple_request = SimpleRequest(method="POST", url=response.url)
        simple_response = SimpleResponse(
            status_code=response.status_code,
            headers=dict(response.headers) if response.headers else {},
            text=response.text,
            request=simple_request,
        )
        raise PerplexityHTTPStatusError(
            message=f"HTTP {response.status_code}",
            request=simple_request,
            response=simple_response,
        )
