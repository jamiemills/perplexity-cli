"""Mutation-killer tests for the auth export and import runners.

Exact call-argument, message and envelope assertions so mutations of the
credential-portability seam cannot survive.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from perplexity_cli._types import OutputFormat
from perplexity_cli.runners import auth as auth_runner
from perplexity_cli.runners.auth import (
    _build_export_bundle,
    _cookies_will_be_stored,
    _default_export_path,
    _emit_export_result,
    _emit_import_result,
    _handle_export_missing_token,
    _is_str_str_dict,
    _load_import_bundle,
    _read_bundle_file,
    _require_bundle_token,
    _require_bundle_version,
    _save_imported_credentials,
    _validate_import_cookies,
    run_export_command,
    run_import_command,
)
from perplexity_cli.utils.exceptions import AuthenticationError


def _options(fmt: OutputFormat = "human") -> object:
    return auth_runner._AuthOutputOptions(
        output_format=fmt, schema_inclusion="no_schema", debug_level="standard"
    )


class TestRequireBundleVersion:
    """Version enforcement must reject anything but the exact integer."""

    def test_accepts_exact_version(self):
        _require_bundle_version({"version": 1})

    @pytest.mark.parametrize("bad", [{"version": 2}, {"version": "1"}, {}, {"version": None}])
    def test_rejects_any_other_version(self, bad):
        with pytest.raises(ValueError, match=r"Unsupported bundle version"):
            _require_bundle_version(bad)

    def test_error_message_is_exact(self):
        with pytest.raises(ValueError) as exc:
            _require_bundle_version({"version": 2})
        assert str(exc.value) == "Unsupported bundle version 2; expected 1."

    def test_error_message_is_exact_from_exception_path(self):
        with pytest.raises(ValueError) as exc:
            _require_bundle_version({"version": 2})
        assert str(exc.value) == "Unsupported bundle version 2; expected 1."


class TestRequireBundleToken:
    """Token enforcement must require a non-empty string."""

    @pytest.mark.parametrize("bad", [None, 5, "", [], {"t": 1}])
    def test_rejects_bad_tokens(self, bad):
        with pytest.raises(ValueError, match=r"Bundle \'token\' must be a non-empty string\."):
            _require_bundle_token({"token": bad})

    def test_accepts_non_empty_string(self):
        assert _require_bundle_token({"token": "tok"}) == "tok"


class TestIsStrStrDict:
    """The cookie shape guard must classify exactly."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ({}, True),
            ({"a": "b"}, True),
            ({"a": 1}, False),
            ({1: "b"}, False),
            (None, False),
            ("text", False),
            ([("a", "b")], False),
        ],
    )
    def test_classification(self, value, expected):
        assert _is_str_str_dict(value) is expected


class TestValidateImportCookies:
    """Cookie validation must convert, reject, or return None exactly."""

    def test_none_returns_none(self):
        assert _validate_import_cookies(None) is None

    def test_empty_dict_returns_none(self):
        assert _validate_import_cookies({}) is None

    def test_valid_mapping_is_copied(self):
        assert _validate_import_cookies({"cf_clearance": "c"}) == {"cf_clearance": "c"}

    def test_malformed_mapping_raises_exact_message(self):
        with pytest.raises(ValueError) as exc:
            _validate_import_cookies({"cf_clearance": 5})
        assert str(exc.value) == "Bundle 'cookies' must be an object of name-to-string values."

    def test_token_error_message_is_exactly_equal(self):
        with pytest.raises(ValueError) as exc:
            _require_bundle_token({"token": ""})
        assert str(exc.value) == "Bundle 'token' must be a non-empty string."

    def test_non_object_error_message_is_exactly_equal(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("[1]", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            _read_bundle_file(path)
        assert str(exc.value) == "Import bundle must be a JSON object."


class TestReadBundleFile:
    """Bundle reads must map every failure mode to ValueError."""

    def test_reads_json_object(self, tmp_path):
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps({"version": 1, "token": "t"}), encoding="utf-8")
        assert _read_bundle_file(path) == {"version": 1, "token": "t"}

    def test_missing_file_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError, match=r"Cannot read import file\:"):
            _read_bundle_file(tmp_path / "absent.json")

    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "bundle.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match=r"Import file is not valid JSON\:"):
            _read_bundle_file(path)

    def test_non_object_json_raises_value_error(self, tmp_path):
        path = tmp_path / "bundle.json"
        path.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(ValueError, match=r"Import bundle must be a JSON object\."):
            _read_bundle_file(path)


