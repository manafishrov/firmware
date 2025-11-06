.PHONY: lint format typecheck

lint:
	uv run ruff check

format:
	uv run ruff format

typecheck:
	uv run basedpyright
