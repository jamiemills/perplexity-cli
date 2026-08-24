"""Mutation-closure behavioural tests for the config implementation (T007).

Each test exercises the public ``perplexity_cli.utils.config`` facade and
targets survivors reported for ``perplexity_cli.utils.config.impl``.
"""

from __future__ import annotations

import builtins
import io
import json
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from perplexity_cli.config.models import FeatureConfig
from perplexity_cli.utils.config import (
    ConfigPaths,
    default_feature_config,
    default_rate_limiting,
    get_config_dir,
    get_config_paths,
    get_feature_config,
    get_feature_config_path,
    get_rate_limiting_config,
    get_urls,
    set_feature,
)
from perplexity_cli.utils.exceptions import ConfigurationError

_IMPL_LOGGER_NAME = "perplexity_cli.utils.config.impl"
_FEATURES_SECTION_ERROR = "^Feature configuration 'features' section must be a dictionary$"
_RATE_LIMITING_SECTION_ERROR = "^rate_limiting section must be a dictionary$"


def _run_with_deadline[ResultT](
    call: Callable[[], ResultT], deadline_seconds: float = 2.0
) -> ResultT:
    """Run ``call`` under a SIGALRM watchdog so a stalled mutant fails fast."""

    def _on_deadline(signum: int, frame: object) -> None:
        raise AssertionError(f"call exceeded {deadline_seconds}s (non-terminating)")

    previous = signal.signal(signal.SIGALRM, _on_deadline)
    signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _missing_packaged_urls(package: str) -> Path:
    """Stand-in for ``importlib.resources.files`` that always fails."""
    raise FileNotFoundError("packaged urls missing")


class TestGetConfigDirResolution:
    """Directory resolution branches of the public config-dir getter."""

    def test_windows_default_without_appdata_uses_home_roaming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows resolution without APPDATA falls back to the home Roaming tree.

        Historically timeout-prone mutants cluster here, so the call runs
        under a termination watchdog; every divergence fails fast instead.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.os",
            SimpleNamespace(name="nt", getenv=os.getenv),
        )
        monkeypatch.setattr("perplexity_cli.utils.config.impl.Path.home", lambda: tmp_path)
        expected = tmp_path / "AppData" / "Roaming" / "perplexity-cli"
        assert _run_with_deadline(get_config_dir) == expected

    def test_unwritable_config_dir_error_names_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A directory creation failure reports the offending path."""
        blocker = tmp_path / "blocker"
        blocker.write_text("file occupying the directory name", encoding="utf-8")
        configured = blocker / "sub"
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(configured))

        with pytest.raises(ConfigurationError) as excinfo:
            get_config_dir()

        assert str(configured) in str(excinfo.value)


class TestUrlsConfigFiles:
    """Bootstrap and failure behaviour of the urls.json user file."""

    def test_urls_bootstrap_writes_two_space_indented_defaults(self) -> None:
        """A freshly created urls.json is pretty-printed with two-space indent."""
        urls_path = get_config_paths().urls_path
        assert not urls_path.exists()

        get_urls()

        text = urls_path.read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), indent=2)

    def test_missing_packaged_defaults_error_names_cause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When packaged defaults cannot be read the error names the cause."""
        fake_resources = SimpleNamespace(files=_missing_packaged_urls)
        monkeypatch.setattr("perplexity_cli.utils.config.impl.resources", fake_resources)

        with pytest.raises(ConfigurationError) as excinfo:
            get_urls()

        assert "packaged urls missing" in str(excinfo.value)

    def test_urls_write_failure_error_names_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A urls.json creation failure reports the underlying file path."""
        blocker = tmp_path / "blocker"
        blocker.write_text("file occupying the directory name", encoding="utf-8")
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(blocker)
        )

        with pytest.raises(ConfigurationError) as excinfo:
            get_urls()

        assert "urls.json" in str(excinfo.value)

    def test_url_defaults_and_user_file_use_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The public URL loader uses read mode and UTF-8 for both files."""
        opened: list[tuple[str, object]] = []
        packaged_open_args: list[tuple[object, ...]] = []
        real_open = builtins.open

        def recording_open(file: object, *args: object, **kwargs: object):
            opened.append((str(file), kwargs.get("encoding")))
            return real_open(file, *args, **kwargs)

        class PackagedUrls:
            def joinpath(self, name: str) -> PackagedUrls:
                assert name == "urls.json"
                return self

            def open(self, *args: object, **kwargs: object):
                packaged_open_args.append(args)
                opened.append(("packaged urls.json", kwargs.get("encoding")))
                return io.StringIO('{"perplexity": {}}')

        monkeypatch.setattr(builtins, "open", recording_open)
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.resources",
            SimpleNamespace(files=lambda package: PackagedUrls()),
        )

        assert _run_with_deadline(get_urls).base_url == "https://www.perplexity.ai"
        assert packaged_open_args == [("r",)]
        assert all(encoding == "utf-8" for _, encoding in opened)


