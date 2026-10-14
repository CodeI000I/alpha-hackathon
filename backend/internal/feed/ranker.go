// Package feed решает, какие новости попадают в ленту пользователя и с каким инсайтом.
// Решение принимает Jev (TypeSafe AI); пока он не подключён, работает KeywordRanker.
package feed

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

// Match — решение Jev: новость важна для роли пользователя.
type Match struct {
	Role     string   `json:"role"`
	Kind     string   `json:"kind"` // event | risk | opportunity
	Score    float32  `json:"score"`
	Insight  string   `json:"insight"`
	Elements []string `json:"elements"`
}

// Request — контекст, который Jev получает при оценке одной новости.
type Request struct {
	News    domain.NewsItem `json:"news"`
	Roles   []string        `json:"roles"`
	Company domain.Company  `json:"company"`
}

type Ranker interface {
	Rank(ctx context.Context, req Request) ([]Match, error)
}

// JevRanker вызывает Jev: POST {JEV_URL}/rank, JSON Request → JSON []Match.
// Это наш внутренний контракт: если API Jev устроен иначе, перевод запроса и ответа
// делается здесь (или в тонком сервисе-адаптере рядом с Jev), остальной код не меняется.
type JevRanker struct {
	URL    string
	Client *http.Client
}

func NewJevRanker(url string) *JevRanker {
	return &JevRanker{URL: strings.TrimRight(url, "/"), Client: &http.Client{Timeout: 30 * time.Second}}
}

func (r *JevRanker) Rank(ctx context.Context, req Request) ([]Match, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, r.URL+"/rank", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := r.Client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("jev: %s", resp.Status)
	}
	var out []Match
	return out, json.NewDecoder(resp.Body).Decode(&out)
}

// KeywordRanker — заглушка, пока Jev не подключён: новость попадает в ленту,
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
