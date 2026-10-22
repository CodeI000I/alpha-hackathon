package ingest

import (
	"strings"
	"testing"
	"time"
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
		"</item></channel></rss>"
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
