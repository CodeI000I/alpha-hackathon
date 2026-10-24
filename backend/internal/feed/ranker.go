// Package feed решает, какие новости попадают в ленту пользователя и с каким инсайтом.
// Решение принимает AI-оркестратор (internal/orchestrator); пока он не подключён, работает KeywordRanker.
package feed

import (
	"context"
	"strings"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

// Match — решение оркестратора: новость важна для роли пользователя.
type Match struct {
	Role     string   `json:"role"`
	Kind     string   `json:"kind"` // event | risk | opportunity
	Score    float32  `json:"score"`
	Insight  string   `json:"insight"`
	Elements []string `json:"elements"`
}

// Request — контекст, который оркестратор получает при оценке одной новости.
// Roles — объединение ролей всех директоров компании: одна оценка на пару (новость, компания).
type Request struct {
	News    News           `json:"news"`
	Roles   []string       `json:"roles"`
	Company domain.Company `json:"company"`
}

// News — новость в том виде, в каком её видит оркестратор. В отличие от domain.NewsItem,
// который уходит во фронтенд, здесь есть полный текст (body).
type News struct {
	ID          int64     `json:"id"`
	Revision    int64     `json:"revision"`
	SourceID    string    `json:"sourceId"`
	URL         string    `json:"url"`
	Title       string    `json:"title"`
	Summary     string    `json:"summary"`
	Body        string    `json:"body"`
	PublishedAt time.Time `json:"publishedAt"`
}

// Лимиты полей совпадают с моделью News оркестратора: длиннее он отвечает 422.
const (
	MaxTitle   = 1000
	MaxSummary = 30000
	MaxBody    = 100000
)

func NewsFrom(n domain.NewsItem) News {
	return News{ID: n.ID, SourceID: n.SourceID, URL: n.URL, Title: n.Title, Summary: n.Summary, Body: n.Body, PublishedAt: n.PublishedAt}
}

type Ranker interface {
	Rank(ctx context.Context, req Request) ([]Match, error)
}

// Error — отказ ранжирования с подсказкой, когда повторять. Ошибки другого типа
// (сеть, таймаут) воркер повторяет с экспоненциальной задержкой.
type Error struct {
	Permanent  bool          // повтор не поможет: оркестратор отверг входные данные
	RetryAfter time.Duration // > 0 — сервис просит не обращаться к нему раньше (лимит или бюджет LLM)
	Err        error
}

func (e *Error) Error() string { return e.Err.Error() }
func (e *Error) Unwrap() error { return e.Err }

// KeywordRanker — заглушка, пока оркестратор не подключён: новость попадает в ленту,
// если в ней упоминается название компании или её ИНН.
type KeywordRanker struct{}

func (KeywordRanker) Rank(_ context.Context, req Request) ([]Match, error) {
	text := strings.ToLower(req.News.Title + " " + req.News.Summary + " " + req.News.Body)
	name := strings.ToLower(req.Company.Name)
	if (name == "" || !strings.Contains(text, name)) && (req.Company.INN == "" || !strings.Contains(text, req.Company.INN)) {
		return nil, nil
	}
	out := make([]Match, 0, len(req.Roles))
	for _, role := range req.Roles {
		out = append(out, Match{Role: role, Kind: "event", Score: 0.5, Elements: []string{"Б12"}})
	}
	return out, nil
}
