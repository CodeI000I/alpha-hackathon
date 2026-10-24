package ingest

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
)

func TestBackoff(t *testing.T) {
	for attempt, want := range map[int]time.Duration{1: time.Minute, 2: 2 * time.Minute, 4: 8 * time.Minute, 9: 4*time.Hour + 16*time.Minute, 30: 6 * time.Hour} {
		if got := backoff(attempt); got != want {
			t.Errorf("backoff(%d) = %v, want %v", attempt, got, want)
		}
	}
}

// fakeRanker отвечает только за новости своей компании: в общей тестовой базе есть и чужие.
type fakeRanker struct {
	mu        sync.Mutex
	companyID int64
	calls     map[int64][][]string // news id → роли каждого вызова
	answer    func(req feed.Request) ([]feed.Match, error)
}

func (f *fakeRanker) Rank(_ context.Context, req feed.Request) ([]feed.Match, error) {
	if req.Company.ID != f.companyID {
		return nil, nil
	}
	f.mu.Lock()
	f.calls[req.News.ID] = append(f.calls[req.News.ID], req.Roles)
	f.mu.Unlock()
	return f.answer(req)
}

func (f *fakeRanker) count(newsID int64) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls[newsID])
}

// Как и тесты httpapi, идёт против настоящего PostgreSQL и без TEST_DATABASE_URL пропускается.
func newTestStore(t *testing.T) *postgres.Store {
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
	return store
}

func TestRankQueue(t *testing.T) {
	store := newTestStore(t)
	ctx := context.Background()
	n := time.Now().UnixNano()
	company, _, err := store.CreateCompany(ctx, domain.Company{INN: fmt.Sprintf("%010d", n%1e10), Name: "ООО Очередь"})
	if err != nil {
		t.Fatal(err)
	}
	newUser := func(roles ...string) domain.User {
		u, err := store.CreateUser(ctx, domain.User{Email: fmt.Sprintf("q%d-%d@example.ru", n, len(roles)), FullName: "Директор",
			CompanyID: &company.ID, Roles: roles})
		if err != nil {
			t.Fatal(err)
		}
		return u
	}
	ceo := newUser("cfo", "ceo")
	cfo := newUser("cfo")
	addNews := func(title string) int64 {
		res, err := store.ImportNews(ctx, []domain.NewsItem{{SourceID: "manual", ExternalID: fmt.Sprintf("%s-%d", title, n),
			Title: title, Body: "Полный текст", PublishedAt: time.Now()}})
		if err != nil {
			t.Fatal(err)
		}
		return res[0].ID
	}
	feedOf := func(u domain.User) []domain.FeedItem {
		items, err := store.Feed(ctx, u.ID, "", 200)
		if err != nil {
			t.Fatal(err)
		}
		return items
	}

	news := addNews("Ставка")
	ranker := &fakeRanker{companyID: company.ID, calls: map[int64][][]string{}, answer: func(req feed.Request) ([]feed.Match, error) {
		if req.News.ID != news {
			return nil, nil // новости других тестов в общей базе
		}
		if req.News.Body != "Полный текст" {
			t.Errorf("orchestrator got no body: %+v", req.News)
		}
		// elements: null и неизвестная роль не должны ломать раскладку.
		return []feed.Match{{Role: "cfo", Kind: "risk", Score: 0.9, Insight: "Расходы вырастут", Elements: []string{"Б3"}},
			{Role: "ceo", Kind: "event"}, {Role: "nobody", Kind: "event"}}, nil
	}}
	p := &Pipeline{Store: store, Ranker: ranker, Log: slog.New(slog.NewTextHandler(io.Discard, nil)), MaxPerRun: 1000, Lookback: time.Hour}
	if err := p.Rank(ctx); err != nil {
		t.Fatal(err)
	}
	if got := ranker.calls[news]; len(got) != 2 || !slices.Equal(got[0], []string{"ceo", "cfo"}) || !slices.Equal(got[1], []string{"ceo", "cfo"}) {
		t.Fatalf("want each user delivery to request the union of roles, got %v", got)
	}
	if items := feedOf(cfo); len(items) != 1 || items[0].Role != "cfo" || items[0].Kind != "risk" ||
		!slices.Equal(items[0].Elements, []string{"Б3"}) || items[0].News.ID != news {
		t.Fatalf("cfo feed: %+v", items)
	}
	if items := feedOf(ceo); len(items) != 2 || items[0].News.ID != news || items[1].News.ID != news {
		t.Fatalf("ceo feed: %+v", items)
	}
	if items, _ := store.Feed(ctx, ceo.ID, "ceo", 10); len(items) != 1 || items[0].Elements == nil || len(items[0].Elements) != 0 {
		t.Fatalf("ceo role feed: %+v", items)
	}

	// Новый директор с той же ролью получает карточку без новой оценки.
	late := newUser("cfo", "ceo", "sales")
	if err := store.SetUserRoles(ctx, late.ID, []string{"cfo"}); err != nil {
		t.Fatal(err)
	}
	if err := p.Rank(ctx); err != nil {
		t.Fatal(err)
	}
	if ranker.count(news) != 5 || len(feedOf(late)) != 1 {
		t.Fatalf("calls=%d, late feed=%+v", ranker.count(news), feedOf(late))
	}
	// Новая роль в компании — переоценка по полному набору ролей.
	if err := store.SetUserRoles(ctx, late.ID, []string{"cfo", "sales"}); err != nil {
		t.Fatal(err)
	}
	if err := p.Rank(ctx); err != nil {
		t.Fatal(err)
	}
	if got := ranker.calls[news]; len(got) != 8 {
		t.Fatalf("want all three user deliveries to be re-ranked, got %v", got)
	} else {
		for _, roles := range got[5:] {
			if !slices.Equal(roles, []string{"ceo", "cfo", "sales"}) {
				t.Fatalf("want re-rank with the new role union, got %v", got)
			}
		}
	}

	// Отказы: 422 снимает новость с очереди, сбой сети — повтор позже, Retry-After — пауза всех оценок.
	rejected, broken := addNews("Отказ"), addNews("Сбой")
	var limited int64
	ranker.answer = func(req feed.Request) ([]feed.Match, error) {
		switch req.News.ID {
		case rejected:
			return nil, &feed.Error{Permanent: true, Err: fmt.Errorf("422")}
		case broken:
			return nil, fmt.Errorf("connection refused")
		case limited:
			return nil, &feed.Error{RetryAfter: time.Hour, Err: fmt.Errorf("429")}
		}
		return nil, nil
	}
	// Проход останавливается на первом сбое оркестратора, 422 — нет.
	for range 3 {
		if err := p.Rank(ctx); err != nil {
			t.Fatal(err)
		}
	}
	if ranker.count(rejected) != 1 || ranker.count(broken) != 1 {
		t.Fatalf("one failed request should defer all sibling deliveries: rejected=%d broken=%d", ranker.count(rejected), ranker.count(broken))
	}
	limited = addNews("Лимит")
	for range 2 {
		if err := p.Rank(ctx); err != nil {
			t.Fatal(err)
		}
	}
	if ranker.count(limited) != 1 || time.Until(p.pausedUntil) < 59*time.Minute {
		t.Fatalf("Retry-After must pause ranking: calls=%d, paused until %v", ranker.count(limited), p.pausedUntil)
	}
	// Другой воркер без паузы тоже их не берёт: 422 снят с очереди, остальные отложены.
	other := &Pipeline{Store: store, Ranker: ranker, Log: p.Log, MaxPerRun: 1000, Lookback: time.Hour}
	if err := other.Rank(ctx); err != nil {
		t.Fatal(err)
	}
	if ranker.count(rejected)+ranker.count(broken)+ranker.count(limited) != 3 {
		t.Fatal("failed rankings must wait for their next attempt")
	}
}

