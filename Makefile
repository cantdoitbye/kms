PY := backend/.venv/bin/python

.PHONY: setup db api web test eval eval-answers ablation gate bench up down

setup:
	python3 -m venv backend/.venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r backend/requirements.txt
	cd frontend && npm install
	cp -n backend/.env.example backend/.env || true

db:
	docker compose up -d db

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q tests

eval:
	cd backend && .venv/bin/python -m eval.run_eval

eval-answers:
	cd backend && .venv/bin/python -m eval.run_eval --answers

ablation:
	cd backend && .venv/bin/python -m eval.ablation

gate:
	cd backend && .venv/bin/python -m eval.gate

# BEIR SciFact benchmark (downloads ~3 MB on first run; indexing takes ~20 min on a laptop CPU)
bench:
	mkdir -p backend/data/benchmarks
	test -f backend/data/benchmarks/scifact/corpus.jsonl || (cd backend/data/benchmarks && \
	  curl -sSLO https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip && unzip -q scifact.zip)
	cd backend && .venv/bin/python -m eval.beir

up:
	docker compose up --build

down:
	docker compose down
