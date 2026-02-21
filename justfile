# Ollama Dashboard - common development tasks

DC := "docker compose -f docker/docker-compose.yml"

default:
    just -ul

# Start the development server (creates venv and installs deps if needed)
dev:
    ./scripts/dev.sh

# Install dependencies into the venv
install:
    #!/usr/bin/env bash
    if [ ! -d ".venv" ]; then python -m venv .venv; fi
    source .venv/bin/activate && pip install -r requirements.txt

# Run all tests
test:
    source .venv/bin/activate && python -m pytest tests/ -v

# Run a specific test file or test case (e.g. just test-one tests/test_ollama_service.py)
test-one target:
    source .venv/bin/activate && python -m pytest {{ target }} -v

# Build and start the Docker container (rebuilds from scratch)
build:
    {{ DC }} build

# Start an existing Docker image without rebuilding
up:
    {{ DC }} up -d

# Stop the Docker container
down:
    {{ DC }} down

# Tail Docker container logs
logs:
    {{ DC }} logs -f

# Clear the history file
clear-history:
    echo '[]' > history.json
