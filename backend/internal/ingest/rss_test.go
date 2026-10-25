package ingest

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

var now = time.Date(2026, 10, 22, 12, 0, 0, 0, time.UTC)

func TestParseRSS(t *testing.T) {
	// Как у РБК и Коммерсанта: HTML-сущности, atom:link в item, полный текст в rbc_news:full-text.
	feed := `<?xml version="1.0" encoding="utf-8"?>
	<rss version="2.0" xmlns:atom="https://www.w3.org/2005/Atom" xmlns:rbc_news="https://www.rbc.ru"><channel>
		<item>
			<guid isPermaLink="false">rbc-1</guid>
			<title>Ставка &mdash; 18%</title>
			<atom:link href="https://example.ru/self" rel="self"/>
			<link>https://example.ru/1</link>
			<description><![CDATA[<p>Банк России <b>повысил</b> ставку&nbsp;до 18%</p>]]></description>
			<rbc_news:full-text>Полный   текст
			новости</rbc_news:full-text>
			<pubDate>Thu, 22 Oct 2026 17:07:00 +0300</pubDate>
		</item>
		<item><title>Без guid</title><link>https://example.ru/2</link><pubDate>22 Oct 2026 10:00:00 GMT</pubDate></item>
		<item><title>  </title><link>https://example.ru/empty</link></item>
	</channel></rss>`
	items, err := parseFeed(strings.NewReader(feed), now)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 2 {
		t.Fatalf("want 2 items (one without title skipped), got %+v", items)
	}
	it := items[0]
	if it.ExternalID != "rbc-1" || it.URL != "https://example.ru/1" || it.Title != "Ставка — 18%" {
		t.Errorf("item 0: %+v", it)
	}
	if it.Summary != "Банк России повысил ставку до 18%" || it.Body != "Полный текст новости" {
		t.Errorf("text not cleaned: summary=%q body=%q", it.Summary, it.Body)
	}
	if !it.PublishedAt.Equal(time.Date(2026, 10, 22, 14, 7, 0, 0, time.UTC)) {
		t.Errorf("pubDate: %v", it.PublishedAt)
	}
	if items[1].ExternalID != "https://example.ru/2" || !items[1].PublishedAt.Equal(time.Date(2026, 10, 22, 10, 0, 0, 0, time.UTC)) {
		t.Errorf("item 1: %+v", items[1])
	}
}

func TestParseWindows1251(t *testing.T) {
	feed := "<?xml version=\"1.0\" encoding=\"windows-1251\"?>\n" +
		"<rss version=\"2.0\"><channel><item><title>\xcd\xee\xe2\xee\xf1\xf2\xfc</title>" +
		"<content:encoded xmlns:content=\"http://purl.org/rss/1.0/modules/content/\">&lt;p&gt;\xd2\xe5\xea\xf1\xf2&lt;/p&gt;</content:encoded>" +
		"<pubDate>Thu, 22 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>"
	items, err := parseFeed(strings.NewReader(feed), now)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Title != "Новость" || items[0].Body != "Текст" || items[0].ExternalID != "Новость" {
		t.Fatalf("got %+v", items)
	}
}

func TestParseAtom(t *testing.T) {
	// Как у kremlin.ru: Atom вместо RSS.
	feed := `<?xml version="1.0" encoding="utf-8"?>
	<feed xmlns="http://www.w3.org/2005/Atom">
		<title>Сайт Президента России</title>
		<link rel="self" href="http://kremlin.ru/events/all/feed"/>
		<entry>
			<id>http://kremlin.ru/events/president/news/1</id>
			<title>Указ о мерах поддержки</title>
			<link rel="alternate" href="http://kremlin.ru/events/president/news/1"/>
			<published>2026-10-22T11:10:00+04:00</published>
			<updated>2026-10-22T10:24:46+04:00</updated>
			<summary type="html">&lt;p&gt;Краткое описание&lt;/p&gt;</summary>
			<content type="html">&lt;p&gt;Полный текст указа&lt;/p&gt;</content>
		</entry>
	</feed>`
	items, err := parseFeed(strings.NewReader(feed), now)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("got %+v", items)
	}
	it := items[0]
	if it.ExternalID != "http://kremlin.ru/events/president/news/1" || it.URL != it.ExternalID ||
		it.Summary != "Краткое описание" || it.Body != "Полный текст указа" ||
		!it.PublishedAt.Equal(time.Date(2026, 10, 22, 7, 10, 0, 0, time.UTC)) {
		t.Errorf("entry: %+v", it)
	}
}

func TestParseDateFallback(t *testing.T) {
	if got := parseDate("вчера", now); !got.Equal(now) {
		t.Fatalf("got %v", got)
	}
}

