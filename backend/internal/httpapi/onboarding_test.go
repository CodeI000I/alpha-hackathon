package httpapi

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
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
	server := &Server{Store: store, RequireAuth: true, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
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
	req.Header.Set("Origin", serverURL)
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
		"user":    map[string]any{"email": suffix + "@example.test", "fullName": "Test User", "password": "correct-horse-battery", "roles": []string{"sales", "procurement"}},
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
	if first.Header.Get("Set-Cookie") == "" {
		t.Fatal("onboarding did not create an authenticated session cookie")
	}
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

func TestOnboardingSessionLoginAndLogout(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	blockedPayload, _ := json.Marshal(onboardingBody(suffix))
	blockedReq, _ := http.NewRequest(http.MethodPost, server.URL+"/api/v1/onboarding", bytes.NewReader(blockedPayload))
	blockedReq.Header.Set("Content-Type", "application/json")
	blockedReq.Header.Set("Idempotency-Key", "cross-site-"+suffix)
	blockedReq.Header.Set("Origin", "https://attacker.example")
	blocked, err := http.DefaultClient.Do(blockedReq)
	if err != nil {
		t.Fatal(err)
	}
	blocked.Body.Close()
	if blocked.StatusCode != http.StatusForbidden {
		t.Fatalf("cross-site onboarding status = %d, want forbidden", blocked.StatusCode)
	}
	resp := postOnboarding(t, server.URL, "session-"+suffix, onboardingBody(suffix))
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("onboarding status = %d", resp.StatusCode)
	}
	user := decodeOnboarding(t, resp).User
	var cookie *http.Cookie
	for _, c := range resp.Cookies() {
		if c.Name == sessionCookie {
			cookie = c
		}
	}
	if cookie == nil || !cookie.HttpOnly || cookie.SameSite != http.SameSiteStrictMode {
		t.Fatalf("unsafe session cookie: %#v", cookie)
	}
	// Одна cookie на весь сайт: переход /bank.html → /register попадает в ту же сессию.
	if cookie.Path != "/" {
		t.Fatalf("session cookie path = %q, want / so bank.html and Signal share it", cookie.Path)
	}

	payload, _ := json.Marshal(map[string]string{"email": strings.ToUpper(user.Email), "password": "correct-horse-battery"})
	loginReq, _ := http.NewRequest(http.MethodPost, server.URL+"/api/v1/auth/login", bytes.NewReader(payload))
	loginReq.Header.Set("Content-Type", "application/json")
	loginReq.Header.Set("Origin", "https://attacker.example")
	blockedLogin, err := http.DefaultClient.Do(loginReq)
	if err != nil {
		t.Fatal(err)
	}
	blockedLogin.Body.Close()
	if blockedLogin.StatusCode != http.StatusForbidden {
		t.Fatalf("cross-site login status = %d, want forbidden", blockedLogin.StatusCode)
	}
	loginReq, _ = http.NewRequest(http.MethodPost, server.URL+"/api/v1/auth/login", bytes.NewReader(payload))
	loginReq.Header.Set("Content-Type", "application/json")
	loginReq.Header.Set("Origin", server.URL)
	loginResp, err := http.DefaultClient.Do(loginReq)
	if err != nil {
		t.Fatal(err)
	}
	defer loginResp.Body.Close()
	if loginResp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(loginResp.Body)
		t.Fatalf("login status %d: %s", loginResp.StatusCode, b)
	}
	var loginCookie *http.Cookie
	for _, c := range loginResp.Cookies() {
		if c.Name == sessionCookie {
			loginCookie = c
		}
	}
	if loginCookie == nil {
		t.Fatal("login did not set a session cookie")
	}
	protected, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("%s/api/v1/users/%d", server.URL, user.ID), nil)
	protected.AddCookie(loginCookie)
	protectedResp, err := http.DefaultClient.Do(protected)
	if err != nil {
		t.Fatal(err)
	}
	protectedResp.Body.Close()
	if protectedResp.StatusCode != http.StatusOK {
		t.Fatalf("self user endpoint status = %d", protectedResp.StatusCode)
	}
	if user.CompanyID == nil {
		t.Fatal("new user has no company")
	}
	colleagueBody, _ := json.Marshal(map[string]any{"companyId": *user.CompanyID, "email": suffix + "+colleague@example.test", "fullName": "Another User", "password": "another-good-password", "roles": []string{"sales"}})
	colleagueReq, _ := http.NewRequest(http.MethodPost, server.URL+"/api/v1/users", bytes.NewReader(colleagueBody))
	colleagueReq.Header.Set("Content-Type", "application/json")
	colleagueReq.Header.Set("Origin", server.URL)
	colleagueReq.AddCookie(loginCookie)
	colleagueResp, err := http.DefaultClient.Do(colleagueReq)
	if err != nil {
		t.Fatal(err)
	}
	colleagueResp.Body.Close()
	if colleagueResp.StatusCode != http.StatusCreated {
		t.Fatalf("same-company registration status = %d, want created", colleagueResp.StatusCode)
	}
	other, _ := http.NewRequest(http.MethodGet, server.URL+"/api/v1/users/999999999", nil)
	other.AddCookie(loginCookie)
	otherResp, err := http.DefaultClient.Do(other)
	if err != nil {
		t.Fatal(err)
	}
	otherResp.Body.Close()
	if otherResp.StatusCode != http.StatusForbidden {
		t.Fatalf("cross-user lookup status = %d, want forbidden", otherResp.StatusCode)
	}

	meReq, _ := http.NewRequest(http.MethodGet, server.URL+"/api/v1/auth/me", nil)
	meReq.AddCookie(loginCookie)
	meResp, err := http.DefaultClient.Do(meReq)
	if err != nil {
		t.Fatal(err)
	}
	defer meResp.Body.Close()
	if meResp.StatusCode != http.StatusOK {
		t.Fatalf("me status = %d", meResp.StatusCode)
	}

	logoutReq, _ := http.NewRequest(http.MethodPost, server.URL+"/api/v1/auth/logout", nil)
	logoutReq.AddCookie(loginCookie)
	logoutReq.Header.Set("Origin", server.URL)
	logoutResp, err := http.DefaultClient.Do(logoutReq)
	if err != nil {
		t.Fatal(err)
	}
	defer logoutResp.Body.Close()
	if logoutResp.StatusCode != http.StatusNoContent {
		t.Fatalf("logout status = %d", logoutResp.StatusCode)
	}
}

