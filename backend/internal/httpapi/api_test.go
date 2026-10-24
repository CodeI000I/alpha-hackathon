package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
)

// Тесты контракта с фронтендом против настоящего PostgreSQL. Без TEST_DATABASE_URL пропускаются:
//
//	docker run -d --rm --name alpha-test-pg -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
//	  -e POSTGRES_DB=alpha -p 127.0.0.1:55432:5432 postgres:16-alpine
//	TEST_DATABASE_URL=postgres://app:app@localhost:55432/alpha?sslmode=disable go test ./...
func newTestServer(t *testing.T, files FileStore) (*httptest.Server, *postgres.Store) {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	store, err := postgres.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	if err := store.Migrate(ctx, migrations.FS); err != nil {
		t.Fatal(err)
	}
	s := &Server{Store: store, Files: files, InternalToken: testToken, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	srv := httptest.NewServer(s.Handler())
	t.Cleanup(srv.Close)
	return srv, store
}

// unique — уникальные ИНН и email, чтобы тесты можно было гонять повторно на одной базе.
func unique() (inn, email string) {
	n := time.Now().UnixNano()
	return fmt.Sprintf("%010d", n%1e10), fmt.Sprintf("user%d@example.ru", n)
}

func call(t *testing.T, method, url string, body any) (int, []byte) {
	t.Helper()
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, url, r)
	req.Header.Set("Content-Type", "application/json")
	return do(t, req)
}

func do(t *testing.T, req *http.Request) (int, []byte) {
	t.Helper()
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b
}

func expect(t *testing.T, gotStatus int, body []byte, wantStatus int, wantBody string) {
	t.Helper()
	if gotStatus != wantStatus || !strings.Contains(string(body), wantBody) {
		t.Fatalf("got %d %s, want %d with %q", gotStatus, body, wantStatus, wantBody)
	}
}

func TestCatalogsAreArrays(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	for _, path := range []string{"/api/v1/roles", "/api/v1/profile-elements"} {
		status, body := call(t, "GET", srv.URL+path, nil)
		expect(t, status, body, 200, "[")
	}
}

func TestOnboarding(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	inn, email := unique()

	status, body := call(t, "POST", srv.URL+"/api/v1/companies", map[string]string{"inn": inn, "name": " ООО Север "})
	expect(t, status, body, 201, `"name":"ООО Север"`)
	var company domain.Company
	json.Unmarshal(body, &company)

	// Второй директор с тем же ИНН присоединяется к уже созданной компании, её данные не меняются.
	status, body = call(t, "POST", srv.URL+"/api/v1/companies", map[string]string{"inn": inn, "name": "ООО Юг"})
	expect(t, status, body, 200, fmt.Sprintf(`{"id":%d,"inn":"%s","ogrn":"","name":"ООО Север"`, company.ID, inn))

	for _, bad := range []string{"123", "12345678901", "1234567890123", "12345abcde"} {
		status, body = call(t, "POST", srv.URL+"/api/v1/companies", map[string]string{"inn": bad, "name": "ООО"})
		expect(t, status, body, 400, "ИНН должен содержать 10 или 12 цифр")
	}

	in := map[string]any{"fullName": "Анна Петрова", "email": email, "companyId": company.ID, "roles": []string{"ceo", "cfo", "nope"}}
	status, body = call(t, "POST", srv.URL+"/api/v1/users", in)
	expect(t, status, body, 201, `"fullName":"Анна Петрова"`)
	var user domain.User
	json.Unmarshal(body, &user)
	if len(user.Roles) != 2 || strings.Contains(string(body), "nope") {
		t.Fatalf("want roles ceo and cfo without the unknown code, got %v", user.Roles)
	}

	status, body = call(t, "POST", srv.URL+"/api/v1/users", in)
	expect(t, status, body, 409, "электронной почтой уже зарегистрирован")

	_, email2 := unique()
	status, body = call(t, "POST", srv.URL+"/api/v1/users",
		map[string]any{"fullName": "Анна", "email": email2, "companyId": 1 << 50, "roles": []string{"ceo"}})
	expect(t, status, body, 404, "Компания не найдена")
	// Неудачная попытка не заняла email: транзакция откатилась.
	status, body = call(t, "POST", srv.URL+"/api/v1/users",
		map[string]any{"fullName": "Анна", "email": email2, "companyId": company.ID, "roles": []string{}})
	expect(t, status, body, 201, `"roles":[]`)

	status, body = call(t, "POST", srv.URL+"/api/v1/users", map[string]any{"fullName": "Анна", "email": "anna@"})
	expect(t, status, body, 400, "корректную электронную почту")

	status, body = call(t, "PUT", fmt.Sprintf("%s/api/v1/users/%d/roles", srv.URL, user.ID), map[string]any{"roles": []string{"strategy"}})
	expect(t, status, body, 200, `"roles":["strategy"]`)
}

func TestNotFound(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	const missing = "/999999999"
	for _, tc := range []struct{ method, path, want string }{
		{"GET", "/api/v1/users" + missing, "Пользователь не найден"},
		{"PUT", "/api/v1/users" + missing + "/roles", "Пользователь не найден"},
		{"GET", "/api/v1/users" + missing + "/feed", "Пользователь не найден"},
		{"GET", "/api/v1/companies" + missing, "Компания не найдена"},
		{"GET", "/api/v1/companies" + missing + "/files", "Компания не найдена"},
		{"PATCH", "/api/v1/companies" + missing + "/profile", "Компания не найдена"},
		{"GET", "/api/v1/analyze", "Метод API не найден"},
		{"POST", "/api/v1/roles", "Метод API не найден"},
	} {
		status, body := call(t, tc.method, srv.URL+tc.path, map[string]any{"roles": []string{"ceo"}})
		expect(t, status, body, 404, tc.want)
	}
	status, body := call(t, "GET", srv.URL+"/api/v1/users/abc", nil)
	expect(t, status, body, 400, "Некорректный идентификатор")
}

func TestFeed(t *testing.T) {
	srv, store := newTestServer(t, nil)
	ctx := context.Background()
	inn, email := unique()
	company, _, err := store.CreateCompany(ctx, domain.Company{INN: inn, Name: "ООО Лента"})
	if err != nil {
		t.Fatal(err)
	}
	user, err := store.CreateUser(ctx, domain.User{Email: email, FullName: "Иван", CompanyID: &company.ID, Roles: []string{"cfo"}})
	if err != nil {
		t.Fatal(err)
	}
	feedURL := fmt.Sprintf("%s/api/v1/users/%d/feed", srv.URL, user.ID)

	status, body := call(t, "GET", feedURL, nil)
	expect(t, status, body, 200, "[]")

	newsID, _, err := store.UpsertNews(ctx, domain.NewsItem{SourceID: "S001", ExternalID: email, Title: "Новость", PublishedAt: time.Now()})
	if err != nil {
		t.Fatal(err)
	}
	// Оркестратор может прислать elements: null — колонка NOT NULL, запись не должна падать.
	if err := store.AddFeedItem(ctx, user.ID, "cfo", newsID, domain.FeedItem{Kind: "risk", Score: 0.9}); err != nil {
		t.Fatal(err)
	}
	status, body = call(t, "GET", feedURL+"?role=cfo&limit=1000", nil)
	expect(t, status, body, 200, `"elements":[]`)
}

const testToken = "test-internal-token"