func TestCleanTextLimit(t *testing.T) {
	if got := cleanText(strings.Repeat("я", 10), 3); got != "яяя" {
		t.Fatalf("got %q", got)
	}
}

type rssTransport func(*http.Request) (*http.Response, error)

func (f rssTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func fixtureRSS(body string) RSSFetcher {
	return RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
	})}}
}

func TestRSSDatesDoNotBecomeFetchTime(t *testing.T) {
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for _, date := range []string{"Fri, 23 Oct 2026 15:30:00 +0300", "Fri, 23 Oct 2026 12:30:00 GMT"} {
		t.Run(date, func(t *testing.T) {
			fetcher := fixtureRSS(fmt.Sprintf(`<rss><channel><item><guid>id-1</guid><title>Title</title><pubDate>%s</pubDate></item></channel></rss>`, date))
			items, err := fetcher.Fetch(context.Background(), src)
			want := time.Date(2026, 10, 23, 12, 30, 0, 0, time.UTC)
			if err != nil || len(items) != 1 || !items[0].PublishedAt.Equal(want) {
				t.Fatalf("got %#v, %v; want original publication time %s", items, err, want)
			}
		})
	}
}

func TestRSSRejectsInvalidInput(t *testing.T) {
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for name, body := range map[string]string{
		"unknown date":     `<rss><channel><item><guid>x</guid><title>T</title><pubDate>unknown</pubDate></item></channel></rss>`,
		"missing identity": `<rss><channel><item><title>T</title><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>`,
		"wrong root":       `<html><body>Provider failed</body></html>`,
		"oversize":         `<rss><channel><title>` + strings.Repeat("x", 8<<20) + `</title></channel></rss>`,
	} {
		t.Run(name, func(t *testing.T) {
			items, err := fixtureRSS(body).Fetch(context.Background(), src)
			if err == nil {
				t.Fatalf("accepted invalid feed: %#v", items)
			}
		})
	}
}

func TestAlfaUnavailableIsNotSuccessfulEmptyFetch(t *testing.T) {
	if _, err := (AlfaFetcher{}).Fetch(context.Background(), postgres.SourceConfig{ID: "fixture"}); err == nil {
		t.Fatal("unconfigured adapter must expose unavailability")
	}
}

func TestRSSAmbiguousZoneDoesNotDependOnWorkerTimezone(t *testing.T) {
	previous := time.Local
	t.Cleanup(func() { time.Local = previous })
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for _, location := range []*time.Location{time.UTC, time.FixedZone("PST", -8*3600)} {
		time.Local = location
		body := `<rss><channel><item><guid>x</guid><title>T</title><pubDate>Fri, 23 Oct 2026 12:30:00 PST</pubDate></item></channel></rss>`
		if _, err := fixtureRSS(body).Fetch(context.Background(), src); err == nil {
			t.Fatalf("ambiguous PST accepted with worker local zone %s", location)
		}
	}
}

func TestRSSCuratedSourceAcceptsOnlyAllowedHTTPSArticles(t *testing.T) {
	var config map[string]any
	if err := json.Unmarshal([]byte(`{"feed_url":"https://agency.example/rss","article_hosts":["agency.example","www.agency.example"]}`), &config); err != nil {
		t.Fatal(err)
	}
	src := postgres.SourceConfig{ID: "official", Config: config}
	for _, article := range []string{
		"https://agency.example/news/1", "https://www.agency.example:443/news/1?view=full",
		"https://external.example/news/1", "https://agency.example.external.example/news/1",
		"http://agency.example/news/1", "https://user@agency.example/news/1",
		"https://agency.example:8443/news/1", "https://agency.example:/news/1",
		"https://agency.example/news/1#fragment", "https://agency.example/news/1#",
		"/news/1", "javascript:alert(1)",
	} {
		t.Run(article, func(t *testing.T) {
			body := fmt.Sprintf(`<rss><channel><item><guid>id-1</guid><title>Title</title><link>%s</link><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>`, article)
			items, err := fixtureRSS(body).Fetch(context.Background(), src)
			want := 0
			if article == "https://agency.example/news/1" || article == "https://www.agency.example:443/news/1?view=full" {
				want = 1
			}
			if err != nil || len(items) != want {
				t.Fatalf("article %q: got %d items, %v; want %d", article, len(items), err, want)
			}
		})
	}
}

func TestRSSRejectsInvalidArticleHostPolicy(t *testing.T) {
	for _, raw := range []any{nil, "agency.example", []any{}, []any{42}, []any{""}, []any{"agency.example:443"}, []any{"localhost"}} {
		src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{
			"feed_url": "https://feed.example/rss", "article_hosts": raw,
		}}
		if _, err := fixtureRSS(`<rss><channel/></rss>`).Fetch(context.Background(), src); err == nil {
			t.Fatalf("invalid article_hosts accepted: %#v", raw)
		}
	}
}

