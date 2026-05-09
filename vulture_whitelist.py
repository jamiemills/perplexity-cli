"""Vulture whitelist -- items listed here are known false positives.

Vulture cannot detect usage of Pydantic model fields, validators,
serialisers, or model_config; context-manager protocol parameters;
enum/constant values used externally; or functions exercised only via
tests or CLI entry points.

This file is consumed by vulture via:
    vulture src/ vulture_whitelist.py --min-confidence 80
"""

# ---------------------------------------------------------------------------
# Context-manager protocol parameters (__exit__ / __aexit__)
# ---------------------------------------------------------------------------
exc_type
exc_val
exc_tb

# ---------------------------------------------------------------------------
# Pydantic model_config (BaseModel class variable)
# ---------------------------------------------------------------------------
model_config

# ---------------------------------------------------------------------------
# Pydantic model fields (used for serialisation/deserialisation)
# ---------------------------------------------------------------------------
# api/models.py -- QueryPayload
search_focus
mode
sources
search_recency_filter
model_preference
is_related_query
is_sponsored
prompt_source
query_source
is_incognito
local_search_enabled
use_schematized_api
send_back_text_in_streaming_api
client_coordinates
mentions
skip_search_enabled
is_nav_suggestions_disabled
always_search_override
override_no_search
should_ask_for_mcp_tool_confirmation
browser_agent_allow_once_from_toggle

# api/models.py -- PerplexityResponse
backend_uuid
context_uuid
display_model
thread_url_slug
text_completed
cursor
read_write_token

# auth/models.py
domain
httponly
expires
is_encrypted
has_cookies

# envelope.py
not_found
truncated
description
input

# ndjson.py
ts

# threads/models.py
last_sync_time
oldest_thread_date
newest_thread_date

# ---------------------------------------------------------------------------
# Pydantic validators / serialisers (@field_validator, @model_validator, etc.)
# ---------------------------------------------------------------------------
_.validate_filename
_.validate_content_type
_.validate_data
_.validate_search_mode
_._validate_upstream_shape
_._split_flat_payload
_._derive_web_results
_.validate_token
_.validate_created_at
_.serialize_created_at
_.validate_name
_.validate_age_days
_.validate_urls
_.validate_sync_time
_.validate_total_threads
_.validate_cache
_.validate_threads
_.validate_style

# ---------------------------------------------------------------------------
# Exit-code constants (public API, referenced by name in docs/help text)
# ---------------------------------------------------------------------------
SUCCESS
USAGE_ERROR
NOT_FOUND
CONFLICT

# ---------------------------------------------------------------------------
# Classes used in tests or forming part of the public API surface
# ---------------------------------------------------------------------------
TokenFormat
CookieData
TokenMetadata
RateLimiterConfig

# ---------------------------------------------------------------------------
# Functions/methods exercised via tests or forming part of the public API
# ---------------------------------------------------------------------------
load_or_prompt_token
_.should_use_colors
should_use_plain_default
resolve_format
build_help_json
_.progress
_.create
_.log_invocation
_.log_response
_.get_cache_coverage
parse_absolute_date_string
clear_urls_cache
classify_http_error
classify_network_error
configure_quiet_mode
enable_structured_logging
_.get_stats
retry_http_request
sleep_with_backoff
is_curl_cffi_available
get_version_from_pyproject
_.extract_plan_info
