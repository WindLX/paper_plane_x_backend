set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    @just --list

setup:
    uv sync

dev:
    uv run app

run:
    uv run app

debug:
    uv run debug

test *args:
    uv run pytest {{args}}

lint:
    uv run ruff check src tests

lint-fix:
    uv run ruff check src tests --fix

format:
    uv run ruff format src tests

format-check:
    uv run ruff format --check src tests

typecheck:
    uv run pyright

build:
    uv build

build-console:
    ./scripts/build_console.sh

pre-commit:
    just lint
    just format-check
    just typecheck
    just test
