// Package orchestrator — HTTP-клиент к AI-оркестратору (Python + LangGraph, каталог orchestrator/).
// Оркестратор — единственный компонент, который вызывает LLM; Go к моделям не ходит.
package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

type Client struct {
	BaseURL string
	Token   string // AI_SERVICE_TOKEN оркестратора; без него он отвечает 401
	HTTP    *http.Client
}

// New — клиент с таймаутом на один запрос. /rank синхронный: на каждую важную для роли
// новость оркестратор делает два вызова LLM, поэтому таймаут — минуты, а не секунды.
func New(baseURL, token string, timeout time.Duration) *Client {
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, HTTP: &http.Client{Timeout: timeout}}
}

// Rank — оценка одной новости для компании и ролей: POST {ORCHESTRATOR_URL}/rank,
// JSON feed.Request → JSON []feed.Match. Пустой массив, если новость не важна.
// Реализует feed.Ranker. Отказы оркестратора возвращаются как *feed.Error.
func (c *Client) Rank(ctx context.Context, req feed.Request) ([]feed.Match, error) {
	var out []feed.Match
	return out, c.post(ctx, "/rank", req, &out)
}

func (c *Client) post(ctx context.Context, path string, in, out any) error {
	body, err := json.Marshal(in)
	if err != nil {
		return err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if c.Token != "" {
		httpReq.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.HTTP.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return &feed.Error{
			// 400/422: оркестратор отверг сам запрос (пустой заголовок, слишком длинный текст и т.п.).
			Permanent:  resp.StatusCode == http.StatusBadRequest || resp.StatusCode == http.StatusUnprocessableEntity,
			RetryAfter: retryAfter(resp.Header.Get("Retry-After"), time.Now()),
			Err:        fmt.Errorf("orchestrator %s: %s: %s", path, resp.Status, strings.TrimSpace(string(msg))),
		}
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// retryAfter разбирает заголовок Retry-After: число секунд или HTTP-дата. 0 — заголовка нет.
func retryAfter(v string, now time.Time) time.Duration {
	if v == "" {
		return 0
	}
	if s, err := strconv.Atoi(v); err == nil && s > 0 {
		return time.Duration(s) * time.Second
	}
	if t, err := http.ParseTime(v); err == nil && t.After(now) {
		return t.Sub(now)
	}
	return 0
}