func TestOnboardingReplayChecksCurrentPasswordWithoutPersistingItInFingerprint(t *testing.T) {
	server, store, dsn := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	key := "onboarding-password-" + suffix
	body := onboardingBody(suffix)
	first := postOnboarding(t, server.URL, key, body)
	if first.StatusCode != http.StatusCreated {
		t.Fatalf("first response status = %d, want %d", first.StatusCode, http.StatusCreated)
	}
	first.Body.Close()

	var fingerprintInput onboardingRequest
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(encoded, &fingerprintInput); err != nil {
		t.Fatal(err)
	}
	fingerprintInput.User.Password = ""
	sort.Strings(fingerprintInput.User.Roles)
	canonical, err := json.Marshal(fingerprintInput)
	if err != nil {
		t.Fatal(err)
	}
	wantHash := sha256.Sum256(canonical)
	var storedHash string
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if err := conn.QueryRow(ctx, `SELECT request_hash FROM onboarding_requests WHERE idempotency_key=$1`, key).Scan(&storedHash); err != nil {
		t.Fatal(err)
	}
	if storedHash != hex.EncodeToString(wantHash[:]) {
		t.Fatal("persisted onboarding fingerprint includes secret fields or differs from canonical public request")
	}

	newPassword := "new-correct-horse-battery"
	newHash, err := hashPassword(newPassword)
	if err != nil {
		t.Fatal(err)
	}
	email := body["user"].(map[string]any)["email"].(string)
	if err := store.SetPasswordByEmail(context.Background(), email, newHash); err != nil {
		t.Fatal(err)
	}
	var userID int64
	if err := conn.QueryRow(ctx, `SELECT id FROM users WHERE email=$1`, email).Scan(&userID); err != nil {
		t.Fatal(err)
	}

	stale := postOnboarding(t, server.URL, key, body)
	stale.Body.Close()
	if stale.StatusCode != http.StatusUnauthorized || stale.Header.Get("Set-Cookie") != "" {
		t.Fatalf("replay with revoked password status=%d cookie=%q, want 401 without session", stale.StatusCode, stale.Header.Get("Set-Cookie"))
	}
	var sessionCount int
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM auth_sessions WHERE user_id=$1`, userID).Scan(&sessionCount); err != nil {
		t.Fatal(err)
	}
	if sessionCount != 0 {
		t.Fatalf("replay with revoked password created %d sessions, want none", sessionCount)
	}

	body["user"].(map[string]any)["password"] = newPassword
	current := postOnboarding(t, server.URL, key, body)
	current.Body.Close()
	if current.StatusCode != http.StatusOK || current.Header.Get("Set-Cookie") == "" {
		t.Fatalf("replay with current password status=%d cookie=%q, want 200 with session", current.StatusCode, current.Header.Get("Set-Cookie"))
	}
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM auth_sessions WHERE user_id=$1`, userID).Scan(&sessionCount); err != nil {
		t.Fatal(err)
	}
	if sessionCount != 1 {
		t.Fatalf("replay with current password created %d sessions, want one", sessionCount)
	}

	body["user"].(map[string]any)["password"] = "wrong-password-for-replay"
	for i := 0; i < 10; i++ {
		resp := postOnboarding(t, server.URL, key, body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Fatalf("wrong replay attempt %d status=%d, want 401", i+1, resp.StatusCode)
		}
	}
	limited := postOnboarding(t, server.URL, key, body)
	limited.Body.Close()
	if limited.StatusCode != http.StatusTooManyRequests || limited.Header.Get("Retry-After") != "60" {
		t.Fatalf("repeated wrong replay status=%d retry-after=%q, want 429/60", limited.StatusCode, limited.Header.Get("Retry-After"))
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

func TestOnboardingRejectsCaseVariantEmail(t *testing.T) {
	server, _, _ := newOnboardingTestServer(t)
	suffix := onboardingSuffix()
	first := onboardingBody(suffix)
	resp := postOnboarding(t, server.URL, "case-a-"+suffix, first)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("first onboarding status = %d", resp.StatusCode)
	}
	resp.Body.Close()
	second := onboardingBody(suffix + "-other")
	second["user"].(map[string]any)["email"] = strings.ToUpper(suffix + "@example.test")
	resp = postOnboarding(t, server.URL, "case-b-"+suffix, second)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("case-variant onboarding status = %d, want conflict", resp.StatusCode)
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
			req.Header.Set("Origin", server.URL)
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
			req.Header.Set("Origin", server.URL)
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
