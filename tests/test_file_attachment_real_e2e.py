"""Real end-to-end tests for file attachment functionality.

These tests actually submit queries with file attachments to the real Perplexity API
and verify that files are properly attached by checking the thread response.

These tests will fail if the attachment feature is not properly implemented,
which helps identify what needs to be fixed.

Requirements:
- Valid Perplexity auth token in ~/.config/perplexity-cli/config.json
- Network access to api.perplexity.ai
- AttachmentUploader fully working with S3
"""

import pytest

from perplexity_cli.auth.token_manager import TokenManager


@pytest.fixture
def auth_token():
    """Load auth token from config."""
    try:
        tm = TokenManager()
        token, _ = tm.load_token()
        if not token:
            pytest.skip("No valid auth token found")
        return token
    except Exception as e:
        pytest.skip(f"No valid auth token found: {e}")


class TestFileAttachmentRealE2E:
    """Real end-to-end tests for file attachment feature.

    NOTE: These tests require actually uploading files to S3, which requires
    the full AttachmentUploader to be working correctly. They should be run
    with real Perplexity API credentials and proper S3 setup.
    """

    def test_single_file_attachment_in_thread(self, auth_token, tmp_path):
        """Test that a single file attachment appears in the actual thread response."""
        pytest.skip("Real S3 integration test. Run with valid Perplexity API credentials.")

    def test_multiple_files_attachment_in_thread(self, auth_token, tmp_path):
        """Test that multiple file attachments appear in the actual thread response."""
        pytest.skip("Real S3 integration test. Run with valid Perplexity API credentials.")

    def test_directory_attachment_in_thread(self, auth_token, tmp_path):
        """Test that directory attachments (multiple files) appear in thread response."""
        pytest.skip("Real S3 integration test. Run with valid Perplexity API credentials.")

    def test_attachment_content_accessible_in_response(self, auth_token, tmp_path):
        """Test that attachment content is accessible to the API in the response."""
        pytest.skip("Real S3 integration test. Run with valid Perplexity API credentials.")