func TestImportNews(t *testing.T) {
	srv, store := newTestServer(t, nil)
	url := srv.URL + "/api/v1/internal/news"
	post := func(token string, body any) (int, []byte) {
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest("POST", url, bytes.NewReader(b))
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		return do(t, req)
	}
	_, email := unique()
	news := []map[string]any{{"title": " Ставка ЦБ " + email, "body": "Полный текст", "publishedAt": "2026-10-22T10:30:00Z"}}

	status, body := post("", news)
	expect(t, status, body, 401, "Нужен служебный токен")
	status, body = post("wrong", news)
	expect(t, status, body, 401, "Нужен служебный токен")
	status, body = post(testToken, map[string]any{"title": "не массив"})
	expect(t, status, body, 400, "Ожидается JSON-массив")
	status, body = post(testToken, []map[string]any{{"title": "  "}})
	expect(t, status, body, 400, "Новость 1: укажите title")
	status, body = post(testToken, []map[string]any{{"title": "x", "sourceId": "S999"}})
	expect(t, status, body, 404, "Источник не найден")

	status, body = post(testToken, news)
	expect(t, status, body, 200, `"created":true`)
	// Без externalId и url повтор того же текста — та же новость.
	status, body = post(testToken, news)
	expect(t, status, body, 200, `"created":false`)

	// Без INTERNAL_API_TOKEN маршрут выключен.
	off := httptest.NewServer((&Server{Store: store, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler())
	defer off.Close()
	status, body = call(t, "POST", off.URL+"/api/v1/internal/news", news)
	expect(t, status, body, 404, "Метод API не найден")
}

type memFiles struct {
	mu   sync.Mutex
	keys []string
	data map[string][]byte
}

func (m *memFiles) Put(_ context.Context, key string, r io.Reader, _ int64, _ string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.keys = append(m.keys, key)
	data, err := io.ReadAll(r)
	if err == nil {
		if m.data == nil {
			m.data = map[string][]byte{}
		}
		m.data[key] = data
	}
	return err
}

func (m *memFiles) Get(_ context.Context, key string) (io.ReadCloser, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return io.NopCloser(bytes.NewReader(m.data[key])), nil
}

func upload(t *testing.T, url string, size int) (int, []byte) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("file", "бюджет-2027.pdf")
	fw.Write(bytes.Repeat([]byte("x"), size))
	mw.Close()
	req, _ := http.NewRequest("POST", url, &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	return do(t, req)
}

func TestFiles(t *testing.T) {
	srv, store := newTestServer(t, nil)
	status, body := upload(t, srv.URL+"/api/v1/companies/1/files", 10)
	expect(t, status, body, 503, "Хранилище файлов не настроено")

	files := &memFiles{}
	srv, store = newTestServer(t, files)
	inn, _ := unique()
	company, _, err := store.CreateCompany(context.Background(), domain.Company{INN: inn, Name: "ООО Файлы"})
	if err != nil {
		t.Fatal(err)
	}
	filesURL := fmt.Sprintf("%s/api/v1/companies/%d/files", srv.URL, company.ID)

	status, body = upload(t, srv.URL+"/api/v1/companies/999999999/files", 10)
	expect(t, status, body, 404, "Компания не найдена")
	status, body = upload(t, filesURL, maxUpload+1)
	expect(t, status, body, 413, "Файл больше 12 МБ")
	if len(files.keys) != 0 {
		t.Fatalf("nothing should reach the storage, got %v", files.keys)
	}

	status, body = upload(t, filesURL, 10)
	expect(t, status, body, 201, `"filename":"бюджет-2027.pdf"`)
	var uploaded domain.CompanyFile
	if err := json.Unmarshal(body, &uploaded); err != nil {
		t.Fatal(err)
	}
	internalURL := fmt.Sprintf("%s/api/v1/internal/files/%d/content", srv.URL, uploaded.ID)
	unauthorized, _ := http.NewRequest(http.MethodGet, internalURL, nil)
	status, body = do(t, unauthorized)
	expect(t, status, body, 401, "Нужен служебный токен")
	internal, _ := http.NewRequest(http.MethodGet, internalURL, nil)
	internal.Header.Set("Authorization", "Bearer "+testToken)
	status, body = do(t, internal)
	expect(t, status, body, 200, "xxxxxxxxxx")
	if got := files.data[files.keys[0]]; string(got) != "xxxxxxxxxx" {
		t.Fatalf("stored test object = %q", got)
	}
	files.data[files.keys[0]] = []byte("short")
	status, body = do(t, internal)
	expect(t, status, body, 502, "Размер файла не совпадает")
	status, body = call(t, "GET", filesURL, nil)
	expect(t, status, body, 200, `"sizeBytes":10`)
}