class TestFeatureConfigFiles:
    """Bootstrap, fallback, and formatting behaviour of config.json."""

    def test_feature_bootstrap_creates_missing_parents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Feature bootstrap creates the whole missing directory chain."""
        config_dir = tmp_path / "deep" / "nest"
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(config_dir)
        )

        config = get_feature_config()

        assert isinstance(config, FeatureConfig)
        assert (config_dir / "config.json").exists()

    def test_feature_bootstrap_matches_public_defaults_and_format(self) -> None:
        """A freshly created config.json equals the public defaults, indented."""
        config_path = get_feature_config_path()

        get_feature_config()

        text = config_path.read_text(encoding="utf-8")
        assert json.loads(text) == default_feature_config()
        assert text == json.dumps(json.loads(text), indent=2)

    def test_corrupt_feature_file_falls_back_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A corrupt config.json yields defaults and one structured warning."""
        corrupt = "{definitely not json"
        config_path = get_feature_config_path()
        config_path.write_text(corrupt, encoding="utf-8")
        with pytest.raises(json.JSONDecodeError) as expected:
            json.loads(corrupt)

        with caplog.at_level(logging.WARNING, logger="perplexity_cli"):
            config = get_feature_config()

        assert config.save_cookies is False
        assert config.debug_mode is False
        warnings_seen = [record for record in caplog.records if record.name == "perplexity_cli"]
        assert len(warnings_seen) == 1
        expected_message = f"Failed to load feature config, using defaults: {expected.value}"
        assert warnings_seen[0].getMessage() == expected_message

    def test_non_dict_features_error_is_anchored(self) -> None:
        """A non-dict features section rejects with the exact contract message."""
        config_path = get_feature_config_path()
        config_path.write_text(json.dumps({"features": "bad"}), encoding="utf-8")

        with pytest.raises(ConfigurationError, match=_FEATURES_SECTION_ERROR):
            get_feature_config()

    def test_set_feature_persists_only_known_feature_keys(self) -> None:
        """Persisting one feature writes exactly the two documented keys."""
        set_feature("save_cookies", True)

        written = json.loads(get_feature_config_path().read_text(encoding="utf-8"))
        assert set(written["features"]) == {"save_cookies", "debug_mode"}
        assert written["features"]["save_cookies"] is True

    def test_feature_bootstrap_uses_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The public feature loader creates and reads config.json as UTF-8."""
        encodings: list[object] = []
        real_open = builtins.open

        def recording_open(file: object, *args: object, **kwargs: object):
            encodings.append(kwargs.get("encoding"))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", recording_open)
        assert get_feature_config().debug_mode is False
        assert encodings and all(encoding == "utf-8" for encoding in encodings)


class TestSetFeatureValidation:
    """Input validation and persistence envelope of set_feature."""

    def test_set_feature_rejects_unknown_key(self) -> None:
        """An unknown key is rejected with the key and the valid key list."""
        with pytest.raises(ConfigurationError) as excinfo:
            set_feature("bogus", True)

        message = str(excinfo.value)
        assert "Invalid feature key: bogus" in message
        assert "save_cookies, debug_mode" in message

    def test_set_feature_rejects_non_boolean_value(self) -> None:
        """A non-boolean value is rejected naming the offending type."""
        with pytest.raises(ConfigurationError) as excinfo:
            set_feature("save_cookies", "yes")

        assert f"got {str.__name__}" in str(excinfo.value)

    def test_set_feature_writes_version_one_envelope(self) -> None:
        """The persisted document is versioned with the value applied."""
        set_feature("debug_mode", False)

        written = json.loads(get_feature_config_path().read_text(encoding="utf-8"))
        assert written["version"] == 1
        assert written["features"]["debug_mode"] is False

    def test_set_feature_writes_two_space_indent(self) -> None:
        """The persisted document is pretty-printed with two-space indent."""
        set_feature("save_cookies", True)

        text = get_feature_config_path().read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), indent=2)

    def test_set_feature_writes_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The public feature setter writes config.json as UTF-8."""
        encodings: list[object] = []
        real_open = builtins.open

        def recording_open(file: object, *args: object, **kwargs: object):
            encodings.append(kwargs.get("encoding"))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", recording_open)
        set_feature("save_cookies", True)
        assert encodings == ["utf-8", "utf-8"]


