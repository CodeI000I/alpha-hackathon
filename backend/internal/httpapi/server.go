// Package httpapi — JSON API для фронтенда и раздача собранного фронтенда.
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// FileStore — объектное хранилище файлов компаний (реализация — files.Store).
type FileStore interface {
	Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error
}

type Server struct {
	Store     *postgres.Store
	Files     FileStore // nil, если объектное хранилище не настроено
	StaticDir string
	Log       *slog.Logger
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("GET /readyz", s.ready)

	mux.HandleFunc("GET /api/v1/roles", s.listRoles)
	mux.HandleFunc("GET /api/v1/profile-elements", s.listProfileElements)

	mux.HandleFunc("POST /api/v1/users", s.createUser)
	mux.HandleFunc("GET /api/v1/users/{id}", s.getUser)
	mux.HandleFunc("PUT /api/v1/users/{id}/roles", s.setUserRoles)
	mux.HandleFunc("GET /api/v1/users/{id}/feed", s.getFeed)

	mux.HandleFunc("POST /api/v1/companies", s.createCompany)
	mux.HandleFunc("GET /api/v1/companies/{id}", s.getCompany)
	mux.HandleFunc("PATCH /api/v1/companies/{id}/profile", s.patchProfile)
	mux.HandleFunc("GET /api/v1/companies/{id}/files", s.listFiles)
	mux.HandleFunc("POST /api/v1/companies/{id}/files", s.uploadFile)

	// Неизвестный метод API — JSON 404, а не index.html со статусом 200 из SPA.
	mux.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusNotFound, apiError{"Метод API не найден"})
	})

	if s.StaticDir != "" {
		mux.Handle("/", spa(s.StaticDir))
	}
	return s.logging(mux)
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	if err := s.Store.Ping(r.Context()); err != nil {
		http.Error(w, "db not ready", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
}

// spa отдаёт статику фронтенда, а неизвестные пути — index.html (клиентский роутинг).
func spa(dir string) http.Handler {
	fileServer := http.FileServer(http.Dir(dir))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := filepath.Join(dir, filepath.Clean("/"+r.URL.Path))
		if st, err := os.Stat(path); err != nil || st.IsDir() {
			http.ServeFile(w, r, filepath.Join(dir, "index.html"))
			return
		}
		fileServer.ServeHTTP(w, r)
	})
}

func (s *Server) logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		if r.URL.Path != "/healthz" && r.URL.Path != "/readyz" {
			s.Log.Info("http", "method", r.Method, "path", r.URL.Path, "dur", time.Since(start))
		}
	})
}

type apiError struct {
	Error string `json:"error"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// Тексты ошибок фронтенд показывает пользователю как есть, поэтому они на русском.
const (
	msgBadID           = "Некорректный идентификатор"
	msgUserNotFound    = "Пользователь не найден"
	msgCompanyNotFound = "Компания не найдена"
)

// fail переводит ошибку хранилища в HTTP-ответ; notFound — текст для 404.
func (s *Server) fail(w http.ResponseWriter, err error, notFound string) {
	switch {
	case errors.Is(err, postgres.ErrNotFound):
		writeJSON(w, http.StatusNotFound, apiError{notFound})
	case errors.Is(err, postgres.ErrEmailTaken):
		writeJSON(w, http.StatusConflict, apiError{"Пользователь с такой электронной почтой уже зарегистрирован"})
	case errors.Is(err, postgres.ErrINNTaken):
		writeJSON(w, http.StatusConflict, apiError{"Компания с таким ИНН уже зарегистрирована"})
	default:
		s.Log.Error("request failed", "err", err)
		writeJSON(w, http.StatusInternalServerError, apiError{"Внутренняя ошибка сервера"})
	}
}

func badRequest(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusBadRequest, apiError{msg})
}

func pathID(r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	return id, err == nil && id > 0
}