func TestRSSCuratedFeedRequiresApprovedHTTPSOriginBeforeFetching(t *testing.T) {
	for _, feedURL := range []string{"https://external.example/rss", "http://agency.example/rss", "https://agency.example:8443/rss", "https://agency.example:/rss"} {
		requests := 0
		fetcher := RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
			requests++
			return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
		})}}
		src := postgres.SourceConfig{ID: "official", Config: map[string]any{
			"feed_url": feedURL, "article_hosts": []any{"agency.example"},
		}}
		if _, err := fetcher.Fetch(context.Background(), src); err == nil || requests != 0 {
			t.Fatalf("unapproved curated feed %q: requests=%d, err=%v", feedURL, requests, err)
		}
	}
}

func TestRSSRejectsUnknownContentPolicyBeforeFetching(t *testing.T) {
	for _, policy := range []any{"metadata-only", "", nil, 42, map[string]any{"mode": "metadata_only"}} {
		requests := 0
		fetcher := RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
			requests++
			return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
		})}}
		src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{
			"feed_url": "https://feed.example/rss", "content_policy": policy,
		}}
		if _, err := fetcher.Fetch(context.Background(), src); err == nil || requests != 0 {
			t.Fatalf("invalid content policy %#v: requests=%d, err=%v", policy, requests, err)
		}
	}
}

func TestRSSCuratedFeedRedirectStaysOnOriginalOrigin(t *testing.T) {
	for _, target := range []string{"https://external.example/rss", "https://www.agency.example/rss", "https://agency.example:8443/rss", "https://agency.example:/rss", "https://agency.example:443/new-rss"} {
		t.Run(target, func(t *testing.T) {
			requests := 0
			fetcher := RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
				requests++
				if requests == 1 {
					return &http.Response{StatusCode: 302, Header: http.Header{"Location": []string{target}}, Body: io.NopCloser(strings.NewReader(""))}, nil
				}
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
			})}}
			src := postgres.SourceConfig{ID: "official", Config: map[string]any{
				"feed_url": "https://agency.example/rss", "article_hosts": []any{"agency.example", "www.agency.example"},
			}}
			_, err := fetcher.Fetch(context.Background(), src)
			if target == "https://agency.example:443/new-rss" {
				if err != nil || requests != 2 {
					t.Fatalf("same origin redirect rejected: requests=%d, err=%v", requests, err)
				}
			} else if err == nil || requests != 1 {
				t.Fatalf("curated feed escaped origin: requests=%d, err=%v", requests, err)
			}
		})
	}
}

func TestRSSMetadataOnlyPolicyKeepsHeadlineAndSummaryWithoutFullText(t *testing.T) {
	body := `<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><guid>id-1</guid><title>Title</title><link>https://agency.example/news/1</link><description>Short announcement</description><content:encoded>Full licensed article</content:encoded><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>`
	for _, policy := range []string{"", "feed_content", "metadata_only"} {
		t.Run(policy, func(t *testing.T) {
			config := map[string]any{"feed_url": "https://feed.example/rss"}
			if policy != "" {
				config["content_policy"] = policy
			}
			items, err := fixtureRSS(body).Fetch(context.Background(), postgres.SourceConfig{ID: "fixture", Config: config})
			if err != nil || len(items) != 1 || items[0].Title != "Title" || items[0].Summary != "Short announcement" {
				t.Fatalf("got %+v, %v", items, err)
			}
			want := "Full licensed article"
			if policy == "metadata_only" {
				want = ""
			}
			if items[0].Body != want {
				t.Fatalf("body=%q; want %q", items[0].Body, want)
			}
		})
	}
}

func TestRSSRedirectPolicyCannotBeBypassedByPriorHandler(t *testing.T) {
	for _, target := range []string{"http://feed.example/other", "https://user@feed.example/other", "https://127.0.0.1/other", "https://localhost/other", "ftp://feed.example/other"} {
		t.Run(target, func(t *testing.T) {
			requests := 0
			fetcher := RSSFetcher{Client: &http.Client{
				CheckRedirect: func(*http.Request, []*http.Request) error { return nil },
				Transport: rssTransport(func(req *http.Request) (*http.Response, error) {
					requests++
					if requests > 1 {
						return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
					}
					return &http.Response{StatusCode: 302, Header: http.Header{"Location": []string{target}}, Body: io.NopCloser(strings.NewReader(""))}, nil
				}),
			}}
			_, err := fetcher.Fetch(context.Background(), postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}})
			if err == nil || requests != 1 {
				t.Fatalf("blocked redirect reached transport: requests=%d, err=%v", requests, err)
			}
		})
	}
}

