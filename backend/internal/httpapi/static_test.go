package httpapi

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// newStaticTestHandler собирает каталог как после `vite build`: две HTML-точки входа и общие assets.
func newStaticTestHandler(t *testing.T) http.Handler {
	t.Helper()
	dir := t.TempDir()
	for name, body := range map[string]string{
		"index.html":                 "<title>Сигнал</title>",
		"bank.html":                  "<title>Альфа-Бизнес</title>",
		"report-charts.html":         "<title>Графики</title>",
		"assets/app-abc123.js":       "console.log('signal')",
		"assets/bank-def456.css":     "body{}",
		"report-charts/catalog.json": "{}",
	} {
		file := filepath.Join(dir, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(file, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	s := &Server{StaticDir: dir, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	return s.Handler()
}

func getStatic(h http.Handler, target string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, target, nil))
	return rec
}

func TestStaticServesEveryEntryPointAsBuilt(t *testing.T) {
	h := newStaticTestHandler(t)
	for _, tc := range []struct{ path, want string }{
		{"/bank.html", "<title>Альфа-Бизнес</title>"},
		{"/report-charts.html", "<title>Графики</title>"},
		{"/assets/app-abc123.js", "console.log('signal')"},
		{"/assets/bank-def456.css", "body{}"},
		{"/report-charts/catalog.json", "{}"},
	} {
		rec := getStatic(h, tc.path)
		if rec.Code != http.StatusOK || rec.Body.String() != tc.want {
			t.Errorf("%s: %d %q, want 200 %q", tc.path, rec.Code, rec.Body.String(), tc.want)
		}
	}
}

func TestStaticClientRoutesGetSignalIndex(t *testing.T) {
	h := newStaticTestHandler(t)
	for _, p := range []string{"/", "/register", "/login", "/dashboard", "/news/101", "/issues/issue_ab12", "/profile?tab=roles"} {
		rec := getStatic(h, p)
		if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "Сигнал") {
			t.Errorf("%s: %d %q, want index.html", p, rec.Code, rec.Body.String())
		}
		if got := rec.Header().Get("Cache-Control"); got != "no-cache" {
			t.Errorf("%s: Cache-Control = %q, want no-cache", p, got)
		}
	}
}

func TestStaticHTMLIsRevalidatedAfterDeploy(t *testing.T) {
	h := newStaticTestHandler(t)
	for _, p := range []string{"/bank.html", "/report-charts.html"} {
		if got := getStatic(h, p).Header().Get("Cache-Control"); got != "no-cache" {
			t.Errorf("%s: Cache-Control = %q, want no-cache", p, got)
		}
	}
	if got := getStatic(h, "/assets/app-abc123.js").Header().Get("Cache-Control"); got != "" {
		t.Errorf("hashed asset: Cache-Control = %q, want default caching", got)
	}
}

// Отсутствующий файл не подменяется index.html: иначе /bank.html из неполной сборки
// или старый чанк после деплоя открылись бы как «Сигнал» со статусом 200.
func TestStaticMissingFilesAreNotReplacedWithIndex(t *testing.T) {
	h := newStaticTestHandler(t)
	for _, p := range []string{"/missing.html", "/assets/app-old999.js", "/assets/chunk", "/favicon.ico", "/report-charts/missing.json"} {
		rec := getStatic(h, p)
		if rec.Code != http.StatusNotFound || strings.Contains(rec.Body.String(), "Сигнал") {
			t.Errorf("%s: %d %q, want plain 404", p, rec.Code, rec.Body.String())
		}
	}
}

func TestStaticBankShortcutRedirectsToBankPage(t *testing.T) {
	h := newStaticTestHandler(t)
	for p, want := range map[string]string{"/bank": "/bank.html", "/bank/": "/bank.html", "/bank?from=demo": "/bank.html?from=demo"} {
		rec := getStatic(h, p)
		if rec.Code != http.StatusFound || rec.Header().Get("Location") != want {
			t.Errorf("%s: %d Location=%q, want 302 %q", p, rec.Code, rec.Header().Get("Location"), want)
		}
	}
}
