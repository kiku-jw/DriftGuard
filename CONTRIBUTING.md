# Contributing to DriftGuard

Thank you for your interest in contributing to DriftGuard! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions. We're building something useful together.

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- Docker (optional, for testing containers)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/kiku-jw/DriftGuard.git
cd agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev,all]"

# Verify installation
driftguard --version
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/driftguard --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_models.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Run linter
ruff check src tests

# Auto-fix linting issues
ruff check --fix src tests

# Run type checker
mypy src

# Format code (optional)
ruff format src tests
```

## How to Contribute

### Reporting Bugs

1. Search existing issues first
2. Create a new issue with:
   - Clear title
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, DriftGuard version)

### Suggesting Features

1. Check if the feature is already planned (see CHANGELOG.md)
2. Open an issue with:
   - Use case description
   - Proposed solution
   - Alternative approaches considered

### Submitting Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass: `pytest`
6. Ensure code quality: `ruff check src tests && mypy src`
7. Commit with clear message: `git commit -m "Add feature X"`
8. Push to your fork: `git push origin feature/your-feature`
9. Open a Pull Request

### PR Guidelines

- Keep PRs focused on a single change
- Include tests for new functionality
- Update documentation if needed
- Follow existing code style
- Add entry to CHANGELOG.md under [Unreleased]

## Project Structure

```
src/driftguard/
├── cli/           # CLI commands (Click)
├── connectors/    # Data source connectors
├── detection/     # Anomaly detection logic
├── alerting/      # Webhook delivery
├── storage/       # State persistence
├── config.py      # Configuration models
└── models.py      # Core data models

tests/
├── unit/          # Unit tests
└── integration/   # Integration tests
```

## Adding a New Connector

1. Create `src/driftguard/connectors/my_connector.py`
2. Implement the `Connector` interface from `base.py`
3. Add connector to `__init__.py` exports
4. Add tests in `tests/unit/test_my_connector.py`
5. Update documentation

Example:

```python
from driftguard.connectors.base import Connector
from driftguard.models import DataSnapshot

class MyConnector(Connector):
    def collect(self, config: SourceConfig) -> DataSnapshot:
        # Implementation
        pass
    
    def collect_with_error_handling(self, config: SourceConfig) -> DataSnapshot:
        # Implementation with error handling
        pass
```

## Adding a New Storage Backend

1. Create `src/driftguard/storage/my_backend.py`
2. Implement the `StateStore` interface from `base.py`
3. Add backend to `__init__.py` exports
4. Add tests in `tests/unit/test_my_backend.py`
5. Update configuration to support new backend

## Commit Message Guidelines

- Use present tense: "Add feature" not "Added feature"
- Use imperative mood: "Move cursor to..." not "Moves cursor to..."
- First line: 50 chars max, capitalize, no period
- Body: Wrap at 72 chars, explain what and why

Examples:
```
Add volume deviation detection

Implement statistical deviation detection based on baseline
standard deviation. Uses configurable deviation_factor to
determine threshold.

Closes #123
```

## Release Process

1. Update version in `src/driftguard/__init__.py`
2. Update CHANGELOG.md
3. Create git tag: `git tag v0.1.0`
4. Push tag: `git push origin v0.1.0`
5. GitHub Actions builds and publishes Docker image

## Questions?

- Open an issue for questions
- Check existing documentation in `/docs`
- Review CHANGELOG.md for planned features

Thank you for contributing!
