-include .env
ORCHESTRATOR_TOKEN ?= $(AI_SERVICE_TOKEN)
export

.PHONY: deps up down server worker web demo-web demo-seed build seed image chart analytics-server analytics-worker analytics-migrate analytics-image

up:            ## собрать и поднять полный локальный стек
	docker compose up --build -d

down:
	docker compose down

server:        ## API на :8080 (миграции применяются при старте)
	cd backend && go run ./cmd/server

worker:        ## сбор новостей и построение лент
	cd backend && go run ./cmd/worker

web:           ## фронтенд на :5173, /api проксируется на :8080
	cd frontend && npm install && npm run dev

demo-web:      ## интерфейс с подготовленными ответами, без API-ключа и backend
	cd frontend && VITE_DATA_MODE=demo npm run dev -- --host 127.0.0.1 --port 5173 --strictPort

demo-seed:     ## загрузить тестовые профили X5 и РЖД в локальный API
	python3 scripts/seed_demo_profiles.py --base-url http://127.0.0.1:8080

analytics-server: ## Python analytics API на :8090 (сначала make analytics-migrate)
	python3 -m uvicorn orchestrator.analytics.app:create_app --factory --host 127.0.0.1 --port 8090

analytics-worker: ## Python analytics worker
	python3 -m orchestrator.analytics.worker

build:
	cd backend && go build ./... && go vet ./...
	cd frontend && npm ci && npm run build

seed:          ## пересобрать справочники из company_research.xlsx
	python3 scripts/gen_seed.py company_research.xlsx > backend/migrations/0002_seed.sql

image:
	docker build -t alpha-hackaton:dev .
	$(MAKE) analytics-image

analytics-image:
	docker build -f Dockerfile.analytics -t alpha-analytics:dev .

analytics-migrate:
	docker compose run --rm analytics-migrate

chart:         ## проверить Helm-чарт (нужен helm)
	helm lint deploy/helm/alpha-hackaton --strict
	helm template alpha deploy/helm/alpha-hackaton --namespace alpha > /dev/null