class TestLoadImportBundle:
    """Validation failures must route through the taxonomy error handler."""

    def _run(self, path: Path):
        with patch.object(auth_runner, "handle_error", Mock(side_effect=SystemExit(7))) as handler:
            with pytest.raises(SystemExit):
                _load_import_bundle(path, _options())
        return handler

    def test_valid_bundle_returns_token_and_cookies(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(
            json.dumps({"version": 1, "token": "tok", "cookies": {"a": "b"}}), encoding="utf-8"
        )
        assert _load_import_bundle(path, _options()) == ("tok", {"a": "b"})

    def test_invalid_bundle_calls_handle_error_with_command(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"version": 9}), encoding="utf-8")
        handler = self._run(path)
        assert handler.call_args.args[1] == "pxcli auth import"


class TestCookiesWillBeStored:
    """The storage predicate must consider both inputs."""

    def test_none_cookies_never_stored(self):
        with patch.object(auth_runner, "get_save_cookies_enabled", return_value=True):
            assert _cookies_will_be_stored(None) is False

    def test_cookies_with_flag_stored(self):
        with patch.object(auth_runner, "get_save_cookies_enabled", return_value=True):
            assert _cookies_will_be_stored({"a": "b"}) is True

    def test_cookies_without_flag_not_stored(self):
        with patch.object(auth_runner, "get_save_cookies_enabled", return_value=False):
            assert _cookies_will_be_stored({"a": "b"}) is False


