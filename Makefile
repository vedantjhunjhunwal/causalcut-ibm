.PHONY: install install-core run test test-verbose seed docker clean

install:
	pip install -r requirements.txt -r requirements-full.txt

install-core:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests -q

test-verbose:
	pytest tests -v --tb=short

# Replay the coke-oven scenario against a running server (Make run first).
seed:
	python scripts/seed_scenario.py --speed 60

docker:
	docker compose up --build

clean:
	rm -rf data/*.db data/*.db-wal data/*.db-shm data/audit .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +

