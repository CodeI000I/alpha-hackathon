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
	"strings"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func New(baseURL string) *Client {
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), HTTP: &http.Client{Timeout: 60 * time.Second}}
}

// Rank — оценка одной новости для компании и ролей: POST {ORCHESTRATOR_URL}/rank,
// JSON feed.Request → JSON []feed.Match. Пустой массив, если новость не важна.
// Реализует feed.Ranker.
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
	resp, err := c.HTTP.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("orchestrator %s: %s: %s", path, resp.Status, strings.TrimSpace(string(msg)))
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