class TestRateLimitingFiles:
    """File-loading and environment behaviour of rate-limiting configuration."""

    def test_non_dict_rate_limiting_error_is_anchored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-dict rate_limiting section rejects with the exact message."""
        urls_path = tmp_path / "urls.json"
        urls_path.write_text(json.dumps({"rate_limiting": ["bad"]}), encoding="utf-8")
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(tmp_path)
        )

        with pytest.raises(ConfigurationError, match=_RATE_LIMITING_SECTION_ERROR):
            get_rate_limiting_config()

    def test_unparseable_urls_file_logs_debug_and_uses_defaults(
        self, caplog: pytest.LogCaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unparseable urls.json falls back to defaults with one debug line."""
        urls_path = tmp_path / "urls.json"
        urls_path.write_text("{nope", encoding="utf-8")
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(tmp_path)
        )

        with caplog.at_level(logging.DEBUG, logger=_IMPL_LOGGER_NAME):
            config = get_rate_limiting_config()

        expected_defaults = default_rate_limiting()
        assert config.enabled is expected_defaults["enabled"]
        assert config.requests_per_period == expected_defaults["requests_per_period"]
        debug_records = [
            record
            for record in caplog.records
            if record.name == _IMPL_LOGGER_NAME and record.levelno == logging.DEBUG
        ]
        assert len(debug_records) == 1
        assert debug_records[0].getMessage() == "Could not load or parse urls configuration file"

    def test_rate_limiting_file_uses_utf8(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The public rate-limit loader reads urls.json as UTF-8."""
        urls_path = tmp_path / "urls.json"
        urls_path.write_text(json.dumps({"rate_limiting": {"enabled": False}}), encoding="utf-8")
        monkeypatch.setattr(
            "perplexity_cli.utils.config.impl.get_config_paths", lambda: ConfigPaths(tmp_path)
        )
        encodings: list[object] = []
        real_open = builtins.open

        def recording_open(file: object, *args: object, **kwargs: object):
            encodings.append(kwargs.get("encoding"))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", recording_open)
        assert get_rate_limiting_config().enabled is False
        assert encodings == ["utf-8"]


class TestEnvironmentOverrideParsing:
    """Truthiness parsing of feature and rate-limiting environment overrides."""

    def test_rate_limiting_enabled_env_accepts_numeric_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PERPLEXITY_RATE_LIMITING_ENABLED=1 enables rate limiting."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "1")
        assert get_rate_limiting_config().enabled is True

    def test_feature_env_yes_and_numeric_one_enable_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save_cookies accepts "yes" and debug_mode accepts "1"."""
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "yes")
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "1")

        config = get_feature_config()

        assert config.save_cookies is True
        assert config.debug_mode is True
