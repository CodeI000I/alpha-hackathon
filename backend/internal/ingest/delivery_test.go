package ingest

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const ingestTestDatabase = "analytics_test_audit_backend"

type fixtureFetcher struct {
	mu    sync.Mutex
	items []domain.NewsItem
}

func (f *fixtureFetcher) Fetch(context.Context, postgres.SourceConfig) ([]domain.NewsItem, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]domain.NewsItem(nil), f.items...), nil
}

func (f *fixtureFetcher) set(items ...domain.NewsItem) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.items = append([]domain.NewsItem(nil), items...)
}

type rankResult struct {
	matches []feed.Match
	err     error
}

type fixtureRanker struct {
	mu      sync.Mutex
	results []rankResult
	calls   int
}

func (r *fixtureRanker) Rank(context.Context, feed.Request) ([]feed.Match, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.calls++
	if len(r.results) == 0 {
		return nil, nil
	}
	result := r.results[0]
	if len(r.results) > 1 {
		r.results = r.results[1:]
	}
	return result.matches, result.err
}

func (r *fixtureRanker) callCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.calls
}

type ingestFixture struct {
	store    *postgres.Store
	pool     *pgxpool.Pool
	pipeline *Pipeline
	fetcher  *fixtureFetcher
	ranker   *fixtureRanker
	source   string
	userID   int64
	news     domain.NewsItem
}

