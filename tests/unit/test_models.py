"""Tests for core data models."""

from datetime import datetime, timedelta, timezone

import pytest

from driftguard.models import (
    AlertState,
    BaselineSummary,
    CollectStatus,
    DataSnapshot,
    Decision,
    DecisionStatus,
    EventType,
    Reason,
    WebhookPayload,
)


class TestDataSnapshot:
    def test_create_success_snapshot(self):
        snapshot = DataSnapshot(
            source_name="test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 100, "latest_timestamp": "2024-01-15T10:00:00Z"},
        )

        assert snapshot.source_name == "test"
        assert snapshot.is_success is True
        assert snapshot.row_count == 100
        assert snapshot.latest_timestamp is not None

    def test_create_failed_snapshot(self):
        snapshot = DataSnapshot(
            source_name="test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.COLLECT_FAILED,
            metrics={},
            metadata={"error_code": "CONNECTION_ERROR"},
        )

        assert snapshot.is_success is False
        assert snapshot.row_count is None

    def test_latest_timestamp_parsing(self):
        snapshot = DataSnapshot(
            source_name="test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 100, "latest_timestamp": "2024-01-15T10:00:00+00:00"},
        )

        assert snapshot.latest_timestamp == datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_latest_timestamp_returns_none_for_invalid_string(self):
        snapshot = DataSnapshot(
            source_name="test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            metrics={"latest_timestamp": "not-a-timestamp"},
        )

        assert snapshot.latest_timestamp is None


class TestDecision:
    def test_ok_decision(self):
        decision = Decision(
            status=DecisionStatus.OK,
            reasons=[],
            metrics={"row_count": 100},
            baseline_summary=None,
        )

        assert decision.status == DecisionStatus.OK
        assert len(decision.reasons) == 0

    def test_anomaly_decision_with_reasons(self):
        decision = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[
                Reason(code="VOLUME_LOW", message="Row count too low"),
                Reason(code="STALE_DATA", message="Data is stale"),
            ],
            metrics={"row_count": 10},
            baseline_summary=None,
        )

        assert decision.status == DecisionStatus.ANOMALY
        assert len(decision.reasons) == 2

    def test_reason_hash_consistency(self):
        decision1 = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="msg1")],
            metrics={},
            baseline_summary=None,
        )
        decision2 = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="different msg")],
            metrics={},
            baseline_summary=None,
        )

        assert decision1.reason_hash == decision2.reason_hash

    def test_reason_hash_different_for_different_reasons(self):
        decision1 = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="msg")],
            metrics={},
            baseline_summary=None,
        )
        decision2 = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="STALE_DATA", message="msg")],
            metrics={},
            baseline_summary=None,
        )

        assert decision1.reason_hash != decision2.reason_hash

    def test_to_dict_includes_confidence_and_reasons(self):
        decision = Decision(
            status=DecisionStatus.WARNING,
            reasons=[Reason(code="NO_NEW_DATA", message="No new rows found")],
            metrics={},
            baseline_summary=None,
            confidence=0.6,
        )

        assert decision.to_dict() == {
            "status": "WARNING",
            "reasons": [{"code": "NO_NEW_DATA", "message": "No new rows found"}],
            "confidence": 0.6,
        }


class TestBaselineSummary:
    def test_to_dict_exposes_baseline_metrics(self):
        summary = BaselineSummary(
            snapshot_count=5,
            row_count_median=100.0,
            row_count_min=90.0,
            row_count_max=110.0,
            row_count_stddev=5.0,
            expected_interval_seconds=3600.0,
            oldest_snapshot_at=None,
            newest_snapshot_at=None,
        )

        assert summary.to_dict() == {
            "snapshot_count": 5,
            "row_count_median": 100.0,
            "row_count_min": 90.0,
            "row_count_max": 110.0,
            "row_count_stddev": 5.0,
            "expected_interval_seconds": 3600.0,
        }


class TestAlertState:
    def test_should_alert_on_status_change(self):
        state = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.OK,
            notified_reason_hash="abc",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        decision = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="test")],
            metrics={},
            baseline_summary=None,
        )

        assert state.should_alert(decision, cooldown_minutes=60) is True

    def test_should_not_alert_same_status(self):
        decision = Decision(
            status=DecisionStatus.OK,
            reasons=[],
            metrics={},
            baseline_summary=None,
        )

        state = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.OK,
            notified_reason_hash=decision.reason_hash,
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        assert state.should_alert(decision, cooldown_minutes=60) is False

    def test_should_not_alert_during_cooldown(self):
        now = datetime.now(timezone.utc)

        state = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.OK,
            notified_reason_hash="abc",
            last_change_at=now,
            last_sent_at=now,
            cooldown_until=now + timedelta(hours=1),
        )

        decision = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="test")],
            metrics={},
            baseline_summary=None,
        )

        assert state.should_alert(decision, cooldown_minutes=60, now=now) is False


class TestWebhookPayload:
    def test_canonical_json_is_stable(self):
        payload = WebhookPayload(
            event_type=EventType.ANOMALY,
            source_name="test",
            source_type="sql",
            decision={"status": "ANOMALY"},
            metrics={"row_count": 100},
            agent_id="agent-1",
        )

        json1 = payload.to_canonical_json()
        json2 = payload.to_canonical_json()

        assert json1 == json2
        assert " " not in json1  # no spaces in canonical form

    def test_to_dict(self):
        payload = WebhookPayload(
            event_type=EventType.ANOMALY,
            source_name="test",
            source_type="sql",
            decision={"status": "ANOMALY"},
            metrics={"row_count": 100},
            agent_id="agent-1",
        )

        data = payload.to_dict()

        assert data["event_type"] == "anomaly"
        assert data["source"]["name"] == "test"
        assert data["metrics"]["row_count"] == 100

    def test_serialize_value_raises_for_unsupported_type(self):
        with pytest.raises(TypeError, match="not JSON serializable"):
            WebhookPayload._serialize_value(object())
