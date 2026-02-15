"""Real end-to-end tests for file attachment functionality.

These tests actually submit queries with file attachments to the real Perplexity API
and verify that files are properly attached by checking if the API can access the
file content in its response.

These tests require:
- Valid Perplexity auth token in ~/.config/perplexity-cli/config.json
- Network access to api.perplexity.ai and S3
- AttachmentUploader fully working with S3

To run these tests:
    pytest tests/test_file_attachment_real_e2e.py -xvs
"""

import asyncio
import textwrap

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import FileAttachment
from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.auth.token_manager import TokenManager


@pytest.fixture
def auth_token():
    """Load auth token from config."""
    try:
        tm = TokenManager()
        token, cookies = tm.load_token()
        if not token:
            pytest.skip("No valid auth token found")
        return token, cookies
    except Exception as e:
        pytest.skip(f"No valid auth token found: {e}")


@pytest.fixture
def attachment_uploader(auth_token):
    """Create an AttachmentUploader with valid token."""
    token, _ = auth_token
    return AttachmentUploader(token=token)


class TestFileAttachmentRealE2E:
    """Real end-to-end tests for file attachment feature.

    These tests upload real files to S3 and query the Perplexity API with them,
    verifying that the API can access and process the attachment content.
    """

    def test_single_file_attachment_in_thread(self, auth_token, tmp_path, attachment_uploader):
        """Test that a single file attachment is accessible to the API.

        Creates a file with a specific number, uploads it to S3, queries the API
        to extract that number from the attachment, and verifies the response.
        """
        token, cookies = auth_token

        # Create test file with specific content
        test_file = tmp_path / "test_single.md"
        test_content = "The answer is 42"
        test_file.write_text(test_content, encoding="utf-8")

        # Upload file to S3
        file_attachment = FileAttachment.from_file(test_file)
        s3_urls = asyncio.run(attachment_uploader.upload_files([file_attachment]))

        assert len(s3_urls) == 1, f"Expected 1 S3 URL, got {len(s3_urls)}"
        s3_url = s3_urls[0]

        # Query API with attachment
        with PerplexityAPI(token=token, cookies=cookies) as api:
            answer = api.get_complete_answer(
                "What is the answer in this file? Reply with just the number.", attachments=[s3_url]
            )

        # Verify API accessed the attachment and extracted the number
        assert answer.text is not None
        assert "42" in answer.text, f"Expected '42' in response, got: {answer.text}"

    def test_multiple_files_attachment_in_thread(self, auth_token, tmp_path, attachment_uploader):
        """Test that multiple file attachments are accessible to the API.

        Creates two files with different content, uploads them, and verifies
        the API can access both and respond to a question about both files.
        """
        token, cookies = auth_token

        # Create test files
        file1 = tmp_path / "test_file1.md"
        file2 = tmp_path / "test_file2.md"

        file1.write_text("The first number is 100", encoding="utf-8")
        file2.write_text("The second number is 200", encoding="utf-8")

        # Upload files to S3
        attachments = [
            FileAttachment.from_file(file1),
            FileAttachment.from_file(file2),
        ]
        s3_urls = asyncio.run(attachment_uploader.upload_files(attachments))

        assert len(s3_urls) == 2, f"Expected 2 S3 URLs, got {len(s3_urls)}"

        # Query API with both attachments
        with PerplexityAPI(token=token, cookies=cookies) as api:
            answer = api.get_complete_answer(
                "What are the two numbers in the files? Reply with just the numbers.",
                attachments=s3_urls,
            )

        # Verify API accessed both attachments
        assert answer.text is not None
        assert (
            "100" in answer.text and "200" in answer.text
        ), f"Expected both '100' and '200' in response, got: {answer.text}"

    def test_directory_attachment_in_thread(self, auth_token, tmp_path, attachment_uploader):
        """Test that multiple files from a directory are accessible to the API.

        Creates a directory with multiple files, uploads all of them, and verifies
        the API can access all files.
        """
        token, cookies = auth_token

        # Create directory with test files
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        (test_dir / "file1.txt").write_text("First file: value A", encoding="utf-8")
        (test_dir / "file2.txt").write_text("Second file: value B", encoding="utf-8")
        (test_dir / "file3.txt").write_text("Third file: value C", encoding="utf-8")

        # Upload all files from directory
        attachments = [FileAttachment.from_file(f) for f in sorted(test_dir.glob("*.txt"))]
        s3_urls = asyncio.run(attachment_uploader.upload_files(attachments))

        assert len(s3_urls) == 3, f"Expected 3 S3 URLs, got {len(s3_urls)}"

        # Query API with all attachments
        with PerplexityAPI(token=token, cookies=cookies) as api:
            answer = api.get_complete_answer(
                "How many files were provided? Reply with just a number.",
                attachments=s3_urls,
            )

        # Verify API accessed all attachments
        assert answer.text is not None
        assert (
            "3" in answer.text or "three" in answer.text.lower()
        ), f"Expected response about 3 files, got: {answer.text}"

    def test_attachment_content_accessible_in_response(
        self, auth_token, tmp_path, attachment_uploader
    ):
        """Test that attachment content is fully accessible to the API.

        Creates a file with structured data, uploads it, and verifies the API
        can extract specific information from the attachment content.
        """
        token, cookies = auth_token

        # Create test file with structured data
        test_file = tmp_path / "structured_data.md"
        test_content = textwrap.dedent(
            """
            # Product Information

            Product: Widget Pro
            Price: $99.99
            Availability: In Stock
            Rating: 4.8/5

            Features:
            - Lightweight
            - Durable
            - Affordable
            """
        ).strip()
        test_file.write_text(test_content, encoding="utf-8")

        # Upload file to S3
        file_attachment = FileAttachment.from_file(test_file)
        s3_urls = asyncio.run(attachment_uploader.upload_files([file_attachment]))

        # Query API to extract specific information
        with PerplexityAPI(token=token, cookies=cookies) as api:
            answer = api.get_complete_answer(
                "What is the price of the product in the file? Reply with just the price.",
                attachments=s3_urls,
            )

        # Verify API extracted the correct information
        assert answer.text is not None
        assert (
            "99.99" in answer.text or "$99" in answer.text
        ), f"Expected price in response, got: {answer.text}"
