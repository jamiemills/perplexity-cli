"""Tests for Thread models and related functionality."""

import json

import pytest

from perplexity_cli.api.models import Collection, SocialInfo, Thread, ThreadContext


class TestSocialInfo:
    """Test SocialInfo model."""

    def test_social_info_from_dict(self):
        """Test SocialInfo creation from dictionary."""
        data = {
            "view_count": 10,
            "fork_count": 2,
            "like_count": 5,
            "user_likes": True,
        }
        social_info = SocialInfo.from_dict(data)
        assert social_info.view_count == 10
        assert social_info.fork_count == 2
        assert social_info.like_count == 5
        assert social_info.user_likes is True

    def test_social_info_defaults(self):
        """Test SocialInfo with default values."""
        social_info = SocialInfo()
        assert social_info.view_count == 0
        assert social_info.fork_count == 0
        assert social_info.like_count == 0
        assert social_info.user_likes is False

    def test_social_info_partial_data(self):
        """Test SocialInfo with partial data."""
        data = {"view_count": 5}
        social_info = SocialInfo.from_dict(data)
        assert social_info.view_count == 5
        assert social_info.fork_count == 0  # default
        assert social_info.user_likes is False  # default


class TestThreadContext:
    """Test ThreadContext model."""

    def test_thread_context_creation(self):
        """Test ThreadContext creation."""
        context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
            read_write_token="token-123",
        )
        assert context.thread_url_slug == "test-slug"
        assert context.frontend_context_uuid == "frontend-uuid"
        assert context.context_uuid == "context-uuid"
        assert context.read_write_token == "token-123"

    def test_thread_context_to_dict(self):
        """Test ThreadContext serialization."""
        context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
            read_write_token="token-123",
        )
        data = context.to_dict()
        assert data["thread_url_slug"] == "test-slug"
        assert data["frontend_context_uuid"] == "frontend-uuid"
        assert data["context_uuid"] == "context-uuid"
        assert data["read_write_token"] == "token-123"

    def test_thread_context_from_dict(self):
        """Test ThreadContext deserialization."""
        data = {
            "thread_url_slug": "test-slug",
            "frontend_context_uuid": "frontend-uuid",
            "context_uuid": "context-uuid",
            "read_write_token": "token-123",
        }
        context = ThreadContext.from_dict(data)
        assert context.thread_url_slug == "test-slug"
        assert context.frontend_context_uuid == "frontend-uuid"
        assert context.context_uuid == "context-uuid"
        assert context.read_write_token == "token-123"

    def test_thread_context_optional_token(self):
        """Test ThreadContext with optional read_write_token."""
        context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
            read_write_token=None,
        )
        assert context.read_write_token is None


