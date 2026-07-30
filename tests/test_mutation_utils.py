"""Mutation-killing tests for utils/ modules."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.config import (
    ConfigPaths,
    clear_feature_config_cache,
    clear_urls_cache,
    get_config_dir,
    get_feature_config_path,
    get_model_config_endpoint,
    get_perplexity_base_url,
    get_query_endpoint,
    get_s3_bucket_url,
    get_thread_list_url,
    get_upload_url_endpoint,
    get_user_settings_endpoint,
    set_feature,
)
from perplexity_cli.utils.config.contracts import (
    default_feature_config as _get_default_feature_config,
)
from perplexity_cli.utils.config.contracts import (
    default_rate_limiting as _get_default_rate_limiting,
)
from perplexity_cli.utils.config.contracts import (
    is_str_dict as _is_str_dict,
)
from perplexity_cli.utils.config.impl import (
    _apply_feature_env_overrides,
    _apply_rate_limiting_enabled,
    _apply_rate_limiting_period,
    _apply_rate_limiting_rps,
    _apply_url_env_overrides,
    _merge_rate_limiting_section,
)
from perplexity_cli.utils.encryption import (
    _ENCRYPTED_TOKEN_VERSION_PREFIX,
    _build_key_material,
    _decrypt_with_current_format,
    _derive_encryption_key_legacy,
    _derive_fernet_key,
    decrypt_token,
    encrypt_token,
)
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.file_handler import (
    MAX_ATTACHMENT_COUNT,
    MAX_ATTACHMENT_FILE_SIZE,
    MAX_TOTAL_ATTACHMENT_SIZE,
    SKIPPED_DIRECTORY_NAMES,
    SKIPPED_FILENAME_PREFIXES,
    SKIPPED_FILENAME_SUFFIXES,
    _extract_file_paths_from_text,
    _should_include_file,
    _should_skip_directory_entry,
    load_attachments,
)
from perplexity_cli.utils.http_errors import (
    classify_http_error,
    classify_network_error,
    handle_http_error,
    handle_network_error,
    handle_unexpected_cli_error,
    raise_http_status_error,
)
from perplexity_cli.utils.rate_limiter import RateLimiter
from perplexity_cli.utils.rate_limiter_models import RateLimiterStats
from perplexity_cli.utils.session_factory import (
    IMPERSONATE_PROFILE,
    create_async_session,
    create_sync_session,
    is_curl_cffi_available,
)
from perplexity_cli.utils.style_manager import MAX_STYLE_LENGTH, StyleManager
from perplexity_cli.utils.upstream_contracts import (
    _describe_dict_shape,
    _describe_list_shape,
    _describe_str_shape,
    _is_mapping,
    _is_sequence,
    describe_payload_shape,
    parse_thread_list_payload,
    parse_upload_url_response,
    require_list,
    require_mapping,
    schema_error,
)


class TestIsStrDict:
    def test_dict_returns_true(self) -> None:
        assert _is_str_dict({}) is True
        assert _is_str_dict({"key": "value"}) is True

    def test_non_dict_returns_false(self) -> None:
        assert _is_str_dict("string") is False
        assert _is_str_dict(42) is False
        assert _is_str_dict(None) is False
        assert _is_str_dict([1, 2]) is False


class TestConfigPaths:
    def test_token_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.token_path == tmp_path / "token.json"

    def test_style_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.style_path == tmp_path / "style.json"

    def test_urls_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.urls_path == tmp_path / "urls.json"

    def test_feature_config_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.feature_config_path == tmp_path / "config.json"

    def test_cache_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.cache_path == tmp_path / "threads-cache.json"

    def test_log_file_path(self, tmp_path: Path) -> None:
        paths = ConfigPaths(tmp_path)
        assert paths.log_file_path == tmp_path / "perplexity-cli.log"


class TestGetConfigDir:
    def test_perplexity_config_dir_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom = tmp_path / "custom-config"
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(custom))
        result = get_config_dir()
        assert result == custom
        assert custom.is_dir()

    def test_xdg_config_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        result = get_config_dir()
        assert result == xdg / "perplexity-cli"
        assert result.is_dir()

    def test_mkdir_failure_raises_configuration_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(tmp_path / "blocked"))
        with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
            with pytest.raises(ConfigurationError, match="Failed to create config directory"):
                get_config_dir()


class TestDefaultRateLimiting:
    def test_exact_defaults(self) -> None:
        result = _get_default_rate_limiting()
        assert result == {"enabled": True, "requests_per_period": 20, "period_seconds": 60}

    def test_enabled_is_true(self) -> None:
        assert _get_default_rate_limiting()["enabled"] is True

    def test_requests_per_period_is_20(self) -> None:
        assert _get_default_rate_limiting()["requests_per_period"] == 20

    def test_period_seconds_is_60(self) -> None:
        assert _get_default_rate_limiting()["period_seconds"] == 60


class TestDefaultFeatureConfig:
    def test_exact_structure(self) -> None:
        result = _get_default_feature_config()
        assert result == {
            "version": 1,
            "features": {"save_cookies": False, "debug_mode": False},
        }

    def test_version_is_1(self) -> None:
        assert _get_default_feature_config()["version"] == 1

    def test_save_cookies_default_false(self) -> None:
        assert _get_default_feature_config()["features"]["save_cookies"] is False

    def test_debug_mode_default_false(self) -> None:
        assert _get_default_feature_config()["features"]["debug_mode"] is False


class TestApplyRateLimitingEnabled:
    def test_true_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "true")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is True

    def test_1_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "1")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is True

    def test_yes_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "yes")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is True

    def test_false_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "false")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is False

    def test_0_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "0")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is False

    def test_no_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "no")
        config: dict = {}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is False

    def test_not_set_leaves_config_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PERPLEXITY_RATE_LIMITING_ENABLED", raising=False)
        config: dict = {"enabled": True}
        _apply_rate_limiting_enabled(config)
        assert config["enabled"] is True


class TestApplyRateLimitingRps:
    def test_valid_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_RPS", "42")
        config: dict = {}
        _apply_rate_limiting_rps(config)
        assert config["requests_per_period"] == 42

    def test_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_RPS", "abc")
        config: dict = {}
        with pytest.raises(ConfigurationError, match="Invalid PERPLEXITY_RATE_LIMITING_RPS: abc"):
            _apply_rate_limiting_rps(config)

    def test_not_set_leaves_config_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PERPLEXITY_RATE_LIMITING_RPS", raising=False)
        config: dict = {"requests_per_period": 20}
        _apply_rate_limiting_rps(config)
        assert config["requests_per_period"] == 20


class TestApplyRateLimitingPeriod:
    def test_valid_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_PERIOD", "90.5")
        config: dict = {}
        _apply_rate_limiting_period(config)
        assert config["period_seconds"] == pytest.approx(90.5)

    def test_integer_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_PERIOD", "120")
        config: dict = {}
        _apply_rate_limiting_period(config)
        assert config["period_seconds"] == pytest.approx(120.0)

    def test_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_PERIOD", "xyz")
        config: dict = {}
        with pytest.raises(
            ConfigurationError, match="Invalid PERPLEXITY_RATE_LIMITING_PERIOD: xyz"
        ):
            _apply_rate_limiting_period(config)


class TestMergeRateLimitingSection:
    def test_no_rate_limiting_key(self) -> None:
        config: dict = {"enabled": True}
        _merge_rate_limiting_section({}, config)
        assert config == {"enabled": True}

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="rate_limiting section must be a dictionary"):
            _merge_rate_limiting_section({"rate_limiting": "bad"}, {})

    def test_merges_values(self) -> None:
        config: dict = {"enabled": True, "requests_per_period": 20}
        _merge_rate_limiting_section({"rate_limiting": {"requests_per_period": 50}}, config)
        assert config["requests_per_period"] == 50
        assert config["enabled"] is True


class TestApplyUrlEnvOverrides:
    def test_all_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://base.example.com")
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "/query")
        monkeypatch.setenv("PERPLEXITY_THREAD_LIST_ENDPOINT", "/threads")
        monkeypatch.setenv("PERPLEXITY_UPLOAD_URL_ENDPOINT", "/upload")
        monkeypatch.setenv("PERPLEXITY_S3_BUCKET_URL", "https://s3.example.com")
        monkeypatch.setenv("PERPLEXITY_MODEL_CONFIG_ENDPOINT", "/models")
        monkeypatch.setenv("PERPLEXITY_USER_SETTINGS_ENDPOINT", "/settings")
        config: dict = {}
        _apply_url_env_overrides(config)
        assert config["base_url"] == "https://base.example.com"
        assert config["query_endpoint"] == "/query"
        assert config["thread_list_endpoint"] == "/threads"
        assert config["upload_url_endpoint"] == "/upload"
        assert config["s3_bucket_url"] == "https://s3.example.com"
        assert config["model_config_endpoint"] == "/models"
        assert config["user_settings_endpoint"] == "/settings"

    def test_no_env_vars_leaves_config_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "PERPLEXITY_BASE_URL",
            "PERPLEXITY_QUERY_ENDPOINT",
            "PERPLEXITY_THREAD_LIST_ENDPOINT",
            "PERPLEXITY_UPLOAD_URL_ENDPOINT",
            "PERPLEXITY_S3_BUCKET_URL",
            "PERPLEXITY_MODEL_CONFIG_ENDPOINT",
            "PERPLEXITY_USER_SETTINGS_ENDPOINT",
        ):
            monkeypatch.delenv(var, raising=False)
        config: dict = {"base_url": "original"}
        _apply_url_env_overrides(config)
        assert config == {"base_url": "original"}


class TestApplyFeatureEnvOverrides:
    def test_save_cookies_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "0")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["save_cookies"] is False

    def test_save_cookies_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "no")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["save_cookies"] is False

    def test_debug_mode_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "0")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["debug_mode"] is False

    def test_debug_mode_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "no")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["debug_mode"] is False

    def test_save_cookies_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "yes")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["save_cookies"] is True

    def test_debug_mode_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "1")
        feature: dict = {}
        _apply_feature_env_overrides(feature)
        assert feature["debug_mode"] is True


class TestSetFeature:
    def test_invalid_key_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Invalid feature key: bad_key"):
            set_feature("bad_key", True)

    def test_non_bool_value_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Feature value must be boolean, got str"):
            set_feature("save_cookies", "yes")

    def test_set_save_cookies_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_feature_config_cache()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(config_dir)
        )
        set_feature("save_cookies", True)
        data = json.loads((config_dir / "config.json").read_text())
        assert data["features"]["save_cookies"] is True
        assert data["version"] == 1
        clear_feature_config_cache()

    def test_set_debug_mode_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_feature_config_cache()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(config_dir)
        )
        set_feature("debug_mode", False)
        data = json.loads((config_dir / "config.json").read_text())
        assert data["features"]["debug_mode"] is False
        clear_feature_config_cache()


class TestUrlGetters:
    def test_get_perplexity_base_url(self) -> None:
        clear_urls_cache()
        url = get_perplexity_base_url()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_query_endpoint(self) -> None:
        clear_urls_cache()
        url = get_query_endpoint()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_thread_list_url(self) -> None:
        clear_urls_cache()
        url = get_thread_list_url()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_upload_url_endpoint(self) -> None:
        clear_urls_cache()
        url = get_upload_url_endpoint()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_s3_bucket_url(self) -> None:
        clear_urls_cache()
        url = get_s3_bucket_url()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_model_config_endpoint(self) -> None:
        clear_urls_cache()
        url = get_model_config_endpoint()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()

    def test_get_user_settings_endpoint(self) -> None:
        clear_urls_cache()
        url = get_user_settings_endpoint()
        assert isinstance(url, str)
        assert len(url) > 0
        clear_urls_cache()


class TestGetFeatureConfigPath:
    def test_returns_config_json(self) -> None:
        path = get_feature_config_path()
        assert path.name == "config.json"


class TestEncryptionKeyMaterial:
    def test_build_key_material_format(self) -> None:
        material = _build_key_material()
        assert isinstance(material, bytes)
        assert b":" in material

    def test_build_key_material_no_user_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        material = _build_key_material()
        assert b":unknown" in material

    def test_derive_fernet_key_returns_bytes(self) -> None:
        key = _derive_fernet_key(b"test-salt")
        assert isinstance(key, bytes)
        assert len(key) == 44

    def test_derive_fernet_key_different_salts(self) -> None:
        key1 = _derive_fernet_key(b"salt1")
        key2 = _derive_fernet_key(b"salt2")
        assert key1 != key2

    def test_derive_legacy_key_returns_bytes(self) -> None:
        key = _derive_encryption_key_legacy()
        assert isinstance(key, bytes)
        assert len(key) == 44

    def test_derive_legacy_key_oserror(self) -> None:
        with patch(
            "perplexity_cli.utils.encryption._build_key_material", side_effect=OSError("fail")
        ):
            with pytest.raises(
                ConfigurationError, match="Failed to derive encryption key \\(legacy\\)"
            ):
                _derive_encryption_key_legacy()


class TestDecryptWithCurrentFormat:
    def test_wrong_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="not in the current format"):
            _decrypt_with_current_format(b"wrong-prefix-data")

    def test_truncated_payload_raises(self) -> None:
        payload = _ENCRYPTED_TOKEN_VERSION_PREFIX + b"short"
        with pytest.raises(ValueError, match="truncated"):
            _decrypt_with_current_format(payload)

    def test_roundtrip(self) -> None:
        token = "test-token-123"
        encrypted = encrypt_token(token)
        decoded = base64.urlsafe_b64decode(encrypted.encode())
        result = _decrypt_with_current_format(decoded)
        assert result == token


class TestDecryptTokenFallback:
    def test_garbage_raises_authentication_error(self) -> None:
        with pytest.raises(AuthenticationError, match="Failed to decrypt token"):
            decrypt_token("aW52YWxpZC1kYXRh")

    def test_error_message_mentions_reauthenticate(self) -> None:
        with pytest.raises(AuthenticationError, match="perplexity-cli auth"):
            decrypt_token("aW52YWxpZC1kYXRh")


class TestStyleManagerBoundaries:
    def test_max_style_length_constant(self) -> None:
        assert MAX_STYLE_LENGTH == 10_000

    def test_validate_style_exactly_at_max(self) -> None:
        sm = StyleManager()
        assert sm.validate_style("x" * MAX_STYLE_LENGTH) is True

    def test_validate_style_one_over_max(self) -> None:
        sm = StyleManager()
        assert sm.validate_style("x" * (MAX_STYLE_LENGTH + 1)) is False

    def test_validate_style_input_exactly_at_max(self) -> None:
        sm = StyleManager()
        sm._validate_style_input("x" * MAX_STYLE_LENGTH)

    def test_validate_style_input_one_over_max(self) -> None:
        sm = StyleManager()
        with pytest.raises(ValueError, match="exceeds maximum length"):
            sm._validate_style_input("x" * (MAX_STYLE_LENGTH + 1))

    def test_validate_style_input_error_message_includes_length(self) -> None:
        sm = StyleManager()
        with pytest.raises(ValueError, match="current length: 10001"):
            sm._validate_style_input("x" * 10001)

    def test_validate_style_input_empty_string(self) -> None:
        sm = StyleManager()
        with pytest.raises(ValueError, match="non-empty string"):
            sm._validate_style_input("")

    def test_validate_style_input_whitespace_only(self) -> None:
        sm = StyleManager()
        with pytest.raises(ValueError, match="blank or whitespace"):
            sm._validate_style_input("   ")

    def test_validate_style_input_non_string(self) -> None:
        sm = StyleManager()
        with pytest.raises(ValueError, match="non-empty string"):
            sm._validate_style_input(123)  # type: ignore[arg-type]

    def test_save_style_oserror(self, tmp_path: Path) -> None:
        style_path = tmp_path / "style.json"
        mock_paths = type("MockPaths", (), {"style_path": style_path})()
        with patch("perplexity_cli.utils.style_manager.get_config_paths", return_value=mock_paths):
            sm = StyleManager()
            with patch("builtins.open", side_effect=OSError("disk full")):
                with pytest.raises(OSError, match="Failed to save style"):
                    sm.save_style("test")

    def test_clear_style_oserror(self, tmp_path: Path) -> None:
        style_path = tmp_path / "style.json"
        style_path.write_text("{}")
        mock_paths = type("MockPaths", (), {"style_path": style_path})()
        with patch("perplexity_cli.utils.style_manager.get_config_paths", return_value=mock_paths):
            sm = StyleManager()
            with patch("pathlib.Path.unlink", side_effect=OSError("locked")):
                with pytest.raises(OSError, match="Failed to delete style file"):
                    sm.clear_style()

    def test_load_style_oserror_message(self, tmp_path: Path) -> None:
        style_path = tmp_path / "style.json"
        style_path.write_text("{bad json")
        mock_paths = type("MockPaths", (), {"style_path": style_path})()
        with patch("perplexity_cli.utils.style_manager.get_config_paths", return_value=mock_paths):
            sm = StyleManager()
            with pytest.raises(OSError, match="Failed to load style"):
                sm.load_style()


class TestFileHandlerExtraction:
    def test_extract_unix_path(self) -> None:
        paths = _extract_file_paths_from_text("look at /tmp/test/file.txt please")
        assert Path("/tmp/test/file.txt") in paths

    def test_extract_tilde_path(self) -> None:
        paths = _extract_file_paths_from_text("check ~/docs/readme.md")
        assert any("readme.md" in str(p) for p in paths)

    def test_extract_no_paths(self) -> None:
        paths = _extract_file_paths_from_text("no paths here")
        assert paths == []

    def test_extract_trailing_punctuation_stripped(self) -> None:
        paths = _extract_file_paths_from_text("see /tmp/file.txt.")
        assert Path("/tmp/file.txt") in paths

    def test_extract_sorted_output(self) -> None:
        paths = _extract_file_paths_from_text("/tmp/b.txt and /tmp/a.txt")
        assert paths == sorted(paths)

    def test_extract_deduplicates(self) -> None:
        paths = _extract_file_paths_from_text("/tmp/same.txt and /tmp/same.txt")
        assert len(paths) == 1


class TestShouldSkipDirectoryEntry:
    def test_skips_git(self) -> None:
        assert _should_skip_directory_entry(Path("/project/.git")) is True

    def test_skips_node_modules(self) -> None:
        assert _should_skip_directory_entry(Path("/project/node_modules")) is True

    def test_skips_pycache(self) -> None:
        assert _should_skip_directory_entry(Path("/project/__pycache__")) is True

    def test_skips_hidden_files(self) -> None:
        assert _should_skip_directory_entry(Path("/project/.hidden")) is True

    def test_skips_env_prefix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/.env.local")) is True

    def test_skips_key_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/server.key")) is True

    def test_skips_pem_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.pem")) is True

    def test_skips_p12_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.p12")) is True

    def test_skips_pfx_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.pfx")) is True

    def test_skips_crt_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.crt")) is True

    def test_skips_cer_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.cer")) is True

    def test_skips_der_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.der")) is True

    def test_skips_jks_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/keystore.jks")) is True

    def test_skips_p8_suffix(self) -> None:
        assert _should_skip_directory_entry(Path("/project/auth.p8")) is True

    def test_includes_normal_file(self) -> None:
        assert _should_skip_directory_entry(Path("/project/main.py")) is False

    def test_includes_txt_file(self) -> None:
        assert _should_skip_directory_entry(Path("/project/readme.txt")) is False

    def test_suffix_check_is_case_insensitive(self) -> None:
        assert _should_skip_directory_entry(Path("/project/cert.KEY")) is True


class TestShouldIncludeFile:
    def test_includes_regular_file(self, tmp_path: Path) -> None:
        regular = tmp_path / "regular.txt"
        regular.write_text("content")
        assert _should_include_file(regular) is True

    def test_excludes_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        assert _should_include_file(link) is False

    def test_excludes_directory(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        assert _should_include_file(subdir) is False


class TestFileHandlerConstants:
    def test_max_attachment_count(self) -> None:
        assert MAX_ATTACHMENT_COUNT == 25

    def test_max_file_size(self) -> None:
        assert MAX_ATTACHMENT_FILE_SIZE == 10 * 1024 * 1024

    def test_max_total_size(self) -> None:
        assert MAX_TOTAL_ATTACHMENT_SIZE == 25 * 1024 * 1024

    def test_skipped_directory_names_contains_expected(self) -> None:
        assert ".git" in SKIPPED_DIRECTORY_NAMES
        assert "node_modules" in SKIPPED_DIRECTORY_NAMES
        assert "__pycache__" in SKIPPED_DIRECTORY_NAMES
        assert ".venv" in SKIPPED_DIRECTORY_NAMES
        assert "venv" in SKIPPED_DIRECTORY_NAMES

    def test_skipped_filename_prefixes(self) -> None:
        assert SKIPPED_FILENAME_PREFIXES == (".env",)

    def test_skipped_filename_suffixes(self) -> None:
        assert ".key" in SKIPPED_FILENAME_SUFFIXES
        assert ".pem" in SKIPPED_FILENAME_SUFFIXES


class TestLoadAttachmentsTooMany:
    def test_too_many_raises(self, tmp_path: Path) -> None:
        paths = [tmp_path / f"file{i}.txt" for i in range(MAX_ATTACHMENT_COUNT + 1)]
        with pytest.raises(AttachmentError, match="Too many attachments"):
            load_attachments(paths)

    def test_exactly_at_limit_does_not_raise_count_error(self, tmp_path: Path) -> None:
        for i in range(MAX_ATTACHMENT_COUNT):
            (tmp_path / f"file{i}.txt").write_text("x")
        paths = [tmp_path / f"file{i}.txt" for i in range(MAX_ATTACHMENT_COUNT)]
        result = load_attachments(paths)
        assert len(result) == MAX_ATTACHMENT_COUNT


class TestFileAttachmentModel:
    def test_empty_filename_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            FileAttachment(
                filename="", content_type="text/plain", data=base64.b64encode(b"x").decode()
            )

    def test_filename_256_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="<=255"):
            FileAttachment(
                filename="a" * 256, content_type="text/plain", data=base64.b64encode(b"x").decode()
            )

    def test_filename_255_chars_ok(self) -> None:
        attachment = FileAttachment(
            filename="a" * 255, content_type="text/plain", data=base64.b64encode(b"x").decode()
        )
        assert len(attachment.filename) == 255

    def test_empty_content_type_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            FileAttachment(filename="f.txt", content_type="", data=base64.b64encode(b"x").decode())

    def test_invalid_base64_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid base64"):
            FileAttachment(filename="f.txt", content_type="text/plain", data="!!!invalid!!!")

    def test_from_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            FileAttachment.from_file(Path("/nonexistent/file.txt"))

    def test_from_file_not_a_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Not a file"):
            FileAttachment.from_file(tmp_path)

    def test_from_file_csv_type(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b,c")
        attachment = FileAttachment.from_file(csv_file)
        assert attachment.content_type == "text/csv"

    def test_from_file_html_type(self, tmp_path: Path) -> None:
        html_file = tmp_path / "page.html"
        html_file.write_text("<html></html>")
        attachment = FileAttachment.from_file(html_file)
        assert attachment.content_type == "text/html"

    def test_from_file_pdf_type(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "doc.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")
        attachment = FileAttachment.from_file(pdf_file)
        assert attachment.content_type == "application/pdf"

    def test_from_file_xml_type(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "data.xml"
        xml_file.write_text("<root/>")
        attachment = FileAttachment.from_file(xml_file)
        assert attachment.content_type == "text/xml"

    def test_from_file_toml_type(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[section]")
        attachment = FileAttachment.from_file(toml_file)
        assert attachment.content_type == "text/plain"

    def test_from_file_ts_type(self, tmp_path: Path) -> None:
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("const x = 1;")
        attachment = FileAttachment.from_file(ts_file)
        assert attachment.content_type == "text/plain"

    def test_from_file_tsx_type(self, tmp_path: Path) -> None:
        tsx_file = tmp_path / "app.tsx"
        tsx_file.write_text("export default () => <div/>;")
        attachment = FileAttachment.from_file(tsx_file)
        assert attachment.content_type == "text/plain"

    def test_from_file_jsx_type(self, tmp_path: Path) -> None:
        jsx_file = tmp_path / "app.jsx"
        jsx_file.write_text("export default () => <div/>;")
        attachment = FileAttachment.from_file(jsx_file)
        assert attachment.content_type == "text/plain"

    def test_from_file_doc_type(self, tmp_path: Path) -> None:
        doc_file = tmp_path / "file.doc"
        doc_file.write_bytes(b"\x00")
        attachment = FileAttachment.from_file(doc_file)
        assert attachment.content_type == "application/msword"

    def test_from_file_docx_type(self, tmp_path: Path) -> None:
        docx_file = tmp_path / "file.docx"
        docx_file.write_bytes(b"\x00")
        attachment = FileAttachment.from_file(docx_file)
        assert attachment.content_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_from_file_rtf_type(self, tmp_path: Path) -> None:
        rtf_file = tmp_path / "file.rtf"
        rtf_file.write_text("{\\rtf1}")
        attachment = FileAttachment.from_file(rtf_file)
        assert attachment.content_type == "application/rtf"

    def test_from_file_unknown_extension(self, tmp_path: Path) -> None:
        unknown_file = tmp_path / "data.zzz"
        unknown_file.write_bytes(b"\x00")
        attachment = FileAttachment.from_file(unknown_file)
        assert attachment.content_type == "application/octet-stream"


class TestUpstreamContracts:
    def test_is_mapping_dict(self) -> None:
        assert _is_mapping({}) is True
        assert _is_mapping({"a": 1}) is True

    def test_is_mapping_non_dict(self) -> None:
        assert _is_mapping([]) is False
        assert _is_mapping("str") is False
        assert _is_mapping(None) is False

    def test_is_sequence_list(self) -> None:
        assert _is_sequence([]) is True
        assert _is_sequence([1, 2]) is True

    def test_is_sequence_non_list(self) -> None:
        assert _is_sequence({}) is False
        assert _is_sequence("str") is False
        assert _is_sequence(None) is False

    def test_describe_dict_shape_non_dict(self) -> None:
        assert _describe_dict_shape(42) == "int"
        assert _describe_dict_shape("str") == "str"

    def test_describe_dict_shape_with_keys(self) -> None:
        result = _describe_dict_shape({"b": 1, "a": 2})
        assert result == "object(keys=[a, b])"

    def test_describe_dict_shape_truncates_keys(self) -> None:
        result = _describe_dict_shape({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6})
        assert result == "object(keys=[a, b, c, d, e])"

    def test_describe_list_shape_non_list(self) -> None:
        assert _describe_list_shape(42) == "int"

    def test_describe_list_shape_with_items(self) -> None:
        assert _describe_list_shape([1, 2, 3]) == "array(len=3)"

    def test_describe_list_shape_empty(self) -> None:
        assert _describe_list_shape([]) == "array(len=0)"

    def test_describe_str_shape_non_str(self) -> None:
        assert _describe_str_shape(42) == "int"

    def test_describe_str_shape_with_value(self) -> None:
        assert _describe_str_shape("hello") == "string(len=5)"

    def test_describe_str_shape_empty(self) -> None:
        assert _describe_str_shape("") == "string(len=0)"

    def test_describe_payload_shape_none(self) -> None:
        assert describe_payload_shape(None) == "null"

    def test_describe_payload_shape_int(self) -> None:
        assert describe_payload_shape(42) == "int"

    def test_describe_payload_shape_float(self) -> None:
        assert describe_payload_shape(3.14) == "float"

    def test_describe_payload_shape_bool(self) -> None:
        assert describe_payload_shape(True) == "bool"

    def test_describe_payload_shape_dict(self) -> None:
        assert describe_payload_shape({"key": "val"}) == "object(keys=[key])"

    def test_describe_payload_shape_list(self) -> None:
        assert describe_payload_shape([1, 2]) == "array(len=2)"

    def test_describe_payload_shape_str(self) -> None:
        assert describe_payload_shape("test") == "string(len=4)"

    def test_schema_error_without_detail(self) -> None:
        err = schema_error("ctx", "object", 42)
        assert str(err) == "ctx: expected object, got int"

    def test_schema_error_with_detail(self) -> None:
        err = schema_error("ctx", "object", 42, detail="extra info")
        assert str(err) == "ctx: expected object, got int (extra info)"

    def test_require_mapping_valid(self) -> None:
        result = require_mapping({"a": 1}, "ctx")
        assert result == {"a": 1}

    def test_require_mapping_invalid(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="expected object, got int"):
            require_mapping(42, "ctx")

    def test_require_list_valid(self) -> None:
        result = require_list([1, 2], "ctx")
        assert result == [1, 2]

    def test_require_list_invalid(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="expected array, got str"):
            require_list("not a list", "ctx")

    def test_parse_upload_url_response_valid(self) -> None:
        payload = {"results": {"uuid1": {"url": "https://example.com"}}}
        result = parse_upload_url_response(payload)
        assert result == payload

    def test_parse_upload_url_response_not_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            parse_upload_url_response("not a dict")

    def test_parse_upload_url_response_missing_results(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing or invalid 'results' field"):
            parse_upload_url_response({"other": "data"})

    def test_parse_upload_url_response_results_not_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            parse_upload_url_response({"results": "bad"})

    def test_parse_upload_url_response_entry_not_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="file_uuid="):
            parse_upload_url_response({"results": {"uuid1": "bad"}})

    def test_parse_thread_list_payload_valid(self) -> None:
        payload = [{"id": 1}, {"id": 2}]
        result = parse_thread_list_payload(payload)
        assert result == [{"id": 1}, {"id": 2}]

    def test_parse_thread_list_payload_not_list(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            parse_thread_list_payload("not a list")

    def test_parse_thread_list_payload_entry_not_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            parse_thread_list_payload(["not a dict"])

    def test_parse_thread_list_payload_empty(self) -> None:
        assert parse_thread_list_payload([]) == []


class TestHTTPErrors:
    def _make_http_error(self, status: int) -> PerplexityHTTPStatusError:
        request = SimpleRequest(method="POST", url="https://example.com")
        response = SimpleResponse(status_code=status, headers={}, text="error", request=request)
        return PerplexityHTTPStatusError(f"HTTP Error {status}", request=request, response=response)

    def test_classify_401(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(401))
        assert code == "authentication_required"
        assert "Authentication failed" in msg
        assert fix == "Run `pxcli auth login` to re-authenticate."

    def test_classify_403(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(403))
        assert code == "permission_denied"
        assert "forbidden" in msg.lower()
        assert fix is None

    def test_classify_429(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(429))
        assert code == "rate_limited"
        assert "Rate limit" in msg
        assert fix == "Wait a moment and retry."

    def test_classify_500(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(500))
        assert code == "network_error"
        assert "Server error (HTTP 500)" in msg
        assert fix == "Try again later."

    def test_classify_502(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(502))
        assert code == "network_error"
        assert "HTTP 502" in msg

    def test_classify_404(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(404))
        assert code == "network_error"
        assert "HTTP error 404" in msg
        assert fix is None

    def test_classify_418(self) -> None:
        code, msg, fix = classify_http_error(self._make_http_error(418))
        assert code == "network_error"
        assert "HTTP error 418" in msg
        assert fix is None

    def test_classify_network_error(self) -> None:
        err = PerplexityRequestError("connection failed")
        code, msg, fix = classify_network_error(err)
        assert code == "network_error"
        assert "Network error" in msg
        assert fix == "Check your internet connection."

    def test_handle_http_error_401(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-401")
        err = self._make_http_error(401)
        with pytest.raises(SystemExit) as exc_info:
            handle_http_error(err, logger)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Authentication failed" in captured.err
        assert "perplexity-cli auth" in captured.err

    def test_handle_http_error_403(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-403")
        err = self._make_http_error(403)
        with pytest.raises(SystemExit) as exc_info:
            handle_http_error(err, logger)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Access forbidden" in captured.err

    def test_handle_http_error_429(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-429")
        err = self._make_http_error(429)
        with pytest.raises(SystemExit) as exc_info:
            handle_http_error(err, logger)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Rate limit exceeded" in captured.err

    def test_handle_http_error_generic(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-generic")
        err = self._make_http_error(500)
        with pytest.raises(SystemExit) as exc_info:
            handle_http_error(err, logger)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "HTTP error 500" in captured.err

    def test_handle_http_error_debug_mode(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-debug")
        err = self._make_http_error(401)
        with pytest.raises(SystemExit):
            handle_http_error(err, logger, debug_mode="debug")
        captured = capsys.readouterr()
        assert "Details:" in captured.err

    def test_handle_http_error_with_context(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-http-context")
        err = self._make_http_error(401)
        with pytest.raises(SystemExit):
            handle_http_error(err, logger, context="during streaming")
        captured = capsys.readouterr()
        assert "Authentication failed" in captured.err

    def test_handle_network_error(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-net")
        err = PerplexityRequestError("timeout")
        with pytest.raises(SystemExit) as exc_info:
            handle_network_error(err, logger)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Network error" in captured.err

    def test_handle_network_error_debug(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-net-debug")
        err = PerplexityRequestError("timeout")
        with pytest.raises(SystemExit):
            handle_network_error(err, logger, debug_mode="debug")
        captured = capsys.readouterr()
        assert "Details:" in captured.err

    def test_handle_network_error_with_context(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-net-ctx")
        err = PerplexityRequestError("timeout")
        with pytest.raises(SystemExit):
            handle_network_error(err, logger, context="during upload")
        captured = capsys.readouterr()
        assert "Network error" in captured.err

    def test_handle_unexpected_debug_no_hint(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-unexpected")
        with pytest.raises(SystemExit) as exc_info:
            try:
                raise RuntimeError("boom")
            except RuntimeError as e:
                handle_unexpected_cli_error(
                    e, logger, debug_mode="debug", message_tuple=("[ERR]", "log msg", False)
                )
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Debug info:" not in captured.err
        assert "RuntimeError: boom" in captured.err

    def test_handle_unexpected_normal_no_hint(self, capsys: pytest.CaptureFixture) -> None:
        import logging

        logger = logging.getLogger("test-unexpected2")
        with pytest.raises(SystemExit) as exc_info:
            try:
                raise RuntimeError("boom")
            except RuntimeError as e:
                handle_unexpected_cli_error(
                    e, logger, debug_mode="normal", message_tuple=("[ERR]", "log msg", False)
                )
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERR]" in captured.err
        assert "Run with --debug" not in captured.err

    def test_raise_http_status_error(self) -> None:
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 500
        mock_response.content = b"Internal Server Error"
        mock_response.headers = {"Content-Type": "text/plain"}
        with pytest.raises(PerplexityHTTPStatusError, match="HTTP Error 500"):
            raise_http_status_error(mock_response)

    def test_raise_http_status_error_non_bytes_body(self) -> None:
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 400
        mock_response.content = "string body"
        mock_response.headers = {}
        with pytest.raises(PerplexityHTTPStatusError, match="HTTP Error 400"):
            raise_http_status_error(mock_response)

    def test_raise_http_status_error_no_content(self) -> None:
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 502
        mock_response.content = None
        mock_response.headers = None
        with pytest.raises(PerplexityHTTPStatusError, match="HTTP Error 502"):
            raise_http_status_error(mock_response)

    def test_raise_http_status_error_custom_method(self) -> None:
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 404
        mock_response.content = b"not found"
        mock_response.headers = {}
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            raise_http_status_error(mock_response, method="GET")
        assert exc_info.value.request.method == "GET"


class TestRateLimiterStats:
    def test_from_data_zero_requests(self) -> None:
        stats = RateLimiterStats.from_data(total_requests=0, total_wait_time=0.0)
        assert stats.average_wait_time == pytest.approx(0.0)
        assert stats.total_requests == 0

    def test_from_data_with_requests(self) -> None:
        stats = RateLimiterStats.from_data(total_requests=4, total_wait_time=2.0)
        assert stats.average_wait_time == pytest.approx(0.5)

    def test_from_data_single_request(self) -> None:
        stats = RateLimiterStats.from_data(total_requests=1, total_wait_time=3.0)
        assert stats.average_wait_time == pytest.approx(3.0)


class TestRateLimiterRepr:
    def test_repr_exact(self) -> None:
        limiter = RateLimiter(requests_per_period=10, period_seconds=30.0)
        assert repr(limiter) == "RateLimiter(requests_per_period=10, period_seconds=30.0)"


class TestSessionFactory:
    def test_is_available(self) -> None:
        assert is_curl_cffi_available() is True

    def test_impersonate_profile(self) -> None:
        assert IMPERSONATE_PROFILE == "chrome"

    def test_sync_session_default_timeout(self) -> None:
        session = create_sync_session()
        assert session is not None

    def test_async_session_default_timeout(self) -> None:
        session = create_async_session()
        assert session is not None

    def test_sync_session_custom_timeout(self) -> None:
        session = create_sync_session(timeout=5)
        assert session is not None

    def test_async_session_custom_timeout(self) -> None:
        session = create_async_session(timeout=5)
        assert session is not None


class TestSimpleRequestResponse:
    def test_simple_request_defaults(self) -> None:
        req = SimpleRequest()
        assert req.method == ""
        assert req.url == ""

    def test_simple_request_custom(self) -> None:
        req = SimpleRequest(method="GET", url="https://example.com")
        assert req.method == "GET"
        assert req.url == "https://example.com"

    def test_simple_response_defaults(self) -> None:
        resp = SimpleResponse()
        assert resp.status_code == 0
        assert resp.headers == {}
        assert resp.text == ""
        assert isinstance(resp.request, SimpleRequest)

    def test_simple_response_custom(self) -> None:
        req = SimpleRequest(method="POST", url="https://api.example.com")
        resp = SimpleResponse(status_code=200, headers={"X-Test": "1"}, text="ok", request=req)
        assert resp.status_code == 200
        assert resp.headers == {"X-Test": "1"}
        assert resp.text == "ok"
        assert resp.request.method == "POST"

    def test_http_status_error_defaults(self) -> None:
        err = PerplexityHTTPStatusError("error")
        assert str(err) == "error"
        assert isinstance(err.request, SimpleRequest)
        assert isinstance(err.response, SimpleResponse)

    def test_http_status_error_custom(self) -> None:
        req = SimpleRequest(method="GET", url="https://x.com")
        resp = SimpleResponse(status_code=500)
        err = PerplexityHTTPStatusError("err", request=req, response=resp)
        assert err.request.method == "GET"
        assert err.response.status_code == 500
