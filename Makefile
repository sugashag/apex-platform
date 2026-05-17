.PHONY: help dev down logs migrate migration lint format typecheck test shell clean

help:
	@echo "APEX Platform — common dev commands"
	@echo ""
	@echo "  make dev              Start docker-compose (postgres + redis + api)"
	@echo "  make down             Stop docker-compose"
	@echo "  make logs             Tail api logs"
	@echo "  make migrate          Run alembic upgrade head"
	@echo "  make migration name=x Create a new alembic migration"
	@echo "  make lint             Run ruff check"
	@echo "  make format           Run ruff format"
	@echo "  make typecheck        Run mypy"
	@echo "  make test             Run pytest"
	@echo "  make shell            Open psql session in the postgres container"
	@echo "  make clean            Remove caches and volumes"

dev:
	docker compose up -d --build
	@echo "API:      http://localhost:8000"
	@echo "Health:   http://localhost:8000/health"
	@echo "Docs:     http://localhost:8000/docs"

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose exec api alembic upgrade head

migration:
ifndef name
	$(error Usage: make migration name=add_something_table)
endif
	docker compose exec api alembic revision --autogenerate -m "$(name)"

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

typecheck:
	poetry run mypy app/

test:
	poetry run pytest -v

shell:
	docker compose exec postgres psql -U apex -d apex

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache
