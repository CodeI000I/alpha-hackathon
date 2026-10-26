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
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// FileStore — объектное хранилище файлов компаний (реализация — files.Store).
type FileStore interface {
	Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error
}

type Server struct {
	Store            *postgres.Store
	Files            FileStore // nil, если объектное хранилище не настроено
	StaticDir        string
	InternalToken    string // токен служебных маршрутов; пусто = выключены
	RequireAuth      bool
	CookieSecure     bool
	AnalyticsURL     string
	AnalyticsToken   string
	Log              *slog.Logger
	loginLimiterOnce sync.Once
	loginLimiter     *loginLimiterState
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("GET /readyz", s.ready)

	mux.HandleFunc("GET /api/v1/roles", s.listRoles)
	mux.HandleFunc("GET /api/v1/profile-elements", s.listProfileElements)

	mux.Handle("POST /api/v1/auth/login", http.HandlerFunc(s.login))
	mux.Handle("GET /api/v1/auth/me", s.requireAuth(http.HandlerFunc(s.me)))
	mux.Handle("POST /api/v1/auth/logout", s.requireAuth(http.HandlerFunc(s.logout)))
	mux.Handle("POST /api/v1/users", s.guard(http.HandlerFunc(s.createUser)))
	mux.HandleFunc("POST /api/v1/onboarding", s.createOnboarding)
	mux.Handle("GET /api/v1/users/{id}", s.guard(http.HandlerFunc(s.getUser)))
	mux.Handle("PUT /api/v1/users/{id}/roles", s.guard(http.HandlerFunc(s.setUserRoles)))
	mux.Handle("GET /api/v1/users/{id}/feed", s.guard(http.HandlerFunc(s.getFeed)))

	mux.Handle("POST /api/v1/companies", s.guard(http.HandlerFunc(s.createCompany)))
	mux.Handle("GET /api/v1/companies/{id}", s.guard(http.HandlerFunc(s.getCompany)))
	mux.Handle("PATCH /api/v1/companies/{id}/profile", s.guard(http.HandlerFunc(s.patchProfile)))
	mux.Handle("GET /api/v1/companies/{id}/files", s.guard(http.HandlerFunc(s.listFiles)))
	mux.Handle("POST /api/v1/companies/{id}/files", s.guard(http.HandlerFunc(s.uploadFile)))
	mux.Handle("GET /api/v1/analytics/{rest...}", s.requireAuth(http.HandlerFunc(s.analyticsProxy)))
	mux.Handle("POST /api/v1/analytics/{rest...}", s.requireAuth(http.HandlerFunc(s.analyticsProxy)))
	mux.Handle("PATCH /api/v1/analytics/{rest...}", s.requireAuth(http.HandlerFunc(s.analyticsProxy)))

	mux.HandleFunc("POST /api/v1/internal/news", s.internalOnly(s.importNews))
	mux.HandleFunc("GET /api/v1/internal/files/{id}/content", s.internalOnly(s.fileContent))

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

// spa отдаёт всю сборку фронтенда (dist) как есть: index.html — «Сигнал», bank.html — демо-кабинет
// Альфа-Бизнеса, assets/ — ресурсы обоих. Пути клиентского роутинга «Сигнала» (/register,
// /dashboard, …) получают index.html. Отсутствующий файл — путь с расширением или внутри
// /assets/ — получает 404: иначе потерянный bank.html или старый чанк после деплоя молча
// подменился бы страницей «Сигнала».
func spa(dir string) http.Handler {
	fileServer := http.FileServer(http.Dir(dir))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		urlPath := path.Clean("/" + r.URL.Path)
		if urlPath == "/bank" {
			target := "/bank.html"
			if r.URL.RawQuery != "" {
				target += "?" + r.URL.RawQuery
			}
			http.Redirect(w, r, target, http.StatusFound)
			return
		}
		if st, err := os.Stat(filepath.Join(dir, filepath.FromSlash(urlPath))); err == nil && !st.IsDir() {
			// HTML ссылается на ресурсы с хешем в имени: без перепроверки браузер после деплоя
			// открыл бы старую страницу, чьих ресурсов уже нет.
			if path.Ext(urlPath) == ".html" {
				w.Header().Set("Cache-Control", "no-cache")
			}
			fileServer.ServeHTTP(w, r)
			return
		}
		if strings.HasPrefix(urlPath, "/assets/") || path.Ext(urlPath) != "" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Cache-Control", "no-cache")
		http.ServeFile(w, r, filepath.Join(dir, "index.html"))
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
	default:
		s.Log.Error("request failed", "err", err)
		writeJSON(w, http.StatusInternalServerError, apiError{"Внутренняя ошибка сервера"})
	}
}

// refreshFeed будит воркер: директор получит уже готовые карточки по своим ролям сразу,
// а не через INGEST_PERIOD. Ошибка не мешает ответу — карточки появятся на следующем проходе.
func (s *Server) refreshFeed(r *http.Request) {
	if err := s.Store.RequestFeedRefresh(r.Context()); err != nil {
		s.Log.Warn("request feed refresh", "err", err)
	}
}

func badRequest(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusBadRequest, apiError{msg})
}

func pathID(r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	return id, err == nil && id > 0
}
