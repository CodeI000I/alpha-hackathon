package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
)

const onboardingTestDatabase = "alpha_test"

type onboardingResponse struct {
	Company domain.Company `json:"company"`
	User    domain.User    `json:"user"`
}

func newOnboardingTestServer(t *testing.T) (*httptest.Server, *postgres.Store, string) {
	t.Helper()
	dsn := os.Getenv("ALPHA_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set ALPHA_TEST_DATABASE_URL to a disposable loopback PostgreSQL database")
	}
	config, err := pgx.ParseConfig(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if config.Database != onboardingTestDatabase || !isLoopbackPGHost(config.Host) {
		t.Fatalf("ALPHA_TEST_DATABASE_URL must target loopback database %q", onboardingTestDatabase)
	}
	for _, fallback := range config.Fallbacks {
		if fallback == nil || !isLoopbackPGHost(fallback.Host) {
			t.Fatalf("ALPHA_TEST_DATABASE_URL may only contain loopback fallback hosts")
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	store, err := postgres.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	if err := store.Migrate(ctx, migrations.FS); err != nil {
		t.Fatal(err)
	}
	server := &Server{Store: store, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)
	return httpServer, store, dsn
}

func isLoopbackPGHost(host string) bool {
	return host == "localhost" || host == "127.0.0.1" || host == "::1"
}

func postOnboarding(t *testing.T, serverURL, key string, body any) *http.Response {
	t.Helper()
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, serverURL+"/api/v1/onboarding", bytes.NewReader(encoded))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", key)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { resp.Body.Close() })
	return resp
}

func decodeOnboarding(t *testing.T, resp *http.Response) onboardingResponse {
	t.Helper()
	var result onboardingResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	return result
}

func onboardingBody(suffix string) map[string]any {
	value, _ := strconv.ParseInt(suffix, 36, 64)
	return map[string]any{
		"company": map[string]any{"inn": fmt.Sprintf("%012d", value%1_000_000_000_000), "name": "Company " + suffix},
		"user":    map[string]any{"email": suffix + "@example.test", "fullName": "Test User", "roles": []string{"sales", "procurement"}},
	}
}

func onboardingSuffix() string {
	return strconv.FormatInt(time.Now().UnixNano(), 36)
}

func TestOnboardingReplayIsIdempotentAndRoleOrderIsCanonical(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	key := "onboarding-" + suffix
	body := onboardingBody(suffix)
	first := postOnboarding(t, server.URL, key, body)
	if first.StatusCode != http.StatusCreated {
		t.Fatalf("first response status = %d, want %d", first.StatusCode, http.StatusCreated)
	}
	created := decodeOnboarding(t, first)
	if created.Company.ID == 0 || created.User.ID == 0 || created.User.CompanyID == nil || *created.User.CompanyID != created.Company.ID {
		t.Fatalf("inconsistent onboarding result: %+v", created)
	}

	user := body["user"].(map[string]any)
	user["roles"] = []string{"procurement", "sales"}
	replay := postOnboarding(t, server.URL, key, body)
	if replay.StatusCode != http.StatusOK {
		t.Fatalf("replay response status = %d, want %d", replay.StatusCode, http.StatusOK)
	}
	replayed := decodeOnboarding(t, replay)
	if replayed.Company.ID != created.Company.ID || replayed.User.ID != created.User.ID {
		t.Fatalf("replay created different records: first=%+v replay=%+v", created, replayed)
	}
}

func TestOnboardingChangedRequestWithSameKeyConflicts(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	key := "onboarding-" + suffix
	body := onboardingBody(suffix)
	first := postOnboarding(t, server.URL, key, body)
	if first.StatusCode != http.StatusCreated {
		t.Fatalf("first response status = %d, want %d", first.StatusCode, http.StatusCreated)
	}
	_ = decodeOnboarding(t, first)

	changed := onboardingBody(suffix)
	changed["company"].(map[string]any)["name"] = "Changed name"
	resp := postOnboarding(t, server.URL, key, changed)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("changed replay response status = %d, want %d", resp.StatusCode, http.StatusConflict)
	}
}

func TestOnboardingUnknownRoleRollsBackCompanyAndUser(t *testing.T) {
	server, _, dsn := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	body := onboardingBody(suffix)
	body["user"].(map[string]any)["roles"] = []string{"does-not-exist"}
	resp := postOnboarding(t, server.URL, "onboarding-"+suffix, body)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("unknown role response status = %d, want %d", resp.StatusCode, http.StatusBadRequest)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	var companies, users int
	inn := body["company"].(map[string]any)["inn"]
	if err := conn.QueryRow(ctx, "SELECT count(*) FROM companies WHERE inn=$1", inn).Scan(&companies); err != nil {
		t.Fatal(err)
	}
	if err := conn.QueryRow(ctx, "SELECT count(*) FROM users WHERE email=$1", suffix+"@example.test").Scan(&users); err != nil {
		t.Fatal(err)
	}
	if companies != 0 || users != 0 {
		t.Fatalf("partial onboarding persisted after role error: companies=%d users=%d", companies, users)
	}
}