class TestSaveImportedCredentials:
    """The save seam must warn first, then save with exact arguments."""

    def _run(self, token: str, cookies: dict[str, str] | None, flag_enabled: bool):
        manager = Mock(name="token-manager")
        with (
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "get_save_cookies_enabled", return_value=flag_enabled),
            patch.object(auth_runner, "click") as click_mock,
        ):
            _save_imported_credentials(token, cookies, _options())
        return manager, click_mock

    def test_saves_token_and_cookies_when_enabled(self):
        manager, click_mock = self._run("tok", {"a": "b"}, True)
        manager.save_token.assert_called_once_with("tok", {"a": "b"})
        click_mock.echo.assert_not_called()

    def test_saves_token_only_when_cookies_absent(self):
        manager, _click = self._run("tok", None, False)
        manager.save_token.assert_called_once_with("tok", None)

    def test_warns_before_save_when_flag_disabled(self):
        manager, click_mock = self._run("tok", {"a": "b"}, False)
        assert click_mock.echo.call_count == 1
        assert click_mock.echo.call_args == call(auth_runner._IMPORT_COOKIES_WARNING, err=True)
        # The manager (not the runner) enforces the storage gate, so cookies
        # are still forwarded and dropped inside save_token.
        manager.save_token.assert_called_once_with("tok", {"a": "b"})

    def test_save_failure_routes_to_handle_error(self):
        manager = Mock(name="token-manager")
        manager.save_token.side_effect = OSError("no space")
        with (
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "get_save_cookies_enabled", return_value=True),
            patch.object(auth_runner, "handle_error", Mock(side_effect=SystemExit(1))) as handler,
        ):
            with pytest.raises(SystemExit):
                _save_imported_credentials("tok", None, _options())
        assert handler.call_args.args[0] is manager.save_token.side_effect
        assert handler.call_args.args[1] == "pxcli auth import"
        assert handler.call_args.kwargs == {
            "output_format": "human",
            "include_schema": "no_schema",
        }

    def test_load_failure_routes_exact_arguments(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("{bad", encoding="utf-8")
        with patch.object(auth_runner, "handle_error", Mock(side_effect=SystemExit(7))) as handler:
            with pytest.raises(SystemExit):
                _load_import_bundle(path, _options())
        raised = handler.call_args.args[0]
        assert isinstance(raised, ValueError)
        assert str(raised).startswith("Import file is not valid JSON:")
        assert handler.call_args.args[1] == "pxcli auth import"
        assert handler.call_args.kwargs == {
            "output_format": "human",
            "include_schema": "no_schema",
        }


class TestEmitResults:
    """Result emitters must produce exact payloads."""

    def test_export_json_envelope_path_only(self, capsys):
        with patch.object(auth_runner, "write_envelope") as writer:
            _emit_export_result(Path("/tmp/x.json"), "json", "no_schema")
        env = writer.call_args.args[0]
        assert env.command == "pxcli auth export"
        assert env.result == {"path": "/tmp/x.json"}
        writer.assert_called_once_with(env, include_schema="no_schema")

    def test_export_human_message_exact(self, capsys):
        _emit_export_result(Path("/tmp/x.json"), "human", "no_schema")
        assert capsys.readouterr().out == "[OK] Credentials exported to /tmp/x.json\n"

    def test_import_json_envelope_payload_and_schema_kwarg(self):
        with patch.object(auth_runner, "write_envelope") as writer:
            _emit_import_result({"imported": True, "cookies_stored": False}, "json", "no_schema")
        env = writer.call_args.args[0]
        assert env.command == "pxcli auth import"
        assert env.result == {"imported": True, "cookies_stored": False}
        writer.assert_called_once_with(env, include_schema="no_schema")

    def test_import_human_message_exact(self, capsys):
        _emit_import_result({"imported": True, "cookies_stored": True}, "human", "no_schema")
        assert capsys.readouterr().out == "[OK] Credentials imported\n"


class TestBuildExportBundle:
    """The bundle schema must be exact."""

    def test_bundle_fields(self):
        with patch.object(auth_runner, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "2026-09-20-120000"
            dt.now.return_value.isoformat.return_value = "2026-09-20T12:00:00+00:00"
            bundle = _build_export_bundle("tok", {"a": "b"})
        assert bundle["version"] == 1
        assert bundle["token"] == "tok"
        assert bundle["cookies"] == {"a": "b"}


class TestDefaultExportPath:
    """The default filename must follow the timestamped convention."""

    def test_filename_pattern(self):
        with patch.object(auth_runner, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "2026-09-20-120000"
            path = _default_export_path()
        assert str(path) == "pxcli-auth-2026-09-20-120000.json"


class TestHandleExportMissingToken:
    """The unauthenticated path must use the exact command and exception."""

    def test_raises_authentication_error_through_handle_error(self):
        with patch.object(auth_runner, "handle_error", Mock(side_effect=SystemExit(4))) as handler:
            with pytest.raises(SystemExit):
                _handle_export_missing_token("human")
        raised = handler.call_args.args[0]
        assert isinstance(raised, AuthenticationError)
        assert str(raised) == "No stored credentials found. Run 'pxcli auth login' first."
        assert handler.call_args.args[1] == "pxcli auth export"
        assert handler.call_args.kwargs["output_format"] == "human"


class TestRunExportCommandContract:
    """The export runner must sequence warning, write, log and emit exactly."""

    def _run(self, loaded, output):
        manager = Mock(name="token-manager")
        manager.load_token.return_value = loaded
        events: list[tuple[str, object]] = []
        logger = Mock(name="logger")

        def _record_write(token, cookies, path):
            events.append(("write", (token, cookies, path)))

        with (
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="human", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(auth_runner, "get_logger", return_value=logger),
            patch.object(auth_runner, "redact_path", side_effect=lambda p: f"<redacted:{p}>"),
            patch.object(auth_runner, "_write_export_bundle", side_effect=_record_write),
            patch.object(
                auth_runner,
                "_emit_export_result",
                side_effect=lambda *a: events.append(("emit", a)),
            ),
            patch.object(auth_runner, "_default_export_path", return_value=Path("default.json")),
        ):
            run_export_command(output)
        return events, logger

    def test_sequenced_flow_with_default_path(self):
        events, logger = self._run(("tok", {"a": "b"}), None)
        assert [name for name, _ in events] == ["write", "emit"]
        token, cookies, path = events[0][1]
        assert (token, cookies, str(path)) == ("tok", {"a": "b"}, "default.json")
        assert events[1][1][0] == Path("default.json")
        logger.info.assert_called_once_with("Credentials exported to %s", "<redacted:default.json>")

    def test_output_override_wins(self):
        events, _logger = self._run(("tok", None), Path("/safe/bundle.json"))
        assert str(events[0][1][2]) == "/safe/bundle.json"

    def test_write_failure_routes_to_handle_error_with_exact_arguments(self):
        manager = Mock(name="token-manager")
        manager.load_token.return_value = ("tok", None)
        boom = OSError("read-only filesystem")
        with (
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="human", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(auth_runner, "_write_export_bundle", Mock(side_effect=boom)),
            patch.object(auth_runner, "handle_error", Mock(side_effect=SystemExit(1))) as handler,
        ):
            with pytest.raises(SystemExit):
                run_export_command(None)
        handler.assert_called_once_with(
            boom,
            "pxcli auth export",
            output_format="human",
            include_schema="no_schema",
        )

    def test_emit_receives_exact_format_and_schema(self):
        events, _logger = self._run(("tok", None), None)
        assert events[1][1] == (Path("default.json"), "human", "no_schema")

    def test_missing_token_routes_to_taxonomy(self):
        manager = Mock(name="token-manager")
        manager.load_token.return_value = (None, None)
        with (
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="human", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(
                auth_runner, "_handle_export_missing_token", Mock(side_effect=SystemExit(4))
            ),
        ):
            with pytest.raises(SystemExit):
                run_export_command(None)


class TestWriteExportBundle:
    """The bundle writer must warn first, then atomically write 0600."""

    def test_warning_precedes_atomic_write_with_exact_arguments(self, capsys):
        calls: list[tuple[object, ...]] = []
        with (
            patch.object(auth_runner, "click") as click_mock,
            patch.object(
                auth_runner,
                "atomic_write_json",
                side_effect=lambda path, bundle, mode: calls.append((path, bundle, mode)),
            ),
        ):
            auth_runner._write_export_bundle("tok", {"a": "b"}, Path("out.json"))
        assert click_mock.echo.call_count == 1
        assert click_mock.echo.call_args == call(auth_runner._EXPORT_WARNING, err=True)
        assert len(calls) == 1
        path, bundle, mode = calls[0]
        assert (str(path), mode) == ("out.json", 0o600)
        assert bundle["version"] == 1
        assert bundle["token"] == "tok"
        assert bundle["cookies"] == {"a": "b"}


class TestRunImportCommandContract:
    """The import runner must sequence load, save and emit exactly."""

    def test_full_sequence_and_envelope_payload(self):
        events: list[tuple[str, object]] = []
        manager = Mock(name="token-manager")

        with (
            patch.object(
                auth_runner,
                "_load_import_bundle",
                side_effect=lambda path, opts: ("tok", {"a": "b"}),
            ),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="json", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(auth_runner, "TokenManager", Mock(return_value=manager)),
            patch.object(auth_runner, "get_save_cookies_enabled", return_value=True),
            patch.object(auth_runner, "click"),
            patch.object(auth_runner, "get_logger", return_value=Mock(name="logger")),
            patch.object(auth_runner, "redact_path", side_effect=lambda p: f"<r:{p}>"),
            patch.object(auth_runner, "success_envelope", wraps=auth_runner.success_envelope),
            patch.object(
                auth_runner,
                "_emit_import_result",
                side_effect=lambda result, *a: events.append(("emit", result)),
            ),
        ):
            run_import_command(Path("b.json"))

        manager.save_token.assert_called_once_with("tok", {"a": "b"})
        assert events == [("emit", {"imported": True, "cookies_stored": True})]

    def test_save_receives_resolved_options_object(self):
        saved: list[object] = []
        options = auth_runner._AuthOutputOptions(
            output_format="json", schema_inclusion="no_schema", debug_level="standard"
        )
        with (
            patch.object(
                auth_runner,
                "_load_import_bundle",
                side_effect=lambda path, opts: ("tok", None),
            ),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(auth_runner, "_resolve_auth_output_options", return_value=options),
            patch.object(
                auth_runner,
                "_save_imported_credentials",
                side_effect=lambda token, cookies, opts: saved.append(opts),
            ),
            patch.object(auth_runner, "get_logger", return_value=Mock(name="logger")),
            patch.object(auth_runner, "_emit_import_result", Mock(name="emit")),
        ):
            run_import_command(Path("b.json"))
        assert saved == [options]

    def test_import_logs_redacted_path_with_exact_message(self):
        logger = Mock(name="logger")
        with (
            patch.object(
                auth_runner,
                "_load_import_bundle",
                side_effect=lambda path, opts: ("tok", None),
            ),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="human", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(
                auth_runner,
                "_save_imported_credentials",
                Mock(name="save"),
            ),
            patch.object(auth_runner, "get_logger", return_value=logger),
            patch.object(auth_runner, "redact_path", side_effect=lambda p: f"<r:{p}>"),
            patch.object(auth_runner, "_emit_import_result", Mock(name="emit")),
        ):
            run_import_command(Path("b.json"))
        logger.info.assert_called_once_with("Credentials imported from %s", "<r:b.json>")

    def test_emit_receives_exact_schema_inclusion(self):
        seen: list[tuple[object, ...]] = []
        with (
            patch.object(
                auth_runner,
                "_load_import_bundle",
                side_effect=lambda path, opts: ("tok", None),
            ),
            patch.object(auth_runner, "_resolve_ctx_flags", return_value=None),
            patch.object(
                auth_runner,
                "_resolve_auth_output_options",
                return_value=auth_runner._AuthOutputOptions(
                    output_format="json", schema_inclusion="no_schema", debug_level="standard"
                ),
            ),
            patch.object(auth_runner, "_save_imported_credentials", Mock(name="save")),
            patch.object(auth_runner, "get_logger", return_value=Mock(name="logger")),
            patch.object(
                auth_runner,
                "_emit_import_result",
                side_effect=lambda result, fmt, schema: seen.append((result, fmt, schema)),
            ),
        ):
            run_import_command(Path("b.json"))
        assert seen[0][1:] == ("json", "no_schema")
