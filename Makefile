# Makefile — D&D Companion
# Backend FastAPI :8010 · frontend Vite :5173 · data-pipeline (importers)
# Requiere: python 3.11+, node/npm, bash (Git Bash en Windows).
# Uso: make help

PY      ?= python
UVICORN ?= uvicorn

BACKEND_DIR  := backend
FRONTEND_DIR := frontend
PIPE_DIR     := data-pipeline

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend setup-pipeline \
        dev dev-backend dev-frontend \
        test test-backend test-frontend test-all compile build preview \
        seed shots \
        import-srd-2014 import-srd-2024 import-open5e import-5etools \
        import-foundry import-dnddata import-file \
        docker-up docker-up-d docker-down docker-logs \
        health clean

# ============================================================
#  HELP / SETUP
# ============================================================

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: setup-backend setup-frontend setup-pipeline ## Instalación completa (backend + frontend + pipeline)

setup-backend: ## Instala el backend en modo editable + extras dev
	cd $(BACKEND_DIR) && pip install -e ".[dev]"

setup-frontend: ## Instala dependencias del frontend
	cd $(FRONTEND_DIR) && npm install

setup-pipeline: ## Instala la data-pipeline en modo editable
	cd $(PIPE_DIR) && pip install -e .

# ============================================================
#  DESARROLLO
# ============================================================

dev: ## Levanta backend (:8010) + frontend (:5173) en paralelo
	$(MAKE) dev-backend & $(MAKE) dev-frontend & wait

dev-backend: ## Solo el backend (uvicorn --reload, :8010)
	cd $(BACKEND_DIR) && $(UVICORN) app.main:app --reload --port 8010

dev-frontend: ## Solo el frontend (vite dev, :5173 — proxifica /api a :8010)
	cd $(FRONTEND_DIR) && npm run dev

# ============================================================
#  TESTS / VERIFICACIÓN
# ============================================================

test: test-backend test-frontend ## Todos los tests (backend + frontend)

test-backend: ## pytest de backend/tests
	$(PY) -m pytest $(BACKEND_DIR)/tests

test-frontend: ## vitest del frontend
	cd $(FRONTEND_DIR) && npm run test

test-all: compile test ## compileall + suite completa

compile: ## Verificación de sintaxis Python (app + pipeline)
	$(PY) -m compileall $(BACKEND_DIR)/app $(PIPE_DIR)

build: ## Build de producción del frontend (vite + PWA)
	cd $(FRONTEND_DIR) && npm run build

preview: ## Sirve el build de producción localmente
	cd $(FRONTEND_DIR) && npm run preview

# ============================================================
#  DATOS / ASSETS
# ============================================================

seed: ## Siembra la demo local (campaña + combate + mapa)
	$(PY) tools/seed_demo.py

shots: ## Regenera la matriz de capturas de docs/assets (requiere dev servers)
	node tools/screenshots.mjs

import-srd-2014: ## Importa el SRD CC-BY-4.0 (edición 2014)
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-srd --edition 2014

import-srd-2024: ## Importa el SRD CC-BY-4.0 (edición 2024)
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-srd --edition 2024

import-open5e: ## Importa un documento Open5e — uso: make import-open5e DOC=tob API=v1
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-open5e --document $(DOC) --api $(or $(API),v1)

import-5etools: ## Importa 5etools local — uso: make import-5etools PATH=<clone>/data
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-5etools --path $(PATH)

import-foundry: ## Importa packs Foundry — uso: make import-foundry PATH=<clone>/packs/_source
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-foundry --path $(PATH)

import-dnddata: ## Importa nick-aschenbach/dnd-data (NON-FREE) — uso: make import-dnddata PATH=<clone>/data RULESET=dnd5e-2014
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-dnddata $(if $(PATH),--path $(PATH),) --ruleset $(or $(RULESET),dnd5e-2014)

import-file: ## Importa un JSON propio — uso: make import-file PATH=<f> LICENSE=<lic> TYPE=<t>
	cd $(PIPE_DIR) && $(PY) -m pipeline.cli import-file --path $(PATH) --license $(LICENSE) --type $(TYPE)

# ============================================================
#  DOCKER / OPS
# ============================================================

docker-up: ## Levanta backend+frontend con docker compose (same-origin :80)
	docker compose up --build

docker-up-d: ## Igual que docker-up pero en background
	docker compose up --build -d

docker-down: ## Detiene los contenedores
	docker compose down

docker-logs: ## Sigue los logs de docker compose
	docker compose logs -f

health: ## Comprueba que el backend local responde
	@curl -s http://localhost:8010/api/health && echo

clean: ## Borra artefactos generados (__pycache__, dist, caches)
	find $(BACKEND_DIR) $(PIPE_DIR) -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(FRONTEND_DIR)/dist .pytest_cache $(BACKEND_DIR)/.pytest_cache
