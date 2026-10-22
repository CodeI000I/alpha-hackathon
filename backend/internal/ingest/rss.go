package ingest

import (
	"context"
	"encoding/xml"
	"fmt"
	"html"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"golang.org/x/net/html/charset"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// RSSFetcher читает RSS 2.0 и Atom. URL ленты берётся из sources.config.feed_url.
type RSSFetcher struct {
	Client *http.Client
}

const maxFeed = 20 << 20 // байт; настоящие ленты — сотни килобайт

type feedDoc struct {
	Items []struct {
		GUID        string   `xml:"guid"`
		Links       []string `xml:"link"` // первый непустой: в item бывает ещё atom:link без текста
		Title       string   `xml:"title"`
		Description string   `xml:"description"`
		FullText    string   `xml:"full-text"` // yandex:full-text, rbc_news:full-text
		Encoded     string   `xml:"encoded"`   // content:encoded
		PubDate     string   `xml:"pubDate"`
	} `xml:"channel>item"`
	Entries []struct {
		ID    string `xml:"id"`
		Links []struct {
			Href string `xml:"href,attr"`
			Rel  string `xml:"rel,attr"`
		} `xml:"link"`
		Title     string `xml:"title"`
		Summary   string `xml:"summary"`
		Content   string `xml:"content"`
		Published string `xml:"published"`
		Updated   string `xml:"updated"`
	} `xml:"entry"`
}

func (f RSSFetcher) Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
	feedURL, _ := src.Config["feed_url"].(string)
	if feedURL == "" {
		return nil, fmt.Errorf("source %s: config.feed_url is empty", src.ID)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, feedURL, nil)
	if err != nil {
		return nil, err
	}
	// Часть СМИ отвечает 403 на User-Agent по умолчанию (Go-http-client).
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; SignalNewsBot/1.0)")
	resp, err := f.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("rss %s: %s", feedURL, resp.Status)
	}
	items, err := parseFeed(io.LimitReader(resp.Body, maxFeed), time.Now())
	if err != nil {
		return nil, fmt.Errorf("rss %s: %w", feedURL, err)
	}
	return items, nil
}

// parseFeed разбирает RSS 2.0 или Atom. Российские ленты бывают в windows-1251
// и с HTML-сущностями вроде &mdash;, поэтому разбор нестрогий.
func parseFeed(r io.Reader, now time.Time) ([]domain.NewsItem, error) {
	dec := xml.NewDecoder(r)
	dec.CharsetReader = charset.NewReaderLabel
	dec.Strict = false
	dec.Entity = xml.HTMLEntity
	var doc feedDoc
	if err := dec.Decode(&doc); err != nil {
		return nil, err
	}

	out := make([]domain.NewsItem, 0, len(doc.Items)+len(doc.Entries))
	add := func(id, link, title, summary, body, date string) {
		title = cleanText(title, feed.MaxTitle)
		if title == "" {
			return // оркестратор не принимает новость без заголовка
		}
		if id = strings.TrimSpace(id); id == "" {
			if id = link; id == "" {
				id = title
			}
		}
		out = append(out, domain.NewsItem{
			ExternalID: id, URL: link, Title: title,
			Summary: cleanText(summary, feed.MaxSummary), Body: cleanText(body, feed.MaxBody),
			PublishedAt: parseDate(date, now),
		})
	}
	for _, it := range doc.Items {
		link := ""
		for _, l := range it.Links {
			if link = strings.TrimSpace(l); link != "" {
				break
			}
		}
		body := it.FullText
		if body == "" {
			body = it.Encoded
		}
		add(it.GUID, link, it.Title, it.Description, body, it.PubDate)
	}
	for _, e := range doc.Entries {
		link := ""
		for _, l := range e.Links {
			if l.Rel == "" || l.Rel == "alternate" {
				link = strings.TrimSpace(l.Href)
				break
			}
		}
		date := e.Published
		if date == "" {
			date = e.Updated
		}
		add(e.ID, link, e.Title, e.Summary, e.Content, date)
	}
	return out, nil
}

var dateLayouts = []string{
	time.RFC1123Z, time.RFC1123, time.RFC3339,
	"Mon, 2 Jan 2006 15:04:05 -0700", "Mon, 2 Jan 2006 15:04:05 MST",
	"2 Jan 2006 15:04:05 -0700", "2 Jan 2006 15:04:05 MST",
}

// parseDate понимает даты RSS (RFC 822) и Atom (RFC 3339); нераспознанная дата — время сбора.
func parseDate(s string, now time.Time) time.Time {
	s = strings.TrimSpace(s)
	for _, layout := range dateLayouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t
		}
	}
	return now
}

var tagRe = regexp.MustCompile(`<[^>]*>`)

// cleanText превращает HTML из description/full-text в простой текст:
// фронтенд показывает summary как есть, а оркестратору разметка не нужна.
func cleanText(s string, max int) string {
	s = html.UnescapeString(tagRe.ReplaceAllString(s, " "))
	s = strings.Join(strings.Fields(s), " ")
	if r := []rune(s); len(r) > max {
		s = string(r[:max])
	}
	return s
}
