package orchestrator

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

func TestRank(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/rank" {
			t.Errorf("got %s %s", r.Method, r.URL.Path)
		}
		var req feed.Request
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatal(err)
		}
		json.NewEncoder(w).Encode([]feed.Match{{Role: req.Roles[0], Kind: "risk", Score: 0.9, Insight: req.News.Title}})
	}))
	defer srv.Close()

	got, err := New(srv.URL+"/").Rank(context.Background(), feed.Request{
		News:  domain.NewsItem{Title: "Санкции против поставщика"},
		Roles: []string{"procurement"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Role != "procurement" || got[0].Kind != "risk" || got[0].Insight != "Санкции против поставщика" {
		t.Fatalf("unexpected matches: %+v", got)
	}
}

func TestRankError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "Budget has been exceeded", http.StatusTooManyRequests)
	}))
	defer srv.Close()

	_, err := New(srv.URL).Rank(context.Background(), feed.Request{})
	if err == nil || !strings.Contains(err.Error(), "Budget has been exceeded") {
		t.Fatalf("want error with response body, got %v", err)
	}
}
