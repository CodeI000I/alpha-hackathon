package ingest

import (
	"context"
	"encoding/xml"
	"fmt"
	"html"
	"io"
	"net"
	"net/http"
	"net/mail"
	"net/url"
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

const maxFeed = 8 << 20 // байт; настоящие ленты — сотни килобайт

type feedDoc struct {
	XMLName xml.Name
	Items   []struct {
		GUID        string   `xml:"guid"`
		Links       []string `xml:"link"` // первый непустой: в item бывает ещё atom:link без текста
		Title       string   `xml:"title"`
		Description string   `xml:"description"`
		FullText    string   `xml:"full-text"` // yandex:full-text, rbc_news:full-text
		Encoded     string   `xml:"encoded"`   // content:encoded
		PubDate     string   `xml:"pubDate"`
		Categories  []string `xml:"category"`
	} `xml:"channel>item"`
	Entries []struct {
		ID    string `xml:"id"`
		Links []struct {
			Href string `xml:"href,attr"`
			Rel  string `xml:"rel,attr"`
		} `xml:"link"`
		Title      string `xml:"title"`
		Summary    string `xml:"summary"`
		Content    string `xml:"content"`
		Published  string `xml:"published"`
		Updated    string `xml:"updated"`
		Categories []struct {
			Term string `xml:"term,attr"`
		} `xml:"category"`
	} `xml:"entry"`
}

func (f RSSFetcher) Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
	feedURL, _ := src.Config["feed_url"].(string)
	if feedURL == "" {
		return nil, fmt.Errorf("source %s: config.feed_url is empty", src.ID)
	}
	parsedURL, err := url.ParseRequestURI(feedURL)
	if err != nil || (parsedURL.Scheme != "http" && parsedURL.Scheme != "https") || parsedURL.Host == "" || parsedURL.User != nil || !publicFeedHost(parsedURL.Hostname()) {
		return nil, fmt.Errorf("source %s: config.feed_url must be a public HTTP(S) URL", src.ID)
	}
	https443 := func(value *url.URL) bool {
		return value.Scheme == "https" && value.User == nil &&
			(value.Port() == "" || value.Port() == "443") && !strings.HasSuffix(value.Host, ":")
	}
	contentPolicy := ""
	if raw, configured := src.Config["content_policy"]; configured {
		var ok bool
		contentPolicy, ok = raw.(string)
		if !ok || (contentPolicy != "metadata_only" && contentPolicy != "feed_content") {
			return nil, fmt.Errorf("source %s: config.content_policy must be metadata_only or feed_content", src.ID)
		}
	}
	var articleHosts map[string]bool
	if raw, configured := src.Config["article_hosts"]; configured {
		hosts, ok := raw.([]any) // JSON arrays in sources.config decode to []any.
		if !ok || len(hosts) == 0 {
			return nil, fmt.Errorf("source %s: config.article_hosts must be a nonempty array", src.ID)
		}
		articleHosts = make(map[string]bool, len(hosts))
		for _, value := range hosts {
			host, ok := value.(string)
			if !ok || host == "" || host != strings.TrimSpace(host) || strings.ContainsAny(host, "/:@?#\\") || !publicFeedHost(host) {
				return nil, fmt.Errorf("source %s: config.article_hosts contains an invalid host", src.ID)
			}
			articleHosts[strings.ToLower(host)] = true
		}
		if !https443(parsedURL) || !articleHosts[strings.ToLower(parsedURL.Hostname())] {
			return nil, fmt.Errorf("source %s: curated feed must use an approved HTTPS origin", src.ID)
		}
	}
	var categories []string
	if raw, configured := src.Config["categories"]; configured {
		values, ok := raw.([]any)
		if !ok || len(values) == 0 {
			return nil, fmt.Errorf("source %s: config.categories must be a nonempty array", src.ID)
		}
		for _, value := range values {
			category, ok := value.(string)
			if !ok || strings.TrimSpace(category) == "" {
				return nil, fmt.Errorf("source %s: config.categories contains an invalid category", src.ID)
			}
			categories = append(categories, strings.TrimSpace(category))
		}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, feedURL, nil)
	if err != nil {
		return nil, err
	}
	// Часть СМИ отвечает 403 на User-Agent по умолчанию (Go-http-client).
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; SignalNewsBot/1.0)")
	client := f.Client
	if client == nil {
		client = http.DefaultClient
	}
	clientCopy := *client
	priorRedirect := clientCopy.CheckRedirect
	clientCopy.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if req.URL.User != nil || (req.URL.Scheme != "http" && req.URL.Scheme != "https") ||
			(parsedURL.Scheme == "https" && req.URL.Scheme != "https") || !publicFeedHost(req.URL.Hostname()) {
			return fmt.Errorf("rss redirect to non-public URL rejected")
		}
		if len(via) >= 10 {
			return fmt.Errorf("too many redirects")
		}
		if articleHosts != nil && (!https443(req.URL) || !strings.EqualFold(req.URL.Hostname(), parsedURL.Hostname())) {
			return fmt.Errorf("curated rss redirect to another origin rejected")
		}
		if priorRedirect != nil {
			return priorRedirect(req, via)
		}
		return nil
	}
	resp, err := clientCopy.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("rss %s: %s", feedURL, resp.Status)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxFeed+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxFeed {
		return nil, fmt.Errorf("rss source %s: feed exceeds %d bytes", src.ID, maxFeed)
	}
	items, err := parseFeed(strings.NewReader(string(body)), time.Now(), categories...)
	if err != nil {
		return nil, fmt.Errorf("rss %s: %w", feedURL, err)
	}
	accepted := items[:0]
	for _, item := range items {
		if articleHosts != nil {
			article, err := url.Parse(item.URL)
			if err != nil || !https443(article) || strings.Contains(item.URL, "#") ||
				!articleHosts[strings.ToLower(article.Hostname())] {
				continue
			}
		}
		if item.URL == "" && item.ExternalID == item.Title {
			return nil, fmt.Errorf("rss source %s: item has no stable identity", src.ID)
		}
		if contentPolicy == "metadata_only" {
			item.Body = ""
		}
		accepted = append(accepted, item)
	}
	return accepted, nil
}