func TestRSSRedirectLimitStillAppliesWithPriorHandler(t *testing.T) {
	requests := 0
	fetcher := RSSFetcher{Client: &http.Client{
		CheckRedirect: func(*http.Request, []*http.Request) error { return nil },
		Transport: rssTransport(func(req *http.Request) (*http.Response, error) {
			requests++
			if requests > 10 {
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
			}
			return &http.Response{StatusCode: 302, Header: http.Header{"Location": []string{fmt.Sprintf("https://feed.example/next-%d", requests)}}, Body: io.NopCloser(strings.NewReader(""))}, nil
		}),
	}}
	_, err := fetcher.Fetch(context.Background(), postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}})
	if err == nil || requests != 10 {
		t.Fatalf("redirect limit bypassed: requests=%d, err=%v", requests, err)
	}
}

func TestRSSSafeRedirectPreservesExistingHandler(t *testing.T) {
	requests, redirects := 0, 0
	fetcher := RSSFetcher{Client: &http.Client{
		CheckRedirect: func(*http.Request, []*http.Request) error { redirects++; return nil },
		Transport: rssTransport(func(req *http.Request) (*http.Response, error) {
			requests++
			if requests == 1 {
				return &http.Response{StatusCode: 302, Header: http.Header{"Location": []string{"https://cdn.example/rss"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
			}
			return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
		}),
	}}
	_, err := fetcher.Fetch(context.Background(), postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}})
	if err != nil || requests != 2 || redirects != 1 {
		t.Fatalf("safe redirect failed: requests=%d, redirects=%d, err=%v", requests, redirects, err)
	}
}

func TestRSSCategoryFilterAcceptsAnyMatchingCategoryBeforeDateValidation(t *testing.T) {
	body := `<rss><channel>
		<item><guid>economy</guid><title>Economy</title><category>Экономика</category><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item>
		<item><guid>sport</guid><title>Sport</title><category>Спорт</category><pubDate>unknown</pubDate></item>
		<item><guid>mixed</guid><title>Mixed</title><category>Политика</category><category> Экономика </category><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item>
		<item><guid>uncategorized</guid><title>No category</title><pubDate>unknown</pubDate></item>
	</channel></rss>`
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{
		"feed_url": "https://feed.example/rss", "categories": []any{"Экономика"},
	}}
	items, err := fixtureRSS(body).Fetch(context.Background(), src)
	if err != nil || len(items) != 2 || items[0].ExternalID != "economy" || items[1].ExternalID != "mixed" {
		t.Fatalf("category filter got %+v, %v", items, err)
	}
}

func TestRSSCategoryFilterPreservesUnconfiguredFeedsAndAcceptsMultipleChoices(t *testing.T) {
	body := `<rss><channel>
		<item><guid>economy</guid><title>Economy</title><category>Экономика</category><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item>
		<item><guid>sport</guid><title>Sport</title><category>Спорт</category><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item>
		<item><guid>none</guid><title>No category</title><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item>
	</channel></rss>`
	for _, configured := range []bool{false, true} {
		config := map[string]any{"feed_url": "https://feed.example/rss"}
		want := 3
		if configured {
			config["categories"] = []any{"Экономика", "Спорт"}
			want = 2
		}
		items, err := fixtureRSS(body).Fetch(context.Background(), postgres.SourceConfig{ID: "fixture", Config: config})
		if err != nil || len(items) != want {
			t.Fatalf("configured=%t: got %+v, %v; want %d items", configured, items, err, want)
		}
	}
}

func TestRSSCategoryFilterSupportsAtomTerms(t *testing.T) {
	body := `<feed xmlns="http://www.w3.org/2005/Atom">
		<entry><id>economy</id><title>Economy</title><category term="Политика"/><category term="Экономика"/><published>2026-10-23T12:30:00Z</published></entry>
		<entry><id>sport</id><title>Sport</title><category term="Спорт"/><published>unknown</published></entry>
	</feed>`
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{
		"feed_url": "https://feed.example/rss", "categories": []any{"Экономика"},
	}}
	items, err := fixtureRSS(body).Fetch(context.Background(), src)
	if err != nil || len(items) != 1 || items[0].ExternalID != "economy" {
		t.Fatalf("Atom category filter got %+v, %v", items, err)
	}
}

func TestRSSRejectsInvalidCategoryPolicyBeforeFetching(t *testing.T) {
	for _, raw := range []any{nil, "Экономика", []any{}, []any{42}, []any{""}, []any{" "}} {
		requests := 0
		fetcher := RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
			requests++
			return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`<rss><channel/></rss>`))}, nil
		})}}
		src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{
			"feed_url": "https://feed.example/rss", "categories": raw,
		}}
		if _, err := fetcher.Fetch(context.Background(), src); err == nil || requests != 0 {
			t.Fatalf("invalid categories %#v: requests=%d, err=%v", raw, requests, err)
		}
	}
}
