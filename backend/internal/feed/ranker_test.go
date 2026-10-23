package feed

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

type roundTripperFunc func(*http.Request) (*http.Response, error)

func (f roundTripperFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func rankWithFixture(body string, roles ...string) ([]Match, error) {
	ranker := NewJevRanker("http://ranker.test")
	ranker.Client = &http.Client{Transport: roundTripperFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header),
			Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	return ranker.Rank(context.Background(), Request{Roles: roles})
}

func TestJevRankerReturnsDecodedMatches(t *testing.T) {
	var gotRequest bool
	ranker := NewJevRanker("http://ranker.test")
	ranker.Client = &http.Client{Transport: roundTripperFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodPost || r.URL.String() != "http://ranker.test/rank" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL)
		}
		gotRequest = true
		var request Request
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil || request.News.Body != "Full source body" {
			t.Errorf("full source body was lost at the rank boundary: %q, %v", request.News.Body, err)
		}
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(
			`[{"role":"procurement","kind":"risk","score":0.8,"insight":"fixture","elements":["Б12"]}]`,
		))}, nil
	})}

	got, err := ranker.Rank(context.Background(), Request{Roles: []string{"procurement"}, News: domain.NewsItem{Body: "Full source body"}})
	if err != nil {
		t.Fatalf("Rank() error = %v", err)
	}
	if !gotRequest {
		t.Fatal("RoundTrip was not called")
	}
	if len(got) != 1 || got[0].Role != "procurement" || got[0].Kind != "risk" || got[0].Score != 0.8 {
		t.Fatalf("Rank() = %#v, want the decoded fixture match", got)
	}
}

func TestJevRankerRejectsInvalidMatches(t *testing.T) {
	cases := []struct {
		name string
		body string
	}{
		{name: "role outside request", body: `[{"role":"admin","kind":"risk","score":0.5}]`},
		{name: "unknown kind", body: `[{"role":"procurement","kind":"prediction","score":0.5}]`},
		{name: "score below range", body: `[{"role":"procurement","kind":"risk","score":-0.1}]`},
		{name: "score above range", body: `[{"role":"procurement","kind":"risk","score":1.01}]`},
		{name: "duplicate role", body: `[{"role":"procurement","kind":"risk","score":0.5},{"role":"procurement","kind":"event","score":0.4}]`},
		{name: "malformed JSON", body: `[{"role":`},
		{name: "trailing JSON", body: `[{"role":"procurement","kind":"risk","score":0.5}] []`},
		{name: "null instead of array", body: `null`},
		{name: "oversized body", body: fmt.Sprintf(`[{"role":"procurement","kind":"risk","score":0.5,"insight":"%s"}]`, strings.Repeat("x", 1<<20))},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got, err := rankWithFixture(tc.body, "procurement"); err == nil {
				t.Fatalf("Rank() = %#v, want validation error", got)
			}
		})
	}
}
