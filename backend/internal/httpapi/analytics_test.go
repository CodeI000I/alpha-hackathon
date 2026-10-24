package httpapi

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

func TestAnalyticsProxyInjectsTrustedScopeAndPreservesRetryAfter(t *testing.T) {
	var got *http.Request
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Clone(context.Background())
		got.Header = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Retry-After", "7")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, `{"detail":{"code":"busy"}}`)
	}))
	defer upstream.Close()
	companyID := int64(41)
	s := &Server{AnalyticsURL: upstream.URL, AnalyticsToken: "service-secret"}
	u := domain.User{ID: 9, CompanyID: &companyID, Roles: []string{"cfo"}}
	r := httptest.NewRequest(http.MethodGet, "/api/v1/analytics/situation?role=cfo", nil)
	r.SetPathValue("rest", "situation")
	r.Header.Set("Authorization", "Bearer attacker")
	r.Header.Set("X-User-ID", "999")
	r.Header.Set("X-Company-ID", "999")
	r.Header.Set("X-Role", "admin")
	r.Header.Set("X-Tenant-ID", "other")
	r = r.WithContext(context.WithValue(r.Context(), authenticatedUserKey{}, u))
	w := httptest.NewRecorder()
	s.analyticsProxy(w, r)
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") != "7" {
		t.Fatalf("response = %d, retry-after=%q", w.Code, w.Header().Get("Retry-After"))
	}
	if got == nil {
		t.Fatal("upstream was not called")
	}
	for key, want := range map[string]string{"Authorization": "Bearer service-secret", "X-User-Id": "9", "X-Company-Id": "41", "X-Role": "cfo", "X-Tenant-Id": "alpha"} {
		if value := got.Header.Get(key); value != want {
			t.Errorf("%s = %q, want %q", key, value, want)
		}
	}
	if strings.Contains(got.URL.RawQuery, "role=") {
		t.Errorf("untrusted role query reached Python: %s", got.URL.RawQuery)
	}
	if got.URL.Path != "/v1/analytics/situation" {
		t.Errorf("upstream path = %q", got.URL.Path)
	}
}

func TestAnalyticsProxyRejectsUnassignedRoleAndIngestionRoutes(t *testing.T) {
	companyID := int64(41)
	s := &Server{AnalyticsURL: "http://127.0.0.1:1", AnalyticsToken: "secret"}
	for _, tc := range []struct {
		method, target string
		want           int
	}{
		{http.MethodGet, "/api/v1/analytics/situation?role=admin", http.StatusForbidden},
		{http.MethodGet, "/api/v1/analytics/news?role=cfo", http.StatusNotFound},
		{http.MethodGet, "/api/v1/analytics/company?role=cfo", http.StatusNotFound},
		{http.MethodGet, "/api/v1/analytics/documents?role=cfo", http.StatusBadGateway},
		{http.MethodPatch, "/api/v1/analytics/issues/abc/state?role=cfo", http.StatusBadGateway},
	} {
		r := httptest.NewRequest(tc.method, tc.target, nil)
		path := strings.TrimPrefix(strings.Split(tc.target, "?")[0], "/api/v1/analytics/")
		r.SetPathValue("rest", path)
		r = r.WithContext(context.WithValue(r.Context(), authenticatedUserKey{}, domain.User{ID: 9, CompanyID: &companyID, Roles: []string{"cfo"}}))
		w := httptest.NewRecorder()
		s.analyticsProxy(w, r)
		if w.Code != tc.want {
			t.Errorf("%s => %d, want %d", tc.target, w.Code, tc.want)
		}
	}
}

func TestHandlerRegistersAnalyticsPatchRouteBehindAuth(t *testing.T) {
	s := &Server{RequireAuth: true, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	r := httptest.NewRequest(http.MethodPatch, "/api/v1/analytics/issues/issue_abc/state?role=cfo", strings.NewReader(`{"workflow":"closed"}`))
	r.Header.Set("Origin", "http://example.test")
	r.Host = "example.test"
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("PATCH route returned %d, want 401 (registered route behind auth)", w.Code)
	}
}
