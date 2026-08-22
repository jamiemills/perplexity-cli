"""Integration tests for file attachment feature with CLI.

The ``query`` command is exercised through ``CliRunner`` with typed
outer-boundary fakes (``FakeAttachmentUploader``, ``FakePerplexityAPI``,
``FakeTokenManager``, ``FakeStyleManager``) substituted at the command's
dependency boundaries.  Tests assert the exact attachment order and body
threaded into the query, plus stdout/stderr channel separation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import query
from tests.helpers.fake_uploader import FakeAttachmentUploader
from tests.helpers.query_deps import patch_query_deps


class FakeTokenManager:
    """Typed fake for ``TokenManager`` at the CLI boundary."""

    def __init__(self, token: tuple[str | None, dict[str, str] | None] = ("test-token", None)):
        """Initialise with the ``load_token`` result to return."""
        self.load_token_result = token
        self.load_calls = 0

    def load_token(self) -> tuple[str | None, dict[str, str] | None]:
        """Return the configured token pair and record the call."""
        self.load_calls += 1
        return self.load_token_result


class FakeStyleManager:
    """Typed fake for ``StyleManager`` at the CLI boundary."""

    def __init__(self, style: str | None = None) -> None:
        """Initialise with the style prompt ``load_style`` should return."""
        self.style = style
        self.load_calls = 0

    def load_style(self) -> str | None:
        """Return the configured style and record the call."""
        self.load_calls += 1
        return self.style


class FakePerplexityAPI:
    """Typed fake for ``PerplexityAPI`` at the CLI boundary.

    Records every ``get_complete_answer`` call so tests can assert the exact
    attachment URL order that was threaded into the query request.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise with a canned answer and no recorded calls."""
        self.answer = Answer(text="Test answer", references=[])
        self.uploaded_attachments: list[list[str] | None] = []

    def __enter__(self) -> FakePerplexityAPI:
        """Support the ``with`` usage in the query runner."""
        return self

    def __exit__(self, *exc_info: object) -> bool:
        """Exit the context manager without suppressing exceptions."""
        return False

    def close(self) -> None:
        """No-op close to satisfy the real client interface."""

    def get_complete_answer(
        self,
        query: str,
        search_implementation_mode: str = "standard",
        *,
        extra_params: tuple[list[str] | None, str | None, dict[str, object] | None] = (
            None,
            None,
            None,
        ),
    ) -> Answer:
        """Record the extra_params and return the canned answer."""
        attachments, _model_preference, _request_params = extra_params
        self.uploaded_attachments.append(attachments)
        return self.answer


@pytest.fixture
def query_app(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager]:
    """Provide typed boundary fakes for every query dependency.

    Returns ``(fake_api, fake_uploader, fake_tm, fake_sm)`` so callers can
    configure results and assert call args without nested ``patch`` blocks.
    """
    fake_api = FakePerplexityAPI()
    fake_uploader = FakeAttachmentUploader()
    fake_tm = FakeTokenManager()
    fake_sm = FakeStyleManager()

    patch_query_deps(
        monkeypatch,
        StyleManager=lambda *args, **kwargs: fake_sm,
    )
    patch_query_deps(
        monkeypatch,
        TokenManager=lambda *args, **kwargs: fake_tm,
    )
    monkeypatch.setattr(
        "perplexity_cli.attachments.AttachmentUploader",
        lambda *args, **kwargs: fake_uploader,
    )
    patch_query_deps(
        monkeypatch,
        PerplexityAPI=lambda *args, **kwargs: fake_api,
    )
    return fake_api, fake_uploader, fake_tm, fake_sm


class TestAttachmentsIntegration:
    """Integration tests for file attachment feature."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Provide an isolated CLI runner."""
        return CliRunner()

    @staticmethod
    def _uploaded_filenames(uploader: FakeAttachmentUploader) -> list[str]:
        """Return the attachment filenames recorded by the fake uploader."""
        return [attachment.filename for attachment in uploader.received[0]]

    # -- Single attachment --------------------------------------------------

    def test_query_with_single_attachment(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """A single file attachment uploads and its URL reaches the query."""
        fake_api, fake_uploader, _fake_tm, _fake_sm = query_app

        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
        fake_uploader.set_results([s3_url])

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(test_file), "What is this file?"],
        )

        assert result.exit_code == 0
        assert result.exception is None
        assert "Test answer" in result.stdout
        assert "[ERROR]" not in result.stdout
        assert fake_api.uploaded_attachments == [[s3_url]]
        assert fake_uploader.upload_calls == 1
        assert self._uploaded_filenames(fake_uploader) == ["test.txt"]

    # -- Multiple attachments -----------------------------------------------

    def test_query_with_multiple_attachments(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """Multiple files upload in order and their URLs reach the query."""
        fake_api, fake_uploader, _fake_tm, _fake_sm = query_app

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.md"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.md",
        ]
        fake_uploader.set_results(s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", f"{file1},{file2}", "Compare these files"],
        )

        assert result.exit_code == 0
        assert result.exception is None
        assert "Test answer" in result.stdout
        assert "[ERROR]" not in result.stdout
        assert fake_api.uploaded_attachments == [s3_urls]
        assert fake_uploader.upload_calls == 1
        assert self._uploaded_filenames(fake_uploader) == ["file1.txt", "file2.md"]

    # -- Repeated attach flags ----------------------------------------------

    def test_query_with_repeated_attach_flags(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """Repeated ``--attach`` flags accumulate files in order."""
        fake_api, fake_uploader, _fake_tm, _fake_sm = query_app

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("Content 2", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
        ]
        fake_uploader.set_results(s3_urls)

        result = runner.invoke(
            query,
            [
                "--no-stream",
                "--attach",
                str(file1),
                "--attach",
                str(file2),
                "Process these",
            ],
        )

        assert result.exit_code == 0
        assert result.exception is None
        assert "Test answer" in result.stdout
        assert "[ERROR]" not in result.stdout
        assert fake_api.uploaded_attachments == [s3_urls]
        assert fake_uploader.upload_calls == 1
        assert self._uploaded_filenames(fake_uploader) == ["file1.txt", "file2.txt"]

    # -- Nonexistent file ---------------------------------------------------

    def test_query_attachment_nonexistent_file_error(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
    ) -> None:
        """A nonexistent attachment fails cleanly to stderr, never stdout."""
        _fake_api, _fake_uploader, _fake_tm, _fake_sm = query_app

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", "/nonexistent/file.txt", "Test"],
        )

        assert result.exit_code == 7
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 7
        # Exact attachment-failure contract goes to stderr, never stdout.
        assert (
            "Error: Failed to load attachments: "
            "File or directory not found: /nonexistent/file.txt" in result.stderr
        )
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""

    # -- Directory attachment -----------------------------------------------

    def test_query_with_directory_attachment(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """A directory attachment uploads every eligible file in order."""
        fake_api, fake_uploader, _fake_tm, _fake_sm = query_app

        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Content 2", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("Content 3", encoding="utf-8")

        s3_urls = [
            f"https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/{name}"
            for name in ("file1.txt", "file2.txt", "file3.txt")
        ]
        fake_uploader.set_results(s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 0
        assert result.exception is None
        assert "Test answer" in result.stdout
        assert "[ERROR]" not in result.stdout
        assert fake_api.uploaded_attachments == [s3_urls]
        assert fake_uploader.upload_calls == 1
        assert self._uploaded_filenames(fake_uploader) == [
            "file1.txt",
            "file2.txt",
            "file3.txt",
        ]

    # -- Directory skips hidden / sensitive ---------------------------------

    def test_query_with_directory_attachment_skips_hidden_and_sensitive_files(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """Hidden and sensitive files in a directory are never uploaded."""
        fake_api, fake_uploader, _fake_tm, _fake_sm = query_app

        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
        (tmp_path / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (tmp_path / "private.key").write_text("key", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt"
        ]
        fake_uploader.set_results(s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 0
        assert result.exception is None
        assert "Test answer" in result.stdout
        assert "[ERROR]" not in result.stdout
        assert fake_api.uploaded_attachments == [s3_urls]
        assert self._uploaded_filenames(fake_uploader) == ["file1.txt"]
        # Sensitive / hidden files must never be uploaded.
        assert all(".env" not in url and ".hidden" not in url for url in s3_urls)
        assert all("private.key" not in url for url in s3_urls)
        assert fake_uploader.upload_calls == 1

    # -- Too many directory files -------------------------------------------

    def test_query_with_too_many_directory_files_fails(
        self,
        runner: CliRunner,
        query_app: tuple[
            FakePerplexityAPI, FakeAttachmentUploader, FakeTokenManager, FakeStyleManager
        ],
        tmp_path: Path,
    ) -> None:
        """A directory exceeding the attachment count limit fails cleanly."""
        _fake_api, _fake_uploader, _fake_tm, _fake_sm = query_app

        from perplexity_cli.utils.file_handler import MAX_ATTACHMENT_COUNT

        for index in range(MAX_ATTACHMENT_COUNT + 1):
            (tmp_path / f"file-{index}.txt").write_text("content", encoding="utf-8")

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 7
        assert "Too many attachments" in result.output
