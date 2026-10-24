package ingest

import (
	"context"
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
