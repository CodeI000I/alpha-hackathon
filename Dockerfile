# Один образ: Go-сервер (API + статика фронтенда) и воркер сбора новостей.

FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM golang:1.27.3-alpine AS backend
WORKDIR /src
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server \
 && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/worker ./cmd/worker \
 && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/set-password ./cmd/set-password

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=backend /out/server /out/worker /out/set-password /app/
COPY --from=frontend /src/dist /app/static
ENV HTTP_ADDR=:8080 STATIC_DIR=/app/static
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/app/server"]