func TestOnboardingRejectsMissingRolesWithoutCreatingRecords(t *testing.T) {
	server, _, dsn := newOnboardingTestServer(t)
	for _, testCase := range []struct {
		name  string
		roles any
	}{
		{name: "empty array", roles: []string{}},
		{name: "null", roles: nil},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			suffix := onboardingSuffix()
			body := onboardingBody(suffix)
			body["user"].(map[string]any)["roles"] = testCase.roles
			resp := postOnboarding(t, server.URL, "onboarding-empty-roles-"+suffix, body)
			if resp.StatusCode != http.StatusBadRequest {
				t.Fatalf("empty-role response status = %d, want %d", resp.StatusCode, http.StatusBadRequest)
			}

			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			conn, err := pgx.Connect(ctx, dsn)
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close(ctx)
			var companies, users int
			inn := body["company"].(map[string]any)["inn"]
			if err := conn.QueryRow(ctx, "SELECT count(*) FROM companies WHERE inn=$1", inn).Scan(&companies); err != nil {
				t.Fatal(err)
			}
			email := body["user"].(map[string]any)["email"]
			if err := conn.QueryRow(ctx, "SELECT count(*) FROM users WHERE email=$1", email).Scan(&users); err != nil {
				t.Fatal(err)
			}
			if companies != 0 || users != 0 {
				t.Fatalf("empty-role onboarding created records: companies=%d users=%d", companies, users)
			}
		})
	}
}

func TestOnboardingExistingCompanyReturnsConflictWithoutPartialUser(t *testing.T) {
	server, _, dsn := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	firstBody := onboardingBody(suffix)
	first := postOnboarding(t, server.URL, "onboarding-first-"+suffix, firstBody)
	if first.StatusCode != http.StatusCreated {
		t.Fatalf("first response status = %d, want %d", first.StatusCode, http.StatusCreated)
	}
	_ = decodeOnboarding(t, first)

	secondBody := onboardingBody(suffix + "-second")
	secondBody["company"].(map[string]any)["inn"] = firstBody["company"].(map[string]any)["inn"]
	resp := postOnboarding(t, server.URL, "onboarding-second-"+suffix, secondBody)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("existing-company response status = %d, want %d", resp.StatusCode, http.StatusConflict)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	var companies, partialUsers int
	inn := firstBody["company"].(map[string]any)["inn"]
	secondEmail := secondBody["user"].(map[string]any)["email"]
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM companies WHERE inn=$1`, inn).Scan(&companies); err != nil {
		t.Fatal(err)
	}
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM users WHERE email=$1`, secondEmail).Scan(&partialUsers); err != nil {
		t.Fatal(err)
	}
	if companies != 1 || partialUsers != 0 {
		t.Fatalf("failed retry changed business rows: companies=%d partial users=%d", companies, partialUsers)
	}
}

func TestConcurrentOnboardingReplayCreatesOneCompanyAndUser(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	key, body := "onboarding-"+suffix, onboardingBody(suffix)
	var wg sync.WaitGroup
	start := make(chan struct{})
	results := make([]onboardingResponse, 2)
	statuses := make([]int, 2)
	errs := make([]error, 2)
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	for i := range results {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			req, err := http.NewRequest(http.MethodPost, server.URL+"/api/v1/onboarding", bytes.NewReader(encoded))
			if err != nil {
				errs[i] = err
				return
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", key)
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				errs[i] = err
				return
			}
			defer resp.Body.Close()
			statuses[i] = resp.StatusCode
			if statuses[i] == http.StatusCreated || statuses[i] == http.StatusOK {
				errs[i] = json.NewDecoder(resp.Body).Decode(&results[i])
			} else {
				data, _ := io.ReadAll(resp.Body)
				errs[i] = fmt.Errorf("status %d: %s", statuses[i], strings.TrimSpace(string(data)))
			}
		}(i)
	}
	close(start)
	wg.Wait()
	for i, err := range errs {
		if err != nil {
			t.Fatalf("request %d failed: %v", i, err)
		}
	}
	if results[0].Company.ID == 0 || results[0].Company.ID != results[1].Company.ID || results[0].User.ID != results[1].User.ID {
		t.Fatalf("concurrent requests did not converge to one result: %+v", results)
	}
}

func TestOnboardingRejectsInvalidKeyAndOversizedBody(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	body, _ := json.Marshal(onboardingBody(suffix))
	duplicateRoleInput := onboardingBody(suffix + "-duplicate")
	duplicateRoleInput["user"].(map[string]any)["roles"] = []string{"sales", "sales"}
	duplicateRoleBody, _ := json.Marshal(duplicateRoleInput)
	for name, testCase := range map[string]struct {
		key     string
		payload []byte
		status  int
	}{
		"invalid-key":    {key: "bad/key", payload: body, status: http.StatusBadRequest},
		"duplicate-role": {key: "onboarding-" + suffix + "-duplicate", payload: duplicateRoleBody, status: http.StatusBadRequest},
		"oversized-body": {key: "onboarding-" + suffix, payload: []byte(`{"padding":"` + strings.Repeat("x", 70<<10) + `"}`), status: http.StatusRequestEntityTooLarge},
	} {
		t.Run(name, func(t *testing.T) {
			req, err := http.NewRequest(http.MethodPost, server.URL+"/api/v1/onboarding", bytes.NewReader(testCase.payload))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", testCase.key)
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != testCase.status {
				t.Fatalf("response status = %d, want %d", resp.StatusCode, testCase.status)
			}
		})
	}
}