func publicFeedHost(host string) bool {
	if strings.EqualFold(host, "localhost") || strings.HasSuffix(strings.ToLower(host), ".localhost") {
		return false
	}
	if ip := net.ParseIP(host); ip != nil {
		return ip.IsGlobalUnicast() && !ip.IsPrivate() && !ip.IsLoopback() && !ip.IsLinkLocalUnicast()
	}
	return host != ""
}

// parseFeed разбирает RSS 2.0 или Atom. Российские ленты бывают в windows-1251
// и с HTML-сущностями вроде &mdash;, поэтому разбор нестрогий.
func parseFeed(r io.Reader, now time.Time, categories ...string) ([]domain.NewsItem, error) {
	dec := xml.NewDecoder(r)
	dec.CharsetReader = charset.NewReaderLabel
	dec.Strict = false
	dec.Entity = xml.HTMLEntity
	var doc feedDoc
	if err := dec.Decode(&doc); err != nil {
		return nil, err
	}
	if doc.XMLName.Local != "rss" && doc.XMLName.Local != "feed" {
		return nil, fmt.Errorf("expected RSS or Atom document, got %q", doc.XMLName.Local)
	}
	wanted := make(map[string]bool, len(categories))
	for _, category := range categories {
		wanted[category] = true
	}

	out := make([]domain.NewsItem, 0, len(doc.Items)+len(doc.Entries))
	var parseErr error
	add := func(id, link, title, summary, body, date string) {
		if parseErr != nil {
			return
		}
		title = cleanText(title, feed.MaxTitle)
		if title == "" {
			return // оркестратор не принимает новость без заголовка
		}
		if id = strings.TrimSpace(id); id == "" {
			id = strings.TrimSpace(link)
			if id == "" {
				id = title
			}
		}
		if id == "" {
			parseErr = fmt.Errorf("feed item has no stable identity")
			return
		}
		publishedAt, ok := parseFeedDate(date)
		if !ok {
			parseErr = fmt.Errorf("feed item has no valid publication date")
			return
		}
		out = append(out, domain.NewsItem{
			ExternalID: id, URL: link, Title: title,
			Summary: cleanText(summary, feed.MaxSummary), Body: cleanText(body, feed.MaxBody),
			PublishedAt: publishedAt,
		})
	}
	for _, it := range doc.Items {
		matches := len(wanted) == 0
		for _, category := range it.Categories {
			matches = matches || wanted[strings.TrimSpace(category)]
		}
		if !matches {
			continue
		}
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
		if parseErr != nil {
			return nil, parseErr
		}
	}
	for _, e := range doc.Entries {
		matches := len(wanted) == 0
		for _, category := range e.Categories {
			matches = matches || wanted[strings.TrimSpace(category.Term)]
		}
		if !matches {
			continue
		}
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
		if parseErr != nil {
			return nil, parseErr
		}
	}
	return out, nil
}

func parseFeedDate(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	if len(value) >= 10 && value[4] == '-' {
		t, err := time.Parse(time.RFC3339, value)
		return t, err == nil
	}
	parts := strings.Fields(value)
	zone := parts[len(parts)-1]
	numericZone := len(zone) == 5 && (zone[0] == '+' || zone[0] == '-') && allDigits(zone[1:])
	if !numericZone && zone != "UTC" && zone != "GMT" && zone != "UT" {
		return time.Time{}, false
	}
	for _, layout := range dateLayouts {
		if t, err := time.Parse(layout, value); err == nil {
			return t, true
		}
	}
	if t, err := mail.ParseDate(value); err == nil {
		return t, true
	}
	return time.Time{}, false
}

func allDigits(value string) bool {
	for _, r := range value {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
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