func TestClaimOrderAlternatesAcrossWorkerRuns(t *testing.T) {
	p := &Pipeline{}
	for i, want := range []bool{true, false, true, false} {
		if got := p.nextClaimNewestFirst(); got != want {
			t.Fatalf("claim %d newestFirst=%v, want %v", i+1, got, want)
		}
	}
}

func TestCollect(t *testing.T) {
	store := newTestStore(t)
	ctx := context.Background()
	n := time.Now().UnixNano()
	var mu sync.Mutex
	seen := map[string]bool{}
	fetch := fetcherFunc(func(_ context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
		mu.Lock()
		seen[src.ID] = true
		mu.Unlock()
		if src.Config["feed_url"] == "" {
			t.Errorf("source %s without feed_url", src.ID)
		}
		return []domain.NewsItem{{ExternalID: fmt.Sprint(n), Title: "Новость", PublishedAt: time.Now()}}, nil
	})
	p := &Pipeline{Store: store, Fetchers: map[string]Fetcher{"rss": fetch}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err := p.Collect(ctx); err != nil {
		t.Fatal(err)
	}
	// Миграция 0003 включает RSS-ленты, у которых нашёлся адрес.
	for _, id := range []string{"S085", "S086", "S136", "S137", "S138", "S139", "S140", "S141", "S142", "S144"} {
		if !seen[id] {
			t.Errorf("source %s is not collected", id)
		}
	}
	if seen["S112"] || seen["manual"] {
		t.Errorf("unexpected sources collected: %v", seen)
	}
}

type fetcherFunc func(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error)

func (f fetcherFunc) Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
	return f(ctx, src)
}
