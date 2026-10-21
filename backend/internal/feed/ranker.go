// Package feed решает, какие новости попадают в ленту пользователя и с каким инсайтом.
// Решение принимает AI-оркестратор (internal/orchestrator); пока он не подключён, работает KeywordRanker.
package feed

import (
	"context"
	"strings"

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
type Request struct {
	News    domain.NewsItem `json:"news"`
	Roles   []string        `json:"roles"`
	Company domain.Company  `json:"company"`
}

type Ranker interface {
	Rank(ctx context.Context, req Request) ([]Match, error)
}

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
