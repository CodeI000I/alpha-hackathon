package ingest

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

var curatedSourceFixtures = []struct {
	id, feedURL, host, class, contentPolicy string
}{
	{"S077", "https://www.cbr.ru/rss/RssPress", "www.cbr.ru", "official_primary", "metadata_only"},
	{"S136", "https://www.interfax.ru/rss", "www.interfax.ru", "established_media", "metadata_only"},
	{"S142", "https://frankmedia.ru/feed", "frankmedia.ru", "industry_media", "feed_content"},
}

func TestCuratedSourceConfiguration(t *testing.T) {
	f := newIngestFixture(t)
	sources, err := f.store.EnabledSources(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, source := range sources {
		if source.Adapter != "rss" {
			continue
		}
		ids = append(ids, source.ID)
		if len(ids) > len(curatedSourceFixtures) {
			t.Fatalf("unexpected enabled RSS source %s", source.ID)
		}
		want := curatedSourceFixtures[len(ids)-1]
		if source.ID != want.id || source.Config["feed_url"] != want.feedURL ||
			source.Config["source_class"] != want.class || source.Config["content_policy"] != want.contentPolicy ||
			fmt.Sprint(source.Config["priority"]) != fmt.Sprint(len(ids)) {
			t.Fatalf("source at priority %d: %+v, want %+v", len(ids), source, want)
		}
		hosts, ok := source.Config["article_hosts"].([]any)
		if !ok || len(hosts) != 1 || hosts[0] != want.host {
			t.Fatalf("source %s article hosts = %#v, want %s", source.ID, hosts, want.host)
		}
		if source.ID == "S136" {
			categories, ok := source.Config["categories"].([]any)
			if !ok || len(categories) != 1 || categories[0] != "Экономика" {
				t.Fatalf("Interfax categories = %#v, want Экономика", categories)
			}
		}
	}
	if !slices.Equal(ids, []string{"S077", "S136", "S142"}) {
		t.Fatalf("enabled RSS sources = %v, want three curated publishers in priority order", ids)
	}
}

func TestCuratedRSSCollectRankFeed(t *testing.T) {
	for _, failedSource := range []string{"", "S077"} {
		t.Run("failed="+failedSource, func(t *testing.T) {
			f := newIngestFixture(t)
			ctx := context.Background()
			// Only this fixture's new deliveries are relevant, not pre-existing backfill.
			if _, err := f.pool.Exec(ctx, `DELETE FROM news_deliveries WHERE user_id=$1`, f.userID); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				_, _ = f.pool.Exec(context.Background(), `DELETE FROM news_items WHERE external_id LIKE $1`, f.source+"-%")
			})
			user, err := f.store.GetUser(ctx, f.userID)
			if err != nil {
				t.Fatal(err)
			}
			f.pipeline.Ranker = &fakeRanker{companyID: *user.CompanyID, calls: map[int64][][]string{}, answer: func(request feed.Request) ([]feed.Match, error) {
				wantBody := ""
				if request.News.SourceID == "S142" {
					wantBody = "Synthetic full feed content."
				}
				if request.News.Summary != "Synthetic "+request.News.SourceID+" announcement." || request.News.Body != wantBody ||
					!slices.Equal(request.Roles, []string{"procurement"}) {
					t.Errorf("ranker did not receive source context and user role: %+v", request)
				}
				return f.ranker.Rank(ctx, request)
			}}
			fixtures := make(map[string]string)
			for _, source := range curatedSourceFixtures {
				fixtures[source.feedURL] = fmt.Sprintf(`<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
					<item><guid>%s-%s</guid><title>Synthetic %s update</title><link>https://%s/fixture/%s</link>
					<description><![CDATA[<p>Synthetic %s announcement.</p>]]></description>
					<content:encoded>Synthetic full feed content.</content:encoded>
					<category>Экономика</category><pubDate>Fri, 23 Oct 2026 15:30:00 +0300</pubDate></item>`,
					f.source, source.id, source.id, source.host, f.source, source.id)
				if source.id == "S136" {
					fixtures[source.feedURL] += `<item><guid>sport</guid><title>Unrelated sports</title><category>Спорт</category><pubDate>unknown</pubDate></item>`
				}
				fixtures[source.feedURL] += `</channel></rss>`
			}
			var requested []string
			f.pipeline.Fetchers = map[string]Fetcher{"rss": RSSFetcher{Client: &http.Client{
				Transport: rssTransport(func(request *http.Request) (*http.Response, error) {
					url := request.URL.String()
					requested = append(requested, url)
					body, ok := fixtures[url]
					if !ok {
						t.Errorf("unexpected feed request %s", url)
					}
					status := http.StatusOK
					if !ok || failedSource == "S077" && url == curatedSourceFixtures[0].feedURL {
						status, body = http.StatusServiceUnavailable, "synthetic source outage"
					}
					return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
				}),
			}}}
			f.setRankResults(rankResult{matches: []feed.Match{{Role: "procurement", Kind: "risk", Score: .8, Insight: "Synthetic supported impact"}}})
			for cycle := 1; cycle <= 2; cycle++ {
				if err := f.pipeline.Collect(ctx); err != nil {
					t.Fatal(err)
				}
				if err := f.pipeline.Rank(ctx); err != nil {
					t.Fatal(err)
				}
				items, err := f.store.Feed(ctx, f.userID, "procurement", 10)
				if err != nil {
					t.Fatal(err)
				}
				wantCount := 3
				if failedSource != "" {
					wantCount--
				}
				if len(items) != wantCount || f.ranker.callCount() != wantCount {
					t.Fatalf("cycle %d: feed items=%d rank calls=%d, want %d each", cycle, len(items), f.ranker.callCount(), wantCount)
				}
				seen := make(map[string]bool)
				for _, item := range items {
					seen[item.News.SourceID] = true
					wantBody := ""
					if item.News.SourceID == "S142" {
						wantBody = "Synthetic full feed content."
					}
					var storedBody string
					if err := f.pool.QueryRow(ctx, `SELECT body FROM news_items WHERE id=$1`, item.News.ID).Scan(&storedBody); err != nil {
						t.Fatal(err)
					}
					if storedBody != wantBody {
						t.Fatalf("source %s stored body=%q, want %q", item.News.SourceID, storedBody, wantBody)
					}
					// Feed projects the announcement; full text stays in storage and Rank requests.
					if item.News.Title != "Synthetic "+item.News.SourceID+" update" ||
						item.News.Summary != "Synthetic "+item.News.SourceID+" announcement." || item.News.Body != "" ||
						!item.News.PublishedAt.Equal(time.Date(2026, 10, 23, 12, 30, 0, 0, time.UTC)) ||
						item.Insight != "Synthetic supported impact" {
						t.Fatalf("metadata/date/analysis did not reach feed: %+v", item)
					}
				}
				for _, source := range curatedSourceFixtures {
					if seen[source.id] != (source.id != failedSource) {
						t.Fatalf("cycle %d source coverage = %v, failed source = %q", cycle, seen, failedSource)
					}
				}
				var newsCount int
				var maxRevision int64
				if err := f.pool.QueryRow(ctx, `SELECT count(*),COALESCE(max(revision),0) FROM news_items WHERE external_id LIKE $1`, f.source+"-%").Scan(&newsCount, &maxRevision); err != nil {
					t.Fatal(err)
				}
				if newsCount != wantCount || maxRevision != 1 {
					t.Fatalf("cycle %d created duplicates: news=%d maxRevision=%d", cycle, newsCount, maxRevision)
				}
			}
			wantURLs := []string{curatedSourceFixtures[0].feedURL, curatedSourceFixtures[1].feedURL, curatedSourceFixtures[2].feedURL}
			if !slices.Equal(requested, append(append([]string(nil), wantURLs...), wantURLs...)) {
				t.Fatalf("feed request priority/order = %v, want two ordered cycles", requested)
			}
		})
	}
}
