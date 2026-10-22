package httpapi

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

// Служебные маршруты /api/v1/internal/... — не для фронтенда: для демо и ручной загрузки данных.
// Доступны только с заголовком Authorization: Bearer INTERNAL_API_TOKEN; без токена в конфиге выключены.

const maxImport = 100

type newsImport struct {
	SourceID    string     `json:"sourceId"`
	ExternalID  string     `json:"externalId"`
	URL         string     `json:"url"`
	Title       string     `json:"title"`
	Summary     string     `json:"summary"`
	Body        string     `json:"body"`
	PublishedAt *time.Time `json:"publishedAt"`
}

// internalOnly пропускает запрос с правильным служебным токеном.
func (s *Server) internalOnly(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.InternalToken == "" {
			writeJSON(w, http.StatusNotFound, apiError{"Метод API не найден"})
			return
		}
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+s.InternalToken)) != 1 {
			writeJSON(w, http.StatusUnauthorized, apiError{"Нужен служебный токен"})
			return
		}
		next(w, r)
	}
}

// importNews сохраняет новости так же, как сборщик источников. Воркер оценивает их
// оркестратором сразу после импорта и раскладывает по лентам.
func (s *Server) importNews(w http.ResponseWriter, r *http.Request) {
	var in []newsImport
	r.Body = http.MaxBytesReader(w, r.Body, 16<<20)
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || len(in) == 0 || len(in) > maxImport {
		badRequest(w, fmt.Sprintf("Ожидается JSON-массив из 1–%d новостей с полями title, summary, body, url, publishedAt", maxImport))
		return
	}
	items := make([]domain.NewsItem, len(in))
	for i, n := range in {
		n.Title = strings.TrimSpace(n.Title)
		switch {
		case n.Title == "" || utf8.RuneCountInString(n.Title) > feed.MaxTitle:
			badRequest(w, fmt.Sprintf("Новость %d: укажите title не длиннее %d символов", i+1, feed.MaxTitle))
			return
		case utf8.RuneCountInString(n.Summary) > feed.MaxSummary || utf8.RuneCountInString(n.Body) > feed.MaxBody:
			badRequest(w, fmt.Sprintf("Новость %d: summary до %d символов, body до %d", i+1, feed.MaxSummary, feed.MaxBody))
			return
		}
		item := domain.NewsItem{SourceID: n.SourceID, ExternalID: n.ExternalID, URL: n.URL, Title: n.Title,
			Summary: n.Summary, Body: n.Body, PublishedAt: time.Now()}
		if item.SourceID == "" {
			item.SourceID = "manual"
		}
		if item.ExternalID == "" {
			item.ExternalID = item.URL
		}
		if item.ExternalID == "" { // повторный импорт того же текста не создаёт дубликат
			sum := sha256.Sum256([]byte(item.Title + "\n" + item.Summary + "\n" + item.Body))
			item.ExternalID = "sha256:" + hex.EncodeToString(sum[:16])
		}
		if n.PublishedAt != nil {
			item.PublishedAt = *n.PublishedAt
		}
		items[i] = item
	}
	res, err := s.Store.ImportNews(r.Context(), items)
	if err != nil {
		s.fail(w, err, "Источник не найден")
		return
	}
	writeJSON(w, http.StatusOK, res)
}
