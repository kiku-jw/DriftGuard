# DriftGuard Agent

> Maintenance mode: preserved as a public reference for data drift monitoring ideas and implementation patterns.

**Automated data quality & drift detection.** Watches incoming data streams, detects anomalies, unexpected spikes, missing values, and schema drift. Ideal for marketplaces, analytics dashboards, financial data, and event pipelines.

[![CI](https://github.com/kiku-jw/DriftGuard/actions/workflows/ci.yaml/badge.svg)](https://github.com/kiku-jw/DriftGuard/actions/workflows/ci.yaml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## Why DriftGuard?

Data can be **syntactically valid but semantically dead**. Your ETL job succeeded, Airflow is green, but:

- The dashboard shows yesterday's data (and no one noticed)
- Row count dropped 90% (but didn't hit zero)
- A critical column is now 30% NULL
- The upstream changed their schema silently

**DriftGuard catches these silent failures before your business does.**

## Features

- **Freshness Detection** — Alerts when data stops updating
- **Volume Monitoring** — Catches unexpected spikes and drops
- **Baseline Learning** — No manual thresholds, learns from your data
- **Schema Drift Detection** — Watches for column name or type changes
- **Webhook Alerts** — Slack, PagerDuty, or any HTTP endpoint
- **Zero UI Required** — CLI-first, DevOps-friendly
- **Lightweight** — Single binary, SQLite storage, no dependencies

## Quick Start

### Installation

```bash
pip install driftguard-agent

# With database drivers
pip install "driftguard-agent[postgres]"
pip install "driftguard-agent[all]"  # postgres, mysql, clickhouse
```

### Initialize

```bash
driftguard init
```

### Configure

Edit `driftguard.yaml`:

```yaml
version: "1"

sources:
  - name: orders_daily
    type: sql
    dialect: postgres
    connection: ${DATABASE_URL}
    query: |
      SELECT 
        COUNT(*) as row_count,
        MAX(created_at) as latest_timestamp
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '24 hours'
    schedule: "0 */6 * * *"
    freshness:
      max_age_hours: 8
    volume:
      min_row_count: 100

alerting:
  webhooks:
    - name: slack
      url: ${SLACK_WEBHOOK_URL}
      events: [anomaly, recovery]
```

### Run

```bash
# Single check
driftguard check

# Daemon mode
driftguard run

# Check specific source
driftguard check --source orders_daily
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `driftguard init` | Create config file |
| `driftguard validate` | Validate configuration |
| `driftguard check` | Run checks on all sources |
| `driftguard run` | Start daemon with scheduler |
| `driftguard status` | Show current status |
| `driftguard history <source>` | Show snapshot history |
| `driftguard explain --source X` | Explain baseline and thresholds |
| `driftguard test-webhook` | Send test payload |
| `driftguard purge` | Clean old snapshots |

## Configuration

### Environment Variables

Secrets must use environment variables:

```yaml
connection: ${DATABASE_URL}      # Required
url: ${SLACK_WEBHOOK_URL}        # Required for webhooks
```

### Source Options

```yaml
sources:
  - name: my_source
    type: sql
    dialect: postgres           # postgres, mysql, clickhouse
    connection: ${DB_URL}
    query: |
      SELECT COUNT(*) as row_count,
             MAX(updated_at) as latest_timestamp
      FROM my_table
    schedule: "*/15 * * * *"    # Cron expression
    freshness:
      max_age_hours: 24         # Hard limit (optional)
      factor: 2.0               # Baseline multiplier
    volume:
      min_row_count: 100        # Hard minimum (optional)
      deviation_factor: 3.0     # Stddev multiplier
    schema_drift: true          # Alert on column changes (optional, default: true)
```

### Webhook Payload

```json
{
  "version": "1",
  "event_id": "uuid",
  "event_type": "anomaly",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": {
    "name": "orders_daily",
    "type": "postgres"
  },
  "decision": {
    "status": "ANOMALY",
    "reasons": [
      {"code": "VOLUME_LOW", "message": "Row count 150 is 85% below baseline"}
    ]
  },
  "metrics": {
    "row_count": 150,
    "baseline_row_count": 1000
  }
}
```

## Docker

```bash
docker run -v ./driftguard.yaml:/app/driftguard.yaml \
  -e DATABASE_URL="..." \
  -e SLACK_WEBHOOK_URL="..." \
  ghcr.io/driftguard/agent:latest run
```

### Docker Compose

```yaml
services:
  driftguard:
    image: ghcr.io/driftguard/agent:latest
    command: run
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
    volumes:
      - ./driftguard.yaml:/app/driftguard.yaml:ro
      - driftguard-data:/app/data
```

## Kubernetes

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: driftguard-check
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: driftguard
              image: ghcr.io/driftguard/agent:latest
              command: ["driftguard", "check"]
              envFrom:
                - secretRef:
                    name: driftguard-secrets
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | Configuration or runtime error |
| 2 | Anomaly detected |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src tests

# Run type checker
mypy src
```

## License

AGPL-3.0. Copyright (c) 2025 KikuAI Lab
