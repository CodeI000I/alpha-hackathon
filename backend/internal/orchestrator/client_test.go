package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

func TestRank(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/rank" {
			t.Errorf("got %s %s", r.Method, r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer secret" {
			t.Errorf("Authorization = %q", got)
		}
		var req map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatal(err)
		}
		// Полный текст новости нужен оркестратору, хотя во фронтенд он не уходит.
		var news feed.News
		json.Unmarshal(req["news"], &news)
		if !strings.Contains(string(req["news"]), `"body":"Полный текст"`) {
			t.Errorf("news without body: %s", req["news"])
		}
		json.NewEncoder(w).Encode([]feed.Match{{Role: "procurement", Kind: "risk", Score: 0.9, Insight: news.Title}})
	}))
	defer srv.Close()

	got, err := New(srv.URL+"/", "secret", time.Minute).Rank(context.Background(), feed.Request{
		News:  feed.News{Title: "Санкции против поставщика", Body: "Полный текст"},
		Roles: []string{"procurement"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Role != "procurement" || got[0].Kind != "risk" || got[0].Insight != "Санкции против поставщика" {
		t.Fatalf("unexpected matches: %+v", got)
	}
}

func TestRankErrors(t *testing.T) {
	for _, tc := range []struct {
		status     int
		retryAfter string
		permanent  bool
		wait       time.Duration
	}{
		{http.StatusTooManyRequests, "3600", false, time.Hour},
		{http.StatusServiceUnavailable, "", false, 0},
		{http.StatusUnauthorized, "", false, 0},
		{http.StatusUnprocessableEntity, "", true, 0},
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if tc.retryAfter != "" {
				w.Header().Set("Retry-After", tc.retryAfter)
			}
			http.Error(w, `{"error":{"code":"budget_exceeded"}}`, tc.status)
		}))
		_, err := New(srv.URL, "", time.Minute).Rank(context.Background(), feed.Request{})
		srv.Close()

		var fe *feed.Error
		if !errors.As(err, &fe) {
			t.Fatalf("%d: want *feed.Error, got %v", tc.status, err)
		}
		if fe.Permanent != tc.permanent || fe.RetryAfter != tc.wait || !strings.Contains(err.Error(), "budget_exceeded") {
			t.Errorf("%d: got permanent=%v retryAfter=%v err=%v", tc.status, fe.Permanent, fe.RetryAfter, err)
		}
	}
}

func TestRetryAfterDate(t *testing.T) {
	now := time.Date(2026, 10, 22, 12, 0, 0, 0, time.UTC)
	if got := retryAfter("Thu, 22 Oct 2026 12:30:00 GMT", now); got != 30*time.Minute {
		t.Fatalf("got %v", got)
	}
	if got := retryAfter("soon", now); got != 0 {
		t.Fatalf("got %v", got)
	}
}

func TestRankDoesNotFollowRedirectWithServiceToken(t *testing.T) {
	redirectTargetCalled := false
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirectTargetCalled = true
		if r.Header.Get("Authorization") != "" {
			t.Error("service token leaked across redirect")
		}
	}))
	defer target.Close()
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL+"/rank", http.StatusTemporaryRedirect)
	}))
	defer origin.Close()
	_, err := New(origin.URL, "secret", time.Minute).Rank(context.Background(), feed.Request{})
	if err == nil {
		t.Fatal("redirect response was accepted")
	}
	if redirectTargetCalled {
		t.Fatal("rank client followed redirect")
	}
}
