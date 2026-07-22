"""Tests for configuration loading and validation."""

from pathlib import Path

import pytest

from driftguard.config import (
    DriftGuardConfig,
    SourceConfig,
    find_config_file,
    generate_example_config,
    load_config,
    mask_secrets,
    resolve_env_vars,
)


class TestResolveEnvVars:
    def test_resolve_single_var(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = resolve_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"

    def test_resolve_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("VAR1", "one")
        monkeypatch.setenv("VAR2", "two")
        result = resolve_env_vars("${VAR1}_${VAR2}")
        assert result == "one_two"

    def test_missing_var_raises(self):
        with pytest.raises(ValueError, match="Environment variable not set"):
            resolve_env_vars("${NONEXISTENT_VAR}")

    def test_no_vars_returns_original(self):
        result = resolve_env_vars("plain string")
        assert result == "plain string"


class TestMaskSecrets:
    def test_mask_postgres_url(self):
        url = "postgresql://user:password123@localhost:5432/db"
        masked = mask_secrets(url)
        assert "password123" not in masked
        assert "***" in masked
        assert "user" in masked

    def test_mask_url_with_special_chars(self):
        url = "postgresql://admin:p@ss!word@host/db"
        masked = mask_secrets(url)
        assert "p@ss!word" not in masked

    def test_no_mask_needed(self):
        url = "localhost:5432"
        masked = mask_secrets(url)
        assert masked == url


class TestSourceConfig:
    def test_valid_source_with_env_var(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        config = SourceConfig(
            name="test",
            type="sql",
            dialect="postgres",
            connection="${DATABASE_URL}",
            query="SELECT COUNT(*) as row_count FROM test",
        )
        assert config.name == "test"

    def test_invalid_source_with_hardcoded_password(self):
        with pytest.raises(ValueError, match="environment variables"):
            SourceConfig(
                name="test",
                type="sql",
                dialect="postgres",
                connection="postgresql://user:password@localhost/db",
                query="SELECT 1",
            )


class TestDriftGuardConfig:
    def test_valid_config(self):
        config = DriftGuardConfig(
            version="1",
            sources=[],
        )
        assert config.version == "1"

    def test_invalid_version(self):
        with pytest.raises(ValueError, match="Unsupported config version"):
            DriftGuardConfig(version="2")


class TestLoadConfig:
    def test_load_valid_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        config_content = """
version: "1"
agent:
  id: test-agent
sources:
  - name: test
    type: sql
    dialect: postgres
    connection: ${DATABASE_URL}
    query: SELECT COUNT(*) as row_count FROM test
"""
        config_file = tmp_path / "driftguard.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)

        assert config.agent.id == "test-agent"
        assert len(config.sources) == 1

    def test_load_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_load_empty_config_raises(self, tmp_path):
        config_file = tmp_path / "driftguard.yaml"
        config_file.write_text("")

        with pytest.raises(ValueError, match="Config file is empty"):
            load_config(config_file)


class TestFindConfigFile:
    def test_returns_first_existing_standard_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "driftguard.yml").write_text("version: '1'\n")

        result = find_config_file()

        assert result == Path("./driftguard.yml")

    def test_returns_none_when_no_standard_path_exists(self, monkeypatch):
        monkeypatch.setattr("driftguard.config.Path.exists", lambda path: False)

        assert find_config_file() is None


class TestGenerateExampleConfig:
    def test_example_config_is_valid_yaml(self):
        import yaml

        example = generate_example_config()
        data = yaml.safe_load(example)

        assert data["version"] == "1"
        assert "sources" in data
        assert "alerting" in data
