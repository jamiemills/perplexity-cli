"""Tests for XDG_CONFIG_HOME support in get_config_dir."""

from pathlib import Path


class TestXDGConfigHome:
    """Test XDG_CONFIG_HOME support in get_config_dir."""

    def test_xdg_config_home_used(self, monkeypatch, tmp_path):
        """When XDG_CONFIG_HOME is set, config dir is under it."""
        monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from perplexity_cli.utils.config import get_config_dir

        result = get_config_dir()
        assert result == tmp_path / "perplexity-cli"

    def test_xdg_unset_falls_back_to_default(self, monkeypatch):
        """When XDG_CONFIG_HOME is not set, falls back to ~/.config."""
        monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        from perplexity_cli.utils.config import get_config_dir

        result = get_config_dir()
        assert result == Path.home() / ".config" / "perplexity-cli"

    def test_perplexity_config_dir_takes_precedence(self, monkeypatch, tmp_path):
        """PERPLEXITY_CONFIG_DIR overrides XDG_CONFIG_HOME."""
        custom = tmp_path / "custom"
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(custom))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        from perplexity_cli.utils.config import get_config_dir

        result = get_config_dir()
        assert result == custom

    def test_xdg_directory_created(self, monkeypatch, tmp_path):
        """Config directory is created if it does not exist."""
        monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "new_xdg"))
        from perplexity_cli.utils.config import get_config_dir

        result = get_config_dir()
        assert result.exists()
