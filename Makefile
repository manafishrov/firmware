.PHONY: lint format typecheck

lint:
	ruff check .

format:
	ruff format .

typecheck:
	basedpyright .
