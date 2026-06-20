"""Realistic JSON example output strings shown in command help text."""

from __future__ import annotations

import textwrap

__all__ = [
    "AUTH_LOGIN_JSON_EXAMPLE",
    "AUTH_LOGOUT_JSON_EXAMPLE",
    "AUTH_STATUS_JSON_EXAMPLE",
    "CONFIG_SET_JSON_EXAMPLE",
    "CONFIG_SHOW_JSON_EXAMPLE",
    "DOCTOR_SECURITY_JSON_EXAMPLE",
    "QUERY_JSON_EXAMPLE",
    "QUERY_NDJSON_EXAMPLE",
    "SKILL_SHOW_JSON_EXAMPLE",
    "STYLE_CLEAR_JSON_EXAMPLE",
    "STYLE_SET_JSON_EXAMPLE",
    "STYLE_SHOW_JSON_EXAMPLE",
    "THREADS_EXPORT_JSON_EXAMPLE",
]

QUERY_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "query",
      "result": {
        "answer": "Python is a high-level, general-purpose programming\\n"
                  "language created by Guido van Rossum ...",
        "references": [
          {
            "index": 1,
            "title": "Python (programming language) - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "snippet": "Python is a high-level, general-purpose programming language."
          }
        ]
      },
      "meta": {
        "duration_ms": 2340,
        "version": "0.7.0",
        "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli query",
          "description": "Ask a follow-up question"
        }
      ]
    }""")

QUERY_NDJSON_EXAMPLE = textwrap.dedent("""\
    {"type": "start", "ts": "2025-05-09T10:00:00+00:00", "command": "query"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": "Python is a"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": " high-level"}
    {"type": "chunk", "ts": "2025-05-09T10:00:02+00:00", "text": " programming language..."}
    {"type": "result", "ts": "2025-05-09T10:00:03+00:00", "ok": true, "command": "query", "result": {"answer": "Python is a high-level programming language...", "references": [...]}, "meta": {"duration_ms": 3000, "version": "0.7.0", "trace_id": "...", "truncated": false}, "next_actions": []}""")

AUTH_LOGIN_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth login",
      "result": {
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "cookies_stored": 12
      },
      "meta": {
        "duration_ms": 450,
        "version": "0.7.0",
        "trace_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth status",
          "description": "Verify authentication is working"
        }
      ]
    }""")

AUTH_LOGOUT_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth logout",
      "result": {
        "credentials_existed": true
      },
      "meta": {
        "duration_ms": 15,
        "version": "0.7.0",
        "trace_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth login",
          "description": "Re-authenticate when needed"
        }
      ]
    }""")

AUTH_STATUS_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth status",
      "result": {
        "authenticated": true,
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "token_age_days": 3,
        "cookies_stored": 12,
        "verified": null
      },
      "meta": {
        "duration_ms": 20,
        "version": "0.7.0",
        "trace_id": "d4e5f6a7-b8c9-0123-defa-234567890123",
        "truncated": false
      },
      "next_actions": []
    }""")

CONFIG_SET_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "config set",
      "result": {
        "key": "save_cookies",
        "value": true
      },
      "meta": {
        "duration_ms": 8,
        "version": "0.7.0",
        "trace_id": "e5f6a7b8-c9d0-1234-efab-345678901234",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli config show",
          "description": "View updated configuration"
        }
      ]
    }""")

CONFIG_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "config show",
      "result": {
        "config_path": "/Users/you/.config/perplexity-cli/config.json",
        "save_cookies": true,
        "debug_mode": false,
        "env_overrides": []
      },
      "meta": {
        "duration_ms": 5,
        "version": "0.7.0",
        "trace_id": "f6a7b8c9-d0e1-2345-fabc-456789012345",
        "truncated": false
      },
      "next_actions": []
    }""")

STYLE_SET_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style set",
      "result": {
        "style": "be brief and concise"
      },
      "meta": {
        "duration_ms": 6,
        "version": "0.7.0",
        "trace_id": "a7b8c9d0-e1f2-3456-abcd-567890123456",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli style show",
          "description": "Verify the configured style"
        }
      ]
    }""")

STYLE_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style show",
      "result": {
        "style": "be brief and concise"
      },
      "meta": {
        "duration_ms": 3,
        "version": "0.7.0",
        "trace_id": "b8c9d0e1-f2a3-4567-bcde-678901234567",
        "truncated": false
      },
      "next_actions": []
    }""")

STYLE_CLEAR_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style clear",
      "result": {
        "had_style": true
      },
      "meta": {
        "duration_ms": 4,
        "version": "0.7.0",
        "trace_id": "c9d0e1f2-a3b4-5678-cdef-789012345678",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli style set",
          "description": "Configure a new style"
        }
      ]
    }""")

THREADS_EXPORT_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "threads export",
      "result": {
        "threads": [
          {
            "title": "How does quantum computing work?",
            "created_at": "2025-05-08T14:30:00+00:00",
            "url": "https://www.perplexity.ai/search/how-does-quantum-abc123"
          },
          {
            "title": "Best Python testing frameworks",
            "created_at": "2025-05-07T09:15:00+00:00",
            "url": "https://www.perplexity.ai/search/best-python-testing-def456"
          }
        ],
        "total": 2,
        "output_path": "threads-20250509-100000.csv",
        "date_range": {
          "from": null,
          "to": null
        }
      },
      "meta": {
        "duration_ms": 1250,
        "version": "0.7.0",
        "trace_id": "d0e1f2a3-b4c5-6789-defa-890123456789",
        "truncated": false
      },
      "next_actions": []
    }""")

SKILL_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "skill show",
      "result": {
        "skill_md": "# perplexity-cli Agent Skill\\n\\nUse perplexity-cli ..."
      },
      "meta": {
        "duration_ms": 2,
        "version": "0.7.0",
        "trace_id": "e1f2a3b4-c5d6-7890-efab-901234567890",
        "truncated": false
      },
      "next_actions": []
    }""")

DOCTOR_SECURITY_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "doctor security",
      "result": {
        "storage_backend": "encrypted_file",
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "token_permissions": "600",
        "cache_path": "/Users/you/.config/perplexity-cli/threads_cache.json",
        "cache_permissions": "600",
        "cookies_enabled": true
      },
      "meta": {
        "duration_ms": 10,
        "version": "0.7.0",
        "trace_id": "f2a3b4c5-d6e7-8901-fabc-012345678901",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth status",
          "description": "Check authentication state"
        }
      ]
    }""")