func newIngestFixture(t *testing.T, items ...domain.NewsItem) *ingestFixture {
	t.Helper()
	dsn := os.Getenv("INGEST_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("INGEST_TEST_DATABASE_URL is not set")
	}
	config, err := pgx.ParseConfig(dsn)
	if err != nil {
		t.Fatalf("parse test database URL: %v", err)
	}
	if config.Database != ingestTestDatabase || !isLoopback(config.Host) {
		t.Fatalf("refusing non-isolated ingest test database %q at host %q", config.Database, config.Host)
	}
	for _, fallback := range config.Fallbacks {
		if fallback == nil {
			t.Fatal("refusing nil ingest test fallback host")
		}
		if !isLoopback(fallback.Host) {
			t.Fatalf("refusing non-loopback ingest test fallback host %q", fallback.Host)
		}
	}
	ctx := context.Background()
	store, err := postgres.New(ctx, dsn)
	if err != nil {
		t.Fatalf("connect test store: %v", err)
	}
	t.Cleanup(store.Close)
	if err := store.Migrate(ctx, migrations.FS); err != nil {
		t.Fatalf("migrate test database: %v", err)
	}
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("connect test query pool: %v", err)
	}
	t.Cleanup(pool.Close)

	key := strings.ReplaceAll(uuid.NewString(), "-", "")
	sourceID := "audit-" + key
	company, _, err := store.CreateCompany(ctx, domain.Company{
		INN: key[:12], Name: "Ingest test " + key[:8],
	})
	if err != nil {
		t.Fatalf("create test company: %v", err)
	}
	user, err := store.CreateUser(ctx, domain.User{
		CompanyID: &company.ID, Email: key + "@example.test", FullName: "Ingest Test",
		Roles: []string{"procurement"},
	})
	if err != nil {
		t.Fatalf("create test user: %v", err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO sources(id, category, name, adapter, enabled)
		VALUES ($1, 'test', 'Ingest fixture', 'audit', true)`, sourceID); err != nil {
		t.Fatalf("create test source: %v", err)
	}
	t.Cleanup(func() {
		cleanupCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_, _ = pool.Exec(cleanupCtx, `DELETE FROM news_items WHERE source_id=$1`, sourceID)
		_, _ = pool.Exec(cleanupCtx, `DELETE FROM sources WHERE id=$1`, sourceID)
		_, _ = pool.Exec(cleanupCtx, `DELETE FROM users WHERE id=$1`, user.ID)
		_, _ = pool.Exec(cleanupCtx, `DELETE FROM companies WHERE id=$1`, company.ID)
	})

	fetcher := &fixtureFetcher{}
	fetcher.set(items...)
	ranker := &fixtureRanker{}
	return &ingestFixture{
		store: store, pool: pool, fetcher: fetcher, ranker: ranker,
		pipeline: &Pipeline{
			Store: store, Ranker: ranker, Fetchers: map[string]Fetcher{"audit": fetcher},
			Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		},
		source: sourceID, userID: user.ID,
		news: domain.NewsItem{ExternalID: "fixture-1", URL: "https://example.test/news/1",
			Title: "Fixture title", Summary: "Fixture summary", Body: "Fixture body",
			PublishedAt: time.Date(2026, 10, 23, 10, 0, 0, 0, time.UTC)},
	}
}

func isLoopback(host string) bool {
	return host == "localhost" || host == "127.0.0.1" || host == "::1"
}

func (f *ingestFixture) rows(t *testing.T) (int, int, int64, string, bool, *time.Time) {
	t.Helper()
	var newsCount, deliveryCount int
	var revision int64
	var state string
	var active bool
	var readAt *time.Time
	err := f.pool.QueryRow(context.Background(), `
		SELECT n.revision,
		       (SELECT count(*) FROM news_items WHERE source_id=$1),
		       (SELECT count(*) FROM news_deliveries WHERE news_id=n.id),
		       (SELECT state FROM news_deliveries WHERE news_id=n.id AND user_id=$2 ORDER BY revision DESC LIMIT 1),
	       COALESCE((SELECT active FROM feed_items WHERE news_id=n.id AND user_id=$2 LIMIT 1), false),
	       (SELECT read_at FROM feed_items WHERE news_id=n.id AND user_id=$2 LIMIT 1)
		FROM news_items n WHERE n.source_id=$1 AND n.external_id='fixture-1'`,
		f.source, f.userID).Scan(&revision, &newsCount, &deliveryCount, &state, &active, &readAt)
	if err != nil {
		t.Fatalf("read delivery fixture: %v", err)
	}
	return newsCount, deliveryCount, revision, state, active, readAt
}

func (f *ingestFixture) setDeliveryDue(t *testing.T) {
	t.Helper()
	if _, err := f.pool.Exec(context.Background(), `UPDATE news_deliveries SET next_attempt_at=now()-interval '1 second'
		WHERE news_id=(SELECT id FROM news_items WHERE source_id=$1 AND external_id='fixture-1')`, f.source); err != nil {
		t.Fatalf("make delivery due: %v", err)
	}
}

func (f *ingestFixture) setRankResults(results ...rankResult) {
	f.ranker.mu.Lock()
	defer f.ranker.mu.Unlock()
	f.ranker.results = append([]rankResult(nil), results...)
}

func (f *ingestFixture) errorForInsightTrigger(t *testing.T) {
	t.Helper()
	_, err := f.pool.Exec(context.Background(), fmt.Sprintf(`
		CREATE FUNCTION %q() RETURNS trigger LANGUAGE plpgsql AS $$
		BEGIN
			IF NEW.insight = 'fail-once' THEN RAISE EXCEPTION 'fixture write failure'; END IF;
			RETURN NEW;
		END $$;
		CREATE TRIGGER %q BEFORE INSERT OR UPDATE ON feed_items
		FOR EACH ROW EXECUTE FUNCTION %q()`, "audit_fail_feed_"+strings.ReplaceAll(f.source, "-", "_"),
		"audit_fail_feed_trigger_"+strings.ReplaceAll(f.source, "-", "_"),
		"audit_fail_feed_"+strings.ReplaceAll(f.source, "-", "_")))
	if err != nil {
		t.Fatalf("install write failure trigger: %v", err)
	}
	t.Cleanup(func() {
		name := strings.ReplaceAll(f.source, "-", "_")
		_, _ = f.pool.Exec(context.Background(), `DROP TRIGGER IF EXISTS `+"audit_fail_feed_trigger_"+name+` ON feed_items`)
		_, _ = f.pool.Exec(context.Background(), `DROP FUNCTION IF EXISTS `+"audit_fail_feed_"+name+`() CASCADE`)
	})
}

func TestRankFailureRetriesAfterSourceItemDisappears(t *testing.T) {
	f := newIngestFixture(t)
	f.fetcher.set(f.news)
	f.setRankResults(rankResult{err: errors.New("temporary rank outage")}, rankResult{matches: []feed.Match{{
		Role: "procurement", Kind: "risk", Score: .8, Insight: "recovered",
	}}})
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("first RunOnce: %v", err)
	}
	if got := f.ranker.callCount(); got != 1 {
		t.Fatalf("first cycle rank calls = %d, want 1", got)
	}
	if news, _, _, state, _, _ := f.rows(t); news != 1 || state != "pending" {
		t.Fatalf("after rank failure news=%d state=%q, want durable pending delivery", news, state)
	}
	f.setDeliveryDue(t)
	f.fetcher.set() // The source no longer returns the news; delivery must still recover.
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("retry RunOnce: %v", err)
	}
	if got := f.ranker.callCount(); got != 2 {
		t.Fatalf("total rank calls = %d, want retry call", got)
	}
	if _, _, _, state, active, _ := f.rows(t); state != "done" || !active {
		t.Fatalf("after recovery state=%q active=%v", state, active)
	}
}

func TestEmptyRankResultCompletesWithoutRepeatedCalls(t *testing.T) {
	f := newIngestFixture(t)
	f.fetcher.set(f.news)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("first RunOnce: %v", err)
	}
	if _, deliveries, _, state, active, _ := f.rows(t); deliveries != 1 || state != "done" || active {
		t.Fatalf("empty result state: deliveries=%d state=%q active=%v", deliveries, state, active)
	}
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("unchanged RunOnce: %v", err)
	}
	if got := f.ranker.callCount(); got != 1 {
		t.Fatalf("rank calls = %d, want no repeat after empty completion", got)
	}
}

func TestCorrectedNewsReprocessesAndPreservesReadAt(t *testing.T) {
	f := newIngestFixture(t)
	f.fetcher.set(f.news)
	f.setRankResults(
		rankResult{matches: []feed.Match{{Role: "procurement", Kind: "risk", Score: .6, Insight: "before"}}},
		rankResult{matches: []feed.Match{{Role: "procurement", Kind: "opportunity", Score: .9, Insight: "after"}}},
	)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("initial RunOnce: %v", err)
	}
	readAt := time.Date(2026, 10, 23, 12, 0, 0, 0, time.UTC)
	if _, err := f.pool.Exec(context.Background(), `UPDATE feed_items SET read_at=$1 WHERE news_id=(
		SELECT id FROM news_items WHERE source_id=$2 AND external_id='fixture-1')`, readAt, f.source); err != nil {
		t.Fatalf("mark feed item read: %v", err)
	}
	corrected := f.news
	corrected.Title = "Corrected title"
	corrected.Summary = "Corrected summary"
	corrected.Body = "Corrected body"
	corrected.URL = "https://example.test/news/corrected"
	corrected.PublishedAt = corrected.PublishedAt.Add(24 * time.Hour)
	f.fetcher.set(corrected)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("corrected RunOnce: %v", err)
	}
	var title, summary, body, url, insight, kind string
	var published time.Time
	var gotReadAt *time.Time
	err := f.pool.QueryRow(context.Background(), `
		SELECT n.title,n.summary,n.body,n.url,n.published_at,f.insight,f.kind,f.read_at
		FROM news_items n JOIN feed_items f ON f.news_id=n.id
		WHERE n.source_id=$1 AND n.external_id='fixture-1' AND f.user_id=$2`, f.source, f.userID).
		Scan(&title, &summary, &body, &url, &published, &insight, &kind, &gotReadAt)
	if err != nil {
		t.Fatalf("read corrected news and feed: %v", err)
	}
	if title != corrected.Title || summary != corrected.Summary || body != corrected.Body || url != corrected.URL || !published.Equal(corrected.PublishedAt) {
		t.Fatalf("source correction not saved: title=%q summary=%q body=%q url=%q published=%v", title, summary, body, url, published)
	}
	if insight != "after" || kind != "opportunity" {
		t.Fatalf("feed was not reranked: insight=%q kind=%q", insight, kind)
	}
	if gotReadAt == nil || !gotReadAt.Equal(readAt) {
		t.Fatalf("read_at = %v, want preserved %v", gotReadAt, readAt)
	}
	if got := f.ranker.callCount(); got != 2 {
		t.Fatalf("rank calls = %d, want initial and corrected", got)
	}
}

func TestCorrectedNewsIsHiddenUntilRerankSucceeds(t *testing.T) {
	f := newIngestFixture(t)
	f.fetcher.set(f.news)
	f.setRankResults(
		rankResult{matches: []feed.Match{{Role: "procurement", Kind: "risk", Score: .6, Insight: "old insight"}}},
		rankResult{err: errors.New("rank unavailable")},
	)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("initial RunOnce: %v", err)
	}
	corrected := f.news
	corrected.Title = "Corrected title"
	f.fetcher.set(corrected)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("corrected RunOnce: %v", err)
	}
	var active bool
	var insight string
	err := f.pool.QueryRow(context.Background(), `SELECT active,insight FROM feed_items WHERE user_id=$1 AND news_id=(
		SELECT id FROM news_items WHERE source_id=$2 AND external_id='fixture-1')`, f.userID, f.source).Scan(&active, &insight)
	if err != nil {
		t.Fatalf("read old feed item: %v", err)
	}
	if active || insight != "old insight" {
		t.Fatalf("corrected news retained stale feed: active=%v insight=%q", active, insight)
	}
	if _, _, _, state, _, _ := f.rows(t); state != "pending" {
		t.Fatalf("failed rerank state=%q, want pending", state)
	}
}

func TestFeedWriteFailureRetriesFromDurableDelivery(t *testing.T) {
	f := newIngestFixture(t)
	f.fetcher.set(f.news)
	f.errorForInsightTrigger(t)
	f.setRankResults(
		rankResult{matches: []feed.Match{{Role: "procurement", Kind: "risk", Score: .7, Insight: "fail-once"}}},
		rankResult{matches: []feed.Match{{Role: "procurement", Kind: "risk", Score: .7, Insight: "persisted"}}},
	)
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("RunOnce after failed feed write: %v", err)
	}
	if _, _, _, state, _, _ := f.rows(t); state != "pending" {
		t.Fatalf("delivery state after DB failure = %q, want pending", state)
	}
	if got := f.ranker.callCount(); got != 1 {
		t.Fatalf("first cycle rank calls = %d, want no tight retry", got)
	}
	f.setDeliveryDue(t)
	f.fetcher.set()
	if err := f.pipeline.RunOnce(context.Background()); err != nil {
		t.Fatalf("RunOnce retry: %v", err)
	}
	var insight string
	err := f.pool.QueryRow(context.Background(), `SELECT f.insight FROM feed_items f JOIN news_items n ON n.id=f.news_id
		WHERE n.source_id=$1 AND f.user_id=$2`, f.source, f.userID).Scan(&insight)
	if err != nil || insight != "persisted" {
		t.Fatalf("recovered feed insight=%q err=%v", insight, err)
	}
}

func TestNewsAndDeliveryAreInsertedAtomically(t *testing.T) {
	f := newIngestFixture(t, fNewsForAtomicity())
	function := "audit_fail_delivery_" + strings.ReplaceAll(f.source, "-", "_")
	trigger := function + "_trigger"
	_, err := f.pool.Exec(context.Background(), fmt.Sprintf(`
		CREATE FUNCTION %q() RETURNS trigger LANGUAGE plpgsql AS $$
		BEGIN RAISE EXCEPTION 'fixture enqueue failure'; END $$;
		CREATE TRIGGER %q BEFORE INSERT ON news_deliveries
		FOR EACH ROW EXECUTE FUNCTION %q()`, function, trigger, function))
	if err != nil {
		t.Fatalf("install outbox failure trigger: %v", err)
	}
	t.Cleanup(func() {
		_, _ = f.pool.Exec(context.Background(), `DROP TRIGGER IF EXISTS `+trigger+` ON news_deliveries`)
		_, _ = f.pool.Exec(context.Background(), `DROP FUNCTION IF EXISTS `+function+`() CASCADE`)
	})
	if err := f.pipeline.RunOnce(context.Background()); err == nil {
		t.Fatal("RunOnce error = nil, want enqueue failure")
	}
	var newsCount, deliveryCount int
	err = f.pool.QueryRow(context.Background(), `
		SELECT (SELECT count(*) FROM news_items WHERE source_id=$1),
		       (SELECT count(*) FROM news_deliveries d JOIN news_items n ON n.id=d.news_id WHERE n.source_id=$1)`,
		f.source).Scan(&newsCount, &deliveryCount)
	if err != nil {
		t.Fatalf("check atomic rollback: %v", err)
	}
	if newsCount != 0 || deliveryCount != 0 {
		t.Fatalf("partial ingest persisted: news=%d deliveries=%d", newsCount, deliveryCount)
	}
}

func fNewsForAtomicity() domain.NewsItem {
	return domain.NewsItem{ExternalID: "fixture-1", URL: "https://example.test/news/1",
		Title: "Fixture title", Summary: "Fixture summary", Body: "Fixture body",
		PublishedAt: time.Date(2026, 10, 23, 10, 0, 0, 0, time.UTC)}
}

func TestConcurrentClaimsDoNotDuplicateDelivery(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	if _, _, err := f.store.UpsertNews(context.Background(), f.news); err != nil {
		t.Fatalf("enqueue delivery: %v", err)
	}
	start := make(chan struct{})
	results := make(chan []postgres.NewsDelivery, 2)
	errs := make(chan error, 2)
	for range 2 {
		go func() {
			<-start
			deliveries, err := f.store.ClaimNewsDeliveries(context.Background(), 10)
			results <- deliveries
			errs <- err
		}()
	}
	close(start)
	var total int
	for range 2 {
		if err := <-errs; err != nil {
			t.Fatalf("claim: %v", err)
		}
		total += len(<-results)
	}
	if total != 1 {
		t.Fatalf("concurrent claims returned %d deliveries, want exactly one", total)
	}
}

func TestExpiredLeaseFencesStaleCompletionAndRetractsOldMatch(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	if _, _, err := f.store.UpsertNews(context.Background(), f.news); err != nil {
		t.Fatalf("enqueue: %v", err)
	}
	first, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(first) != 1 {
		t.Fatalf("first claim=%v err=%v", first, err)
	}
	if _, err := f.pool.Exec(context.Background(), `UPDATE news_deliveries SET lease_until=now()-interval '1 second' WHERE id=$1`, first[0].ID); err != nil {
		t.Fatalf("expire lease: %v", err)
	}
	second, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(second) != 1 {
		t.Fatalf("second claim=%v err=%v", second, err)
	}
	match := []feed.Match{{Role: "procurement", Kind: "risk", Score: .7, Insight: "current"}}
	if ok, err := f.store.CompleteNewsDelivery(context.Background(), first[0], match); err != nil || ok {
		t.Fatalf("stale completion ok=%v err=%v, want fenced", ok, err)
	}
	if ok, err := f.store.CompleteNewsDelivery(context.Background(), second[0], match); err != nil || !ok {
		t.Fatalf("current completion ok=%v err=%v", ok, err)
	}
	corrected := f.news
	corrected.Title = "corrected"
	if _, _, err := f.store.UpsertNews(context.Background(), corrected); err != nil {
		t.Fatalf("correct news: %v", err)
	}
	newClaim, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(newClaim) != 1 {
		t.Fatalf("corrected claim=%v err=%v", newClaim, err)
	}
	if ok, err := f.store.CompleteNewsDelivery(context.Background(), newClaim[0], nil); err != nil || !ok {
		t.Fatalf("empty corrected completion ok=%v err=%v", ok, err)
	}
	var active bool
	if err := f.pool.QueryRow(context.Background(), `SELECT active FROM feed_items WHERE news_id=$1 AND user_id=$2`, newClaim[0].NewsID, f.userID).Scan(&active); err != nil {
		t.Fatalf("read retracted row: %v", err)
	}
	if active {
		t.Fatal("old match remained active after corrected empty result")
	}
}

func TestNoCurrentRolesCompletesWithoutRanking(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	if _, _, err := f.store.UpsertNews(context.Background(), f.news); err != nil {
		t.Fatalf("enqueue: %v", err)
	}
	if err := f.store.SetUserRoles(context.Background(), f.userID, nil); err != nil {
		t.Fatalf("remove roles: %v", err)
	}
	if err := f.pipeline.processDeliveries(context.Background()); err != nil {
		t.Fatalf("terminal delivery: %v", err)
	}
	if got := f.ranker.callCount(); got != 0 {
		t.Fatalf("rank calls=%d, want none", got)
	}
	if _, _, _, state, _, _ := f.rows(t); state != "done" {
		t.Fatalf("delivery state=%q, want done", state)
	}
}

func TestFeedHidesItemsForRolesNoLongerAssigned(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	newsID, _, err := f.store.UpsertNews(context.Background(), f.news)
	if err != nil {
		t.Fatalf("enqueue news: %v", err)
	}
	if err := f.store.AddFeedItem(context.Background(), f.userID, "procurement", newsID, domain.FeedItem{
		Kind: "risk", Score: .8, Insight: "published", Elements: []string{},
	}); err != nil {
		t.Fatalf("add feed item: %v", err)
	}
	if err := f.store.SetUserRoles(context.Background(), f.userID, nil); err != nil {
		t.Fatalf("remove role: %v", err)
	}
	items, err := f.store.Feed(context.Background(), f.userID, "", 10)
	if err != nil {
		t.Fatalf("read feed: %v", err)
	}
	if len(items) != 0 {
		t.Fatalf("feed returned %d item(s) for removed role", len(items))
	}
}

func TestSetRolesMissingUserReturnsNotFound(t *testing.T) {
	f := newIngestFixture(t)
	var missingID int64
	if err := f.pool.QueryRow(context.Background(), `SELECT COALESCE(max(id),0)+100000 FROM users`).Scan(&missingID); err != nil {
		t.Fatalf("choose missing user id: %v", err)
	}
	if err := f.store.SetUserRoles(context.Background(), missingID, []string{"procurement"}); !errors.Is(err, postgres.ErrNotFound) {
		t.Fatalf("SetUserRoles error=%v, want ErrNotFound", err)
	}
}

func TestCompletionDoesNotPublishRoleRemovedAfterClaim(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	if _, _, err := f.store.UpsertNews(context.Background(), f.news); err != nil {
		t.Fatalf("enqueue: %v", err)
	}
	claimed, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(claimed) != 1 {
		t.Fatalf("claim=%v err=%v", claimed, err)
	}
	if err := f.store.SetUserRoles(context.Background(), f.userID, nil); err != nil {
		t.Fatalf("remove role after claim: %v", err)
	}
	match := []feed.Match{{Role: "procurement", Kind: "risk", Score: .7, Insight: "stale role"}}
	if ok, err := f.store.CompleteNewsDelivery(context.Background(), claimed[0], match); err != nil || ok {
		t.Fatalf("stale role completion ok=%v err=%v, want requeued", ok, err)
	}
	var failureCount int
	if err := f.pool.QueryRow(context.Background(), `SELECT failures FROM news_deliveries WHERE id=$1`, claimed[0].ID).Scan(&failureCount); err != nil {
		t.Fatalf("read failure count after role requeue: %v", err)
	}
	if failureCount != 0 {
		t.Fatalf("role requeue counted as %d failures, want zero", failureCount)
	}
	if err := f.pipeline.processDeliveries(context.Background()); err != nil {
		t.Fatalf("finish after role removal: %v", err)
	}
	var count int
	if err := f.pool.QueryRow(context.Background(), `SELECT count(*) FROM feed_items WHERE user_id=$1 AND news_id=$2 AND active`, f.userID, claimed[0].NewsID).Scan(&count); err != nil {
		t.Fatalf("count published rows: %v", err)
	}
	if count != 0 {
		t.Fatalf("published %d rows after role removal, want none", count)
	}
}

func TestDeliveryStopsAfterEightFailuresAndOtherNewsContinues(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	firstNewsID, _, err := f.store.UpsertNews(context.Background(), f.news)
	if err != nil {
		t.Fatalf("enqueue first news: %v", err)
	}
	second := f.news
	second.ExternalID = "fixture-2"
	second.Title = "Second fixture"
	secondNewsID, _, err := f.store.UpsertNews(context.Background(), second)
	if err != nil {
		t.Fatalf("enqueue second news: %v", err)
	}
	var failedDeliveryID int64
	for failure := 1; failure <= 8; failure++ {
		claims, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
		if err != nil || len(claims) != 1 || claims[0].NewsID != firstNewsID {
			t.Fatalf("failure %d claim=%v err=%v", failure, claims, err)
		}
		failedDeliveryID = claims[0].ID
		if err := f.store.RetryNewsDelivery(context.Background(), claims[0], "rank_failed"); err != nil {
			t.Fatalf("record failure %d: %v", failure, err)
		}
		if _, err := f.pool.Exec(context.Background(), `UPDATE news_deliveries SET next_attempt_at=now()-interval '1 second' WHERE id=$1`, failedDeliveryID); err != nil {
			t.Fatalf("make failure %d immediately due: %v", failure, err)
		}
	}
	var state, errorCode string
	var failures int
	if err := f.pool.QueryRow(context.Background(), `SELECT state,last_error,failures FROM news_deliveries WHERE id=$1`, failedDeliveryID).Scan(&state, &errorCode, &failures); err != nil {
		t.Fatalf("read terminal delivery: %v", err)
	}
	if state != "failed" || errorCode != "rank_failed" || failures != 8 {
		t.Fatalf("terminal delivery state=%q error=%q failures=%d", state, errorCode, failures)
	}
	claims, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(claims) != 1 || claims[0].NewsID != secondNewsID {
		t.Fatalf("other news claim=%v err=%v, want second news", claims, err)
	}
	if ok, err := f.store.CompleteNewsDelivery(context.Background(), claims[0], nil); err != nil || !ok {
		t.Fatalf("complete second news ok=%v err=%v", ok, err)
	}
	claims, err = f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(claims) != 0 {
		t.Fatalf("failed job was claimed again: claims=%v err=%v", claims, err)
	}
}

func TestExpiredLeasesCountTowardFailureLimit(t *testing.T) {
	f := newIngestFixture(t)
	f.news.SourceID = f.source
	newsID, _, err := f.store.UpsertNews(context.Background(), f.news)
	if err != nil {
		t.Fatalf("enqueue news: %v", err)
	}
	claims, err := f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(claims) != 1 {
		t.Fatalf("initial claim=%v err=%v", claims, err)
	}
	for expired := 1; expired <= 7; expired++ {
		current := claims[0]
		if _, err := f.pool.Exec(context.Background(), `UPDATE news_deliveries SET lease_until=now()-interval '1 second' WHERE id=$1`, current.ID); err != nil {
			t.Fatalf("expire lease %d: %v", expired, err)
		}
		claims, err = f.store.ClaimNewsDeliveries(context.Background(), 1)
		if err != nil || len(claims) != 1 || claims[0].NewsID != newsID {
			t.Fatalf("reclaim after lease %d: claims=%v err=%v", expired, claims, err)
		}
	}
	if _, err := f.pool.Exec(context.Background(), `UPDATE news_deliveries SET lease_until=now()-interval '1 second' WHERE id=$1`, claims[0].ID); err != nil {
		t.Fatalf("expire eighth claim: %v", err)
	}
	claims, err = f.store.ClaimNewsDeliveries(context.Background(), 1)
	if err != nil || len(claims) != 0 {
		t.Fatalf("eighth expired claim was retried: claims=%v err=%v", claims, err)
	}
	var state, code string
	var failures int
	if err := f.pool.QueryRow(context.Background(), `SELECT state,last_error,failures FROM news_deliveries WHERE news_id=$1`, newsID).Scan(&state, &code, &failures); err != nil {
		t.Fatalf("read failed lease: %v", err)
	}
	if state != "failed" || code != "lease_expired" || failures != 8 {
		t.Fatalf("expired delivery state=%q code=%q failures=%d", state, code, failures)
	}
}
