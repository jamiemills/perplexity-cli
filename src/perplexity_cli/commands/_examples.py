"""Realistic JSON example output strings shown in command help text.

Each example keeps a hard-coded ``"version": "0.7.0"`` placeholder so the
source remains readable; :func:`_versioned` substitutes the runtime version
at import time so the rendered help never drifts from ``pyproject.toml``.
"""

from __future__ import annotations

import textwrap

from perplexity_cli.utils.version import get_version

__all__ = [
    "AUTH_LOGIN_JSON_EXAMPLE",
    "AUTH_LOGOUT_JSON_EXAMPLE",
    "AUTH_STATUS_JSON_EXAMPLE",
    "CONFIG_SET_JSON_EXAMPLE",
    "CONFIG_SHOW_JSON_EXAMPLE",
    "DOCTOR_SECURITY_JSON_EXAMPLE",
    "MODELS_LIST_JSON_EXAMPLE",
    "QUERY_JSON_EXAMPLE",
    "QUERY_NDJSON_EXAMPLE",
    "SKILL_SHOW_JSON_EXAMPLE",
    "STYLE_CLEAR_JSON_EXAMPLE",
    "STYLE_SET_JSON_EXAMPLE",
    "STYLE_SHOW_JSON_EXAMPLE",
    "THREADS_EXPORT_JSON_EXAMPLE",
]

_PLACEHOLDER_VERSION = "0.7.0"
_VERSION = get_version()


def _versioned(example: str) -> str:
    """Substitute the placeholder version with the runtime version.

    Args:
        example: JSON example string containing ``"version": "0.7.0"``.

    Returns:
        The example with the runtime version, or the input unchanged when
        the runtime version already matches the placeholder.
    """
    if _VERSION == _PLACEHOLDER_VERSION:
        return example
    return example.replace(
        f'"version": "{_PLACEHOLDER_VERSION}"',
        f'"version": "{_VERSION}"',
    )


QUERY_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli query",
      "result": {
        "answer": "Python is a high-level, general-purpose programming\\n"
                  "language created by Guido van Rossum ...",
        "references": [
          {
            "name": "Python (programming language) - Wikipedia",
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
)

QUERY_NDJSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {"type": "start", "ts": "2025-05-09T10:00:00+00:00", "command": "pxcli query --json --stream"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": "Python is a"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": " high-level"}
    {"type": "chunk", "ts": "2025-05-09T10:00:02+00:00", "text": " programming language..."}
    {"type": "result", "ts": "2025-05-09T10:00:03+00:00", "ok": true, "command": "pxcli query --json --stream", "result": {"answer": "Python is a high-level programming language...", "references": [{"name": "...", "url": "...", "snippet": "..."}]}, "meta": {"duration_ms": 3000, "version": "0.7.0", "trace_id": "...", "truncated": false}, "next_actions": []}""")
)

AUTH_LOGIN_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli auth login",
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
)

AUTH_LOGOUT_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli auth logout",
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
)

AUTH_STATUS_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli auth status",
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
)

CONFIG_SET_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli config set",
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
)

CONFIG_SHOW_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli config show",
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
)

STYLE_SET_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli style set",
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
)

STYLE_SHOW_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli style show",
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
)

STYLE_CLEAR_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli style clear",
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
)

THREADS_EXPORT_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli threads export",
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
        "output_path": "/abs/path/to/threads-20250509-100000.csv",
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
)

SKILL_SHOW_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli skill show",
      "result": {
        "content": "# perplexity-cli Agent Skill\\n\\nUse perplexity-cli ..."
      },
      "meta": {
        "duration_ms": 2,
        "version": "0.7.0",
        "trace_id": "e1f2a3b4-c5d6-7890-efab-901234567890",
        "truncated": false
      },
      "next_actions": []
    }""")
)

DOCTOR_SECURITY_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli doctor security",
      "result": {
        "storage_backend": "machine-bound encrypted file storage",
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "token_permissions": "secure (0o600)",
        "cache_path": "/Users/you/.config/perplexity-cli/threads-cache.json",
        "cache_permissions": "secure (0o600)",
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
)

MODELS_LIST_JSON_EXAMPLE = _versioned(
    textwrap.dedent("""\
    {
      "ok": true,
      "command": "pxcli models list",
      "result": {
        "models": [
          {
            "model_id": "pplx_pro",
            "label": "Best",
            "tier": "pro",
            "description": "Auto-select the best model for the query",
            "reasoning_model": null,
            "is_default": true
          },
          {
            "model_id": "gpt54",
            "label": "GPT-5.4",
            "tier": "pro",
            "description": "OpenAI GPT-5.4",
            "reasoning_model": "gpt54_reasoning",
            "is_default": false
          }
        ]
      },
      "meta": {
        "duration_ms": 620,
        "version": "0.7.0",
        "trace_id": "0a1b2c3d-4e5f-6789-abcd-0123456789ab",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli query --model gpt54",
          "description": "Use a specific model for a query"
        }
      ]
    }""")
)
