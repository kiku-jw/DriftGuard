"""Mock tests for SQL connector."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from driftguard.config import SourceConfig
from driftguard.connectors.base import (
    ConnectionError,
    ConnectorError,
    QueryError,
    TimeoutError,
    ValidationError,
)
from driftguard.connectors.sql import SQLConnector


@pytest.fixture
def connector():
    return SQLConnector(timeout_seconds=5)

@pytest.fixture
def source_config(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://user:pass@localhost:5432/db")
    return SourceConfig(
        name="test_sql",
        type="sql",
        dialect="postgres",
        connection="${DB_URL}",
        query="SELECT COUNT(*) as row_count FROM my_table",
    )

class TestSQLConnectorMock:
    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_success_postgres(self, mock_create_engine, connector, source_config):
        # Mock engine and connection
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Mock result execution
        mock_result = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_result.fetchone.return_value = [100, datetime(2024, 1, 1, tzinfo=timezone.utc)]
        mock_result.keys.return_value = ["row_count", "latest_timestamp"]

        snapshot = connector.collect(source_config)

        assert snapshot.source_name == "test_sql"
        assert snapshot.row_count == 100
        assert snapshot.latest_timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert snapshot.schema == [
            {"name": "row_count", "type": "int"},
            {"name": "latest_timestamp", "type": "datetime"}
        ]

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_failure_connection(self, mock_create_engine, connector, source_config):
        mock_create_engine.side_effect = OperationalError("Connection error", None, None)

        snapshot = connector.collect_with_error_handling(source_config)

        assert snapshot.collect_status.value == "COLLECT_FAILED"
        assert "Database connection failed" in snapshot.metadata["error_message"]

    def test_build_connection_string_sqlite(self, connector):
        cfg = SourceConfig(
            name="sqlite",
            type="sql",
            dialect="sqlite",
            connection="data.db",
            query="SELECT 1"
        )
        conn_str = connector._build_connection_string(cfg)
        assert conn_str == "sqlite:///data.db"

    def test_build_connection_string_adds_driver_for_non_url_connection(self, connector):
        cfg = SourceConfig(
            name="postgres",
            type="sql",
            dialect="postgres",
            connection="user:pass@localhost:5432/db",
            query="SELECT 1",
        )

        assert connector._build_connection_string(cfg) == "postgresql+psycopg2://user:pass@localhost:5432/db"

    def test_extract_metrics_various_names(self, connector, source_config):
        # Test mapping 'count' to 'row_count'
        metrics = connector._extract_metrics({"count": 42}, source_config)
        assert metrics["row_count"] == 42

        # Test mapping 'max_timestamp' to 'latest_timestamp'
        ts = datetime(2024, 1, 1)
        metrics = connector._extract_metrics({"row_count": 10, "max_timestamp": ts}, source_config)
        assert metrics["latest_timestamp"] == ts.replace(tzinfo=timezone.utc)

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_raises_query_error_when_query_returns_no_rows(
        self, mock_create_engine, connector, source_config
    ):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        with pytest.raises(QueryError, match="Query returned no rows"):
            connector.collect(source_config)

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_raises_timeout_error_for_timeout_operational_error(
        self, mock_create_engine, connector, source_config
    ):
        mock_create_engine.side_effect = OperationalError("timeout while connecting", None, None)

        with pytest.raises(TimeoutError, match="Query timed out"):
            connector.collect(source_config)

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_raises_query_error_for_programming_error(
        self, mock_create_engine, connector, source_config
    ):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = ProgrammingError("bad sql", None, None)
        mock_create_engine.return_value = mock_engine

        with pytest.raises(QueryError, match="Query execution failed"):
            connector.collect(source_config)

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_wraps_unexpected_errors(self, mock_create_engine, connector, source_config):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = RuntimeError("boom")
        mock_create_engine.return_value = mock_engine

        with pytest.raises(ConnectorError, match="Unexpected error: boom"):
            connector.collect(source_config)

    @patch("driftguard.connectors.sql.create_engine")
    def test_test_connection_returns_true_on_success(self, mock_create_engine, connector, source_config):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        assert connector.test_connection(source_config) is True

    @patch("driftguard.connectors.sql.create_engine")
    def test_test_connection_returns_false_on_failure(self, mock_create_engine, connector, source_config):
        mock_create_engine.side_effect = RuntimeError("unavailable")

        assert connector.test_connection(source_config) is False

    def test_build_connection_string_normalizes_unknown_scheme_using_config_dialect(
        self, connector, monkeypatch
    ):
        monkeypatch.setenv("MYSQL_URL", "mysql2://user:pass@localhost/db")
        cfg = SourceConfig(
            name="mysql",
            type="sql",
            dialect="mysql",
            connection="${MYSQL_URL}",
            query="SELECT 1",
        )

        assert connector._build_connection_string(cfg) == "mysql+pymysql://user:pass@localhost/db"

    def test_build_connection_string_raises_for_unsupported_dialect(self, connector):
        cfg = SourceConfig(
            name="unknown",
            type="sql",
            dialect="oracle",
            connection="db.example.com/service",
            query="SELECT 1",
        )

        with pytest.raises(ConnectionError, match="Unsupported dialect: oracle"):
            connector._build_connection_string(cfg)

    def test_get_connect_args_adds_timeout_for_mysql(self, connector):
        assert connector._get_connect_args("mysql") == {
            "connect_timeout": 5,
            "read_timeout": 5,
        }

    def test_extract_metrics_reads_generic_names_and_numeric_extras(self, connector, source_config):
        naive_dt = datetime(2024, 1, 1, 12, 0, 0)
        metrics = connector._extract_metrics(
            {
                "total_count": "1,234",
                "event_time": naive_dt,
                "error_rate": 0.5,
                "label": "keep-string-out",
            },
            source_config,
        )

        assert metrics["row_count"] == 1234
        assert metrics["latest_timestamp"] == naive_dt.replace(tzinfo=timezone.utc)
        assert metrics["error_rate"] == 0.5
        assert "label" not in metrics

    def test_extract_metrics_raises_when_row_count_is_missing(self, connector, source_config):
        with pytest.raises(ValidationError, match="Query must return 'row_count' column"):
            connector._extract_metrics({"latest_timestamp": datetime.now(timezone.utc)}, source_config)

    def test_to_int_handles_none_float_and_string(self, connector):
        assert connector._to_int(None) == 0
        assert connector._to_int(3.9) == 3
        assert connector._to_int("42.0") == 42

    def test_to_datetime_handles_invalid_and_non_datetime_values(self, connector):
        naive_dt = datetime(2024, 1, 2, 3, 4, 5)

        assert connector._to_datetime(None) is None
        assert connector._to_datetime(naive_dt) == naive_dt.replace(tzinfo=timezone.utc)
        assert connector._to_datetime("2024-01-02T03:04:05") == naive_dt.replace(tzinfo=timezone.utc)
        assert connector._to_datetime("not-a-date") is None
        assert connector._to_datetime(123) is None
