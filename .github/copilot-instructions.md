# Ollama Dashboard - Development Guide

## Project Overview

A Flask-based dashboard for monitoring locally running Ollama models. The app connects to Ollama's API at `http://localhost:11434`, displays running models with real-time status, and maintains a history of model usage.

## Build & Run

### Development
```bash
./scripts/dev.sh                                    # Setup venv and start dev server
```

Development server runs at `http://127.0.0.1:5000` (use IP, not `localhost`)

### Production (Docker)
```bash
./scripts/build.sh                                  # Build and start container
docker-compose -f docker/docker-compose.yml up -d   # Start existing image
docker-compose -f docker/docker-compose.yml down    # Stop container
```

### Testing
```bash
python -m pytest                                    # Run all tests
python -m pytest tests/test_ollama_service.py       # Run specific test file
python -m pytest tests/test_ollama_service.py::TestOllamaService::test_ping_endpoint  # Single test
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
  - Manages `history.json` (deque with configurable max length)
  - Formats model data (sizes, timestamps, relative times)

**Routes** (`app/routes/`)
- Blueprint registered in `main.py`
- Main route (`/`) renders dashboard with model data
- Service instance is module-level but initialized via `init_app(app)` for context

**Templates** (`app/templates/`)
- Jinja2 templates with custom filters (`datetime`, `time_ago`)
- Filters defined in `app/__init__.py` and delegated to `OllamaService` methods

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
- `MAX_HISTORY`: Max history entries (default: `50`)
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
- History stored as deque (FIFO when max reached)
- Each entry: `{timestamp: ISO string, models: [model objects]}`
- Persisted to JSON after each update
- Loaded on service initialization

### Test Routes
Test routes exist for previewing UI states (not currently in routes/main.py):
- `/test/no-models`: Empty state preview
- `/test/error`: Error state preview
- `/test/with-models`: Sample models preview
