# Ollama Dashboard - Development Guide

## Project Overview

A Flask-based dashboard for monitoring locally running Ollama models. The app connects to Ollama's API at `http://localhost:11434`, displays running models with real-time status, and maintains a history of model usage.

## Build & Run

### Development
```bash
just dev                                            # Setup venv and start dev server
# or directly:
./scripts/dev.sh
```

Development server runs at `http://127.0.0.1:5000` (use IP, not `localhost`)

### Production (Docker)
```bash
just build                                          # Build and start container (clean rebuild)
just up                                             # Start existing image
just down                                           # Stop container
just logs                                           # Tail container logs
```

### Testing
```bash
just test                                           # Run all tests
just test-one tests/test_ollama_service.py          # Run specific test file
just test-one tests/test_ollama_service.py::TestOllamaService::test_ping_endpoint  # Single test
```

## Architecture

### Application Factory Pattern
- Entry point: `wsgi.py` creates app via `app/__init__.py:create_app()`
- Flask app is instantiated using the factory pattern with blueprints
- Configuration loaded from `Config` class in `app/__init__.py` (consolidates `app/config.py`)

### Core Components

**Services** (`app/services/`)
- `OllamaService`: Singleton service that manages Ollama API communication and history
  - Initialized with `init_app(app)` to receive Flask app context
  - Handles API calls to `/api/ps` endpoint
  - Tracks model sessions in `history.json` (start/end times, change-only writes)
  - Delegates all formatting to `format_utils`
- `format_utils`: Standalone formatting functions (`format_size`, `format_datetime`, `format_time_ago`, `format_relative_time`, `format_duration`)

**Routes** (`app/routes/`)
- Blueprint registered in `main.py`
- Main route (`/`) renders dashboard with model data
- Service instance is module-level but initialized via `init_app(app)` for context

**Templates** (`app/templates/`)
- Jinja2 templates with custom filters (`datetime`, `time_ago`)
- Filters registered in `main.py` using functions from `app/services/format_utils`

### Data Flow
1. Route handler calls `ollama_service.get_running_models()`
2. Service makes HTTP GET to `http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/ps`
3. Response processed: formats sizes, families, expiration times
4. Current models added to history deque and persisted to `history.json`
5. Formatted data returned to template for rendering

### Docker Networking
- Container connects to host Ollama via `host.docker.internal`
- Volumes mount `history.json` for persistence across container restarts
- Static files and templates mounted read-only

## Configuration

Environment variables (see `app/__init__.py:Config`):
- `OLLAMA_HOST`: Ollama server host (default: `localhost`, Docker: `host.docker.internal`)
- `OLLAMA_PORT`: Ollama server port (default: `11434`)
- `HISTORY_RETENTION_DAYS`: Days of model session history to retain (default: `30`)
- `HISTORY_FILE`: History JSON path (default: `history.json`)

## Key Conventions

### Service Initialization Pattern
Services use lazy initialization with `init_app(app)`:
```python
# Module level
ollama_service = OllamaService()

# In route init or blueprint registration
def init_app(app):
    ollama_service.init_app(app)
```

### Error Handling
- Routes catch service exceptions and pass error strings to templates
- Templates render error state when `error` is not None
- Service methods raise descriptive exceptions (e.g., "Could not connect to Ollama server...")

### Time Formatting
Two approaches for time display:
- `format_datetime()`: Converts to local timezone with abbreviation (e.g., "2:45 PM, Feb 7 (PST)")
- `format_time_ago()`: Relative time buckets (e.g., "about 2 hours", "a few minutes")

### History Management
- History stored as a list of **model sessions** (start/end times per model run)
- Each entry: `{model_name, started_at, ended_at (null if running), families, parameter_size, size, cpu_gpu_split}`
- Only written to JSON when the model set changes (not every tick)
- Entries older than `HISTORY_RETENTION_DAYS` pruned on load
- `get_history()` computes and attaches `duration` to each session before returning

### Test Routes
Test routes exist for previewing UI states (not currently in routes/main.py):
- `/test/no-models`: Empty state preview
- `/test/error`: Error state preview
- `/test/with-models`: Sample models preview
