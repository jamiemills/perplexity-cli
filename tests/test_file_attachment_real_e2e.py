"""Real end-to-end tests for file attachment functionality.

These tests actually submit queries with file attachments to the real Perplexity API
and verify that files are properly attached by checking the thread response.

These tests will fail if the attachment feature is not properly implemented,
which helps identify what needs to be fixed.

Requirements:
- Valid Perplexity auth token in ~/.config/perplexity-cli/config.json
- Network access to api.perplexity.ai
"""

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import FileAttachment
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
    """Real end-to-end tests for file attachment feature."""

    def test_single_file_attachment_in_thread(self, auth_token, tmp_path):
        """Test that a single file attachment appears in the actual thread response."""
        # Create a test file with unique content
        test_file = tmp_path / "test_attachment_single.txt"
        test_file.write_text(
            "Test file for attachment - single file test\nContent: This is test content",
            encoding="utf-8",
        )

        # Create attachment
        attachment = FileAttachment.from_file(test_file)

        # Submit query with attachment to real API
        with PerplexityAPI(token=auth_token) as api:
            # Collect all messages to get the final response with thread info
            messages = []
            for message in api.submit_query(
                "What files were attached to this query? List the filenames.",
                attachments=[attachment],
            ):
                messages.append(message)

        # Get the final message which should contain attachment info
        assert len(messages) > 0, "No messages received from API"
        final_message = messages[-1]

        # Verify attachment is in the thread response
        assert hasattr(final_message, "attachments") or (
            isinstance(final_message, dict) and "attachments" in final_message
        ), "No attachments field in final message"

        # Get attachments from message
        attachments = (
            final_message.attachments
            if hasattr(final_message, "attachments")
            else final_message.get("attachments", [])
        )

        assert (
            len(attachments) >= 1
        ), f"Expected at least 1 attachment in thread, got {len(attachments)}"
        assert any(
            "test_attachment_single" in str(att) for att in attachments
        ), f"Expected attachment with filename 'test_attachment_single', got {attachments}"

    def test_multiple_files_attachment_in_thread(self, auth_token, tmp_path):
        """Test that multiple file attachments appear in the actual thread response."""
        # Create two test files
        file1 = tmp_path / "test_file_1.txt"
        file2 = tmp_path / "test_file_2.md"
        file1.write_text("Test file 1 content", encoding="utf-8")
        file2.write_text("# Test file 2\nMarkdown content here", encoding="utf-8")

        # Create attachments
        attachments = [
            FileAttachment.from_file(file1),
            FileAttachment.from_file(file2),
        ]

        # Submit query with attachments to real API
        with PerplexityAPI(token=auth_token) as api:
            messages = []
            for message in api.submit_query(
                "What files were attached? List them with their types.",
                attachments=attachments,
            ):
                messages.append(message)

        assert len(messages) > 0, "No messages received from API"
        final_message = messages[-1]

        # Verify both attachments are in the thread response
        thread_attachments = (
            final_message.attachments
            if hasattr(final_message, "attachments")
            else final_message.get("attachments", [])
        )

        assert (
            len(thread_attachments) >= 2
        ), f"Expected at least 2 attachments, got {len(thread_attachments)}"
        attachment_str = " ".join(str(a) for a in thread_attachments)
        assert (
            "test_file_1" in attachment_str
        ), f"Expected 'test_file_1' in attachments, got {thread_attachments}"
        assert (
            "test_file_2" in attachment_str
        ), f"Expected 'test_file_2' in attachments, got {thread_attachments}"

    def test_directory_attachment_in_thread(self, auth_token, tmp_path):
        """Test that directory attachments (multiple files) appear in thread response."""
        # Create a test directory with files
        test_dir = tmp_path / "test_directory"
        test_dir.mkdir()

        (test_dir / "doc1.txt").write_text("Document 1", encoding="utf-8")
        (test_dir / "doc2.txt").write_text("Document 2", encoding="utf-8")

        # Create subdirectory with file
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "doc3.txt").write_text("Document 3", encoding="utf-8")

        # Create attachments from all files
        attachments = [
            FileAttachment.from_file(test_dir / "doc1.txt"),
            FileAttachment.from_file(test_dir / "doc2.txt"),
            FileAttachment.from_file(subdir / "doc3.txt"),
        ]

        # Submit query with directory attachments to real API
        with PerplexityAPI(token=auth_token) as api:
            messages = []
            for message in api.submit_query(
                "List all attached files and their names.", attachments=attachments
            ):
                messages.append(message)

        assert len(messages) > 0, "No messages received from API"
        final_message = messages[-1]

        # Verify all files from directory are in thread response
        thread_attachments = (
            final_message.attachments
            if hasattr(final_message, "attachments")
            else final_message.get("attachments", [])
        )

        assert (
            len(thread_attachments) >= 3
        ), f"Expected at least 3 attachments from directory, got {len(thread_attachments)}"
        attachment_str = " ".join(str(a) for a in thread_attachments)
        assert "doc1" in attachment_str, f"Expected 'doc1' in {thread_attachments}"
        assert "doc2" in attachment_str, f"Expected 'doc2' in {thread_attachments}"
        assert "doc3" in attachment_str, f"Expected 'doc3' in {thread_attachments}"

    def test_attachment_content_accessible_in_response(self, auth_token, tmp_path):
        """Test that attachment content is accessible to the API in the response."""
        # Create a test file with specific content
        test_file = tmp_path / "content_test.txt"
        test_content = "UNIQUE_TEST_MARKER_12345: This is the specific content"
        test_file.write_text(test_content, encoding="utf-8")

        attachment = FileAttachment.from_file(test_file)

        # Submit query asking about the file content
        with PerplexityAPI(token=auth_token) as api:
            answer = api.get_complete_answer(
                "What is the exact content of the attached file? Return the exact text.",
                attachments=[attachment],
            )

        # Verify the answer references the file content
        answer_text = answer.text.lower()
        assert len(answer_text) > 0, "No answer received from API"
        # The API should either mention the file or its content
        assert (
            "content_test" in answer_text or "unique" in answer_text or "12345" in answer_text
        ), f"Expected answer to reference file content or name, got: {answer.text[:200]}"