class TestThread:
    """Test Thread model."""

    def test_thread_from_dict(self):
        """Test Thread creation from API response dictionary."""
        data = {
            "thread_number": 0,
            "slug": "what-is-python-HDn1I22.QKCoDctO58P2UA",
            "title": "What is Python?",
            "context_uuid": "ea323fd3-df7a-43ea-bbdb-3c6fa6f4a0f5",
            "frontend_context_uuid": "40a32424-1609-445e-ba2b-e198f654e0ef",
            "read_write_token": "d54938fc-5ebe-41cc-9e60-3ed074e78d9c",
            "first_answer": '{"answer":"Python is a programming language..."}',
            "last_query_datetime": "2025-11-09T17:55:06.207507",
            "query_count": 1,
            "total_threads": 99,
            "has_next_page": True,
            "mode": "copilot",
            "uuid": "1c39f523-6dbe-40a0-a80d-cb4ee7c3f650",
            "frontend_uuid": "924b1b53-5b5a-4f1e-a70d-adde0b246add",
            "thread_access": 1,
            "status": "COMPLETED",
            "first_entry_model_preference": "PPLX_PRO",
            "display_model": "pplx_pro",
            "expiry_time": None,
            "source": "default",
            "source_metadata": None,
            "thread_status": "completed",
            "is_personal_intent": False,
            "is_mission_control": False,
            "stream_created_at": None,
            "unread": False,
            "search_focus": "internet",
            "search_recency_filter": None,
            "sources": ["web"],
            "featured_images": [],
            "social_info": {
                "view_count": 0,
                "fork_count": 0,
                "like_count": 0,
                "user_likes": False,
            },
        }
        thread = Thread.from_dict(data)
        assert thread.slug == "what-is-python-HDn1I22.QKCoDctO58P2UA"
        assert thread.title == "What is Python?"
        assert thread.query_count == 1
        assert thread.total_threads == 99
        assert thread.has_next_page is True
        assert thread.mode == "copilot"
        assert thread.status == "COMPLETED"
        assert isinstance(thread.social_info, SocialInfo)

    def test_thread_to_thread_context(self):
        """Test Thread conversion to ThreadContext."""
        thread = Thread(
            thread_number=0,
            slug="test-slug",
            title="Test Thread",
            context_uuid="context-uuid",
            frontend_context_uuid="frontend-uuid",
            read_write_token="token-123",
            first_answer='{"answer":"test"}',
            last_query_datetime="2025-11-09T00:00:00",
            query_count=1,
            total_threads=1,
            has_next_page=False,
            mode="copilot",
            uuid="uuid-123",
            frontend_uuid="frontend-uuid-123",
            thread_access=1,
            status="COMPLETED",
            first_entry_model_preference="PPLX_PRO",
            display_model="pplx_pro",
        )
        context = thread.to_thread_context()
        assert isinstance(context, ThreadContext)
        assert context.thread_url_slug == "test-slug"
        assert context.frontend_context_uuid == "frontend-uuid"
        assert context.context_uuid == "context-uuid"
        assert context.read_write_token == "token-123"

    def test_thread_defaults(self):
        """Test Thread with default values."""
        data = {
            "thread_number": 0,
            "slug": "test",
            "title": "Test",
            "context_uuid": "uuid",
            "frontend_context_uuid": "uuid",
            "read_write_token": "token",
            "first_answer": "{}",
            "last_query_datetime": "2025-01-01T00:00:00",
            "query_count": 0,
            "total_threads": 0,
            "has_next_page": False,
            "mode": "copilot",
            "uuid": "uuid",
            "frontend_uuid": "uuid",
            "thread_access": 1,
            "status": "COMPLETED",
            "first_entry_model_preference": "PPLX_PRO",
            "display_model": "pplx_pro",
        }
        thread = Thread.from_dict(data)
        assert thread.sources == ["web"]  # default
        assert thread.featured_images == []  # default
        assert isinstance(thread.social_info, SocialInfo)


class TestCollection:
    """Test Collection model."""

    def test_collection_from_dict(self):
        """Test Collection creation from API response dictionary."""
        data = {
            "number": 0,
            "uuid": "ea2fe0c5-cd76-4e9d-8475-262516df10e0",
            "title": "DS and AI",
            "description": "",
            "slug": "ds-and-ai-6i_gxc12Tp2EdSYlFt8Q4A",
            "updated_datetime": "2025-07-06T18:15:12.957599",
            "has_next_page": False,
            "thread_count": 0,
            "page_count": 0,
            "access": 1,
            "user_permission": 4,
            "emoji": "1f4d0",
            "instructions": "",
            "suggested_queries": None,
            "s3_social_preview_url": None,
            "model_selection": None,
            "template_id": None,
            "file_count": 0,
            "focused_web_config": None,
            "max_contributors": None,
            "enable_web_by_default": True,
        }
        collection = Collection.from_dict(data)
        assert collection.title == "DS and AI"
        assert collection.slug == "ds-and-ai-6i_gxc12Tp2EdSYlFt8Q4A"
        assert collection.thread_count == 0
        assert collection.enable_web_by_default is True

