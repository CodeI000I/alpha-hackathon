// Package orchestrator — HTTP-клиент к AI-оркестратору (Python + LangGraph, каталог orchestrator/).
// Оркестратор — единственный компонент, который вызывает LLM; Go к моделям не ходит.
package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
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
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, HTTP: &http.Client{
		Timeout:       timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}}
}

// Rank — оценка одной новости для компании и ролей: POST {ORCHESTRATOR_URL}/rank,
// JSON feed.Request → JSON []feed.Match. Пустой массив, если новость не важна.
// Реализует feed.Ranker. Отказы оркестратора возвращаются как *feed.Error.
func (c *Client) Rank(ctx context.Context, req feed.Request) ([]feed.Match, error) {
	var out []feed.Match
	if err := c.post(ctx, "/rank", req, &out); err != nil {
		return nil, err
	}
	if err := validateMatches(req.Roles, out); err != nil {
		return nil, err
	}
	return out, nil
}

const maxResponseBytes = 1 << 20

func validateMatches(roles []string, matches []feed.Match) error {
	allowed := make(map[string]struct{}, len(roles))
	for _, role := range roles {
		allowed[role] = struct{}{}
	}
	seen := make(map[string]struct{}, len(matches))
	for _, match := range matches {
		if _, ok := allowed[match.Role]; !ok {
			return fmt.Errorf("orchestrator: response contains an unrequested role")
		}
		if _, ok := seen[match.Role]; ok {
			return fmt.Errorf("orchestrator: response contains duplicate roles")
		}
		seen[match.Role] = struct{}{}
		switch match.Kind {
		case "event", "risk", "opportunity":
		default:
			return fmt.Errorf("orchestrator: response contains an unsupported kind")
		}
		if math.IsNaN(float64(match.Score)) || math.IsInf(float64(match.Score), 0) || match.Score < 0 || match.Score > 1 {
			return fmt.Errorf("orchestrator: response contains an invalid score")
		}
	}
	return nil
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
	body, err = io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return fmt.Errorf("orchestrator %s: read response: %w", path, err)
	}
	if len(body) > maxResponseBytes {
		return fmt.Errorf("orchestrator %s: response exceeds %d bytes", path, maxResponseBytes)
	}
	if len(strings.TrimSpace(string(body))) == 0 || strings.TrimSpace(string(body))[0] != '[' {
		return fmt.Errorf("orchestrator %s: expected JSON array", path)
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("orchestrator %s: invalid response JSON: %w", path, err)
	}
	return nil
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
