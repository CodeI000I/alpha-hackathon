-include .env
export

.PHONY: deps up down server worker web build seed image chart

up:            ## поднять Postgres и RustFS (S3)
	docker compose up -d

down:
	docker compose down

server:        ## API на :8080 (миграции применяются при старте)
	cd backend && go run ./cmd/server

worker:        ## сбор новостей и построение лент
	cd backend && go run ./cmd/worker

web:           ## фронтенд на :5173, /api проксируется на :8080
	cd frontend && npm install && npm run dev

build:
	cd backend && go build ./... && go vet ./...
	cd frontend && npm ci && npm run build

seed:          ## пересобрать справочники из company_research.xlsx
	python3 scripts/gen_seed.py company_research.xlsx > backend/migrations/0002_seed.sql

image:
	docker build -t alpha-hackaton:dev .

chart:         ## проверить Helm-чарт (нужен helm)
	helm lint deploy/helm/alpha-hackaton --strict
	helm template alpha deploy/helm/alpha-hackaton --namespace alpha > /dev/null
