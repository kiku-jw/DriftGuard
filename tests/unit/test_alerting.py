"""Tests for alerting pipeline."""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from driftguard.alerting.pipeline import AlertingPipeline
from driftguard.alerting.webhook import WebhookDelivery
from driftguard.config import AlertingConfig, SourceConfig, WebhookConfig
from driftguard.models import (
    AlertState,
    Decision,
    DecisionStatus,
    DeliveryResult,
    EventType,
    Reason,
    WebhookPayload,
)


@pytest.fixture
def webhook_config():
    return WebhookConfig(
        name="test-webhook",
        url="https://example.com/webhook",
        secret="test-secret",
        events=["anomaly", "recovery"],
        timeout_seconds=5,
    )


@pytest.fixture
def payload():
    return WebhookPayload(
        event_type=EventType.ANOMALY,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        source_name="test-source",
        source_type="sql",
        decision={"status": "ANOMALY", "reasons": []},
        metrics={"row_count": 100},
        agent_id="test-agent",
    )


@pytest.fixture
def source_config(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://localhost/test")
    return SourceConfig(
        name="test-source",
        type="sql",
        dialect="postgres",
        connection="${DB_URL}",
        query="SELECT COUNT(*) as row_count FROM test",
    )


@pytest.fixture
def decision():
    return Decision(
        status=DecisionStatus.ANOMALY,
        reasons=[Reason(code="VOLUME_LOW", message="Row count dropped")],
        metrics={"row_count": 100},
        baseline_summary=None,
    )


class TestWebhookDelivery:
    def test_dry_run_returns_success(self, webhook_config, payload):
        delivery = WebhookDelivery(dry_run=True)

        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.attempts == 0

    def test_signature_generation(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        headers = delivery._build_headers(body, payload, webhook_config)

        assert "X-DriftGuard-Signature" in headers
        assert headers["X-DriftGuard-Signature"].startswith("sha256=")

    def test_signature_verification(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        signature = delivery._sign(body, webhook_config.secret)

        expected = hmac.new(
            webhook_config.secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected

    def test_headers_include_metadata(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        headers = delivery._build_headers(body, payload, webhook_config)

        assert headers["Content-Type"] == "application/json"
        assert headers["X-DriftGuard-Event"] == "anomaly"
        assert "X-DriftGuard-Event-ID" in headers
        assert "X-DriftGuard-Timestamp" in headers

    @patch("driftguard.alerting.webhook.httpx.Client")
    def test_successful_delivery(self, mock_client_class, webhook_config, payload):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.status_code == 200
        assert result.attempts == 1

    @patch("driftguard.alerting.webhook.httpx.Client")
    def test_4xx_is_considered_success(self, mock_client_class, webhook_config, payload):
        mock_response = MagicMock()
        mock_response.status_code = 400

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.status_code == 400

    @patch("driftguard.alerting.webhook.httpx.Client")
    @patch("driftguard.alerting.webhook.time.sleep")
    def test_retry_on_5xx(self, mock_sleep, mock_client_class, webhook_config, payload):
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [mock_response_500, mock_response_200]
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.attempts == 2


class TestWebhookPayload:
    def test_canonical_json_is_deterministic(self, payload):
        json1 = payload.to_canonical_json()
        json2 = payload.to_canonical_json()

        assert json1 == json2

    def test_canonical_json_has_no_whitespace(self, payload):
        json_str = payload.to_canonical_json()

        assert "\n" not in json_str
        assert ": " not in json_str

    def test_build_payload(self):
        delivery = WebhookDelivery()

        payload = delivery.build_payload(
            source_name="test",
            source_type="sql",
            event_type=EventType.ANOMALY,
            decision_dict={"status": "ANOMALY"},
            metrics={"row_count": 100},
            baseline_dict={"median": 1000},
            agent_id="agent-1",
        )

        assert payload.source_name == "test"
        assert payload.event_type == EventType.ANOMALY
        assert payload.version == "1"


class TestAlertingPipeline:
    def test_process_skips_webhook_when_event_not_enabled(self, source_config, decision):
        store = MagicMock()
        pipeline = AlertingPipeline(
            config=AlertingConfig(
                webhooks=[
                    WebhookConfig(
                        name="test-webhook",
                        url="https://example.com/webhook",
                        events=["warning"],
                    )
                ]
            ),
            store=store,
            agent_id="agent-1",
        )

        result = pipeline.process(source_config, decision)

        assert result == {}
        store.get_alert_state.assert_not_called()

    def test_process_marks_webhook_success_when_alert_is_suppressed(self, source_config, decision):
        store = MagicMock()
        state = AlertState(
            source_name=source_config.name,
            target_name="test-webhook",
            notified_status=decision.status,
            notified_reason_hash=decision.reason_hash,
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        store.get_alert_state.return_value = state

        pipeline = AlertingPipeline(
            config=AlertingConfig(
                webhooks=[
                    WebhookConfig(
                        name="test-webhook",
                        url="https://example.com/webhook",
                        events=["anomaly"],
                    )
                ]
            ),
            store=store,
            agent_id="agent-1",
        )

        result = pipeline.process(source_config, decision)

        assert result == {"test-webhook": True}
        store.log_delivery.assert_not_called()
        store.set_alert_state.assert_not_called()

    def test_get_event_type_maps_warning_and_unknown_statuses(self):
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=MagicMock(),
            agent_id="agent-1",
        )

        warning_decision = Decision(
            status=DecisionStatus.WARNING,
            reasons=[Reason(code="VOLUME_LOW", message="warn")],
            metrics={},
            baseline_summary=None,
        )
        unknown_decision = Decision(
            status=DecisionStatus.UNKNOWN,
            reasons=[],
            metrics={},
            baseline_summary=None,
        )

        assert pipeline._get_event_type(warning_decision) == EventType.WARNING
        assert pipeline._get_event_type(unknown_decision) == EventType.INFO

    def test_get_event_type_maps_ok_status_to_recovery(self):
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=MagicMock(),
            agent_id="agent-1",
        )
        decision = Decision(
            status=DecisionStatus.OK,
            reasons=[],
            metrics={},
            baseline_summary=None,
        )

        assert pipeline._get_event_type(decision) == EventType.RECOVERY

    def test_should_alert_returns_false_for_same_status_and_hash(self, decision):
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=MagicMock(),
            agent_id="agent-1",
        )
        state = AlertState(
            source_name="test-source",
            target_name="test-webhook",
            notified_status=decision.status,
            notified_reason_hash=decision.reason_hash,
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        assert pipeline._should_alert(decision, state) is False

    def test_should_alert_returns_true_for_unknown_status(self, decision):
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=MagicMock(),
            agent_id="agent-1",
        )
        state = AlertState(
            source_name="test-source",
            target_name="test-webhook",
            notified_status=DecisionStatus.UNKNOWN,
            notified_reason_hash="",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        assert pipeline._should_alert(decision, state) is True

    def test_should_alert_returns_true_for_changed_status(self, decision):
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=MagicMock(),
            agent_id="agent-1",
        )
        state = AlertState(
            source_name="test-source",
            target_name="test-webhook",
            notified_status=DecisionStatus.OK,
            notified_reason_hash="different",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        assert pipeline._should_alert(decision, state) is True

    def test_send_alert_logs_and_updates_state_on_success(
        self,
        monkeypatch,
        source_config,
        decision,
    ):
        monkeypatch.setenv("WEBHOOK_URL", "https://resolved.example/webhook")
        monkeypatch.setenv("WEBHOOK_SECRET", "resolved-secret")

        store = MagicMock()
        pipeline = AlertingPipeline(
            config=AlertingConfig(cooldown_minutes=30),
            store=store,
            agent_id="agent-1",
        )
        webhook = WebhookConfig(
            name="test-webhook",
            url="${WEBHOOK_URL}",
            secret="${WEBHOOK_SECRET}",
            events=["anomaly"],
        )
        state = AlertState(
            source_name=source_config.name,
            target_name=webhook.name,
            notified_status=DecisionStatus.UNKNOWN,
            notified_reason_hash="",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )
        delivery_result = DeliveryResult(success=True, status_code=202, latency_ms=45, attempts=1)

        with patch.object(pipeline.delivery, "deliver", return_value=delivery_result) as mock_deliver:
            success = pipeline._send_alert(
                source_config,
                decision,
                EventType.ANOMALY,
                webhook,
                state,
            )

        assert success is True
        resolved_webhook = mock_deliver.call_args.args[1]
        assert resolved_webhook.url == "https://resolved.example/webhook"
        assert resolved_webhook.secret == "resolved-secret"
        store.log_delivery.assert_called_once()
        store.set_alert_state.assert_called_once()
        saved_state = store.set_alert_state.call_args.args[0]
        assert saved_state.notified_status == DecisionStatus.ANOMALY
        assert saved_state.cooldown_until is not None

    def test_send_alert_returns_false_when_delivery_fails(self, source_config, decision):
        store = MagicMock()
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=store,
            agent_id="agent-1",
        )
        webhook = WebhookConfig(
            name="test-webhook",
            url="https://example.com/webhook",
            events=["anomaly"],
        )
        state = AlertState(
            source_name=source_config.name,
            target_name=webhook.name,
            notified_status=DecisionStatus.UNKNOWN,
            notified_reason_hash="",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )
        delivery_result = DeliveryResult(
            success=False,
            status_code=503,
            error="Service unavailable",
            latency_ms=20,
            attempts=4,
        )

        with patch.object(pipeline.delivery, "deliver", return_value=delivery_result):
            success = pipeline._send_alert(
                source_config,
                decision,
                EventType.ANOMALY,
                webhook,
                state,
            )

        assert success is False
        store.log_delivery.assert_called_once()
        store.set_alert_state.assert_not_called()

    def test_send_alert_short_circuits_in_dry_run(self, source_config, decision):
        store = MagicMock()
        pipeline = AlertingPipeline(
            config=AlertingConfig(),
            store=store,
            agent_id="agent-1",
            dry_run=True,
        )
        webhook = WebhookConfig(
            name="test-webhook",
            url="https://example.com/webhook",
            events=["anomaly"],
        )
        state = AlertState(
            source_name=source_config.name,
            target_name=webhook.name,
            notified_status=DecisionStatus.UNKNOWN,
            notified_reason_hash="",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        success = pipeline._send_alert(
            source_config,
            decision,
            EventType.ANOMALY,
            webhook,
            state,
        )

        assert success is True
        store.log_delivery.assert_not_called()
        store.set_alert_state.assert_not_called()
