"""Узкое извлечение статьи из HTML пресс-релиза Банка России."""

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import unquote, urlsplit


_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl", "dt", "dd",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "li", "main", "ol", "p", "pre", "section", "ul",
}
_IGNORED_TAGS = {"script", "style", "nav"}
_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)


def _normalized_text(parts):
    text = "".join(parts).replace("\xa0", " ").replace("\r", "\n")
    lines = []
    for raw_line in text.split("\n"):
        cells = [re.sub(r"\s+", " ", cell).strip() for cell in raw_line.split("\t")]
        line = "\t".join(cell for cell in cells if cell)
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def _published_day(text):
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month_name, year = match.groups()
    try:
        return date(int(year), _MONTHS[month_name.lower()], int(day)).isoformat()
    except ValueError:
        return None


def _pdf_href(attrs):
    href = attrs.get("href")
    if not href or any(char.isspace() or ord(char) < 32 for char in href) or "\\" in href:
        return None
    href = href.strip()
    try:
        parsed = urlsplit(href)
    except ValueError:
        return None
    path = unquote(parsed.path).lower()
    if parsed.scheme.lower() not in ("", "https") or not path.endswith(".pdf"):
        return None
    if "/search/" in path or "/content/savetopdf/" in path:
        return None
    return href


class _CbrArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.body_parts = []
        self.title_parts = []
        self.date_parts = []
        self.attachments = []
        self.no_follow = False
        self.landing_count = 0
        self.body_count = 0
        self.active_landing = None
        self.closed_landing = False
        self.structural_error = False
        self._frame_id = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {name.lower(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())

        if tag == "body":
            self.body_count += 1
            if self.body_count > 1:
                self.structural_error = True

        if tag == "meta" and attributes.get("name", "").lower() == "robots":
            directives = set(re.findall(r"[a-z]+", attributes.get("content", "").lower()))
            if directives.intersection({"nofollow", "none"}):
                self.no_follow = True

        if tag == "br" and self._captures_body():
            self.body_parts.append("\n")
        if tag in _VOID_TAGS:
            return

        self._frame_id += 1
        frame = {
            "id": self._frame_id,
            "tag": tag,
            "landing": False,
            "title": tag == "h1" and not self.title_parts,
            "date": "news-info-line_date" in classes and not self.date_parts,
            "ignored": tag in _IGNORED_TAGS,
            "row": tag == "tr",
        }
        if "landing-text" in classes:
            self.landing_count += 1
            frame["landing"] = True
            if self.active_landing is None and not self.closed_landing:
                self.active_landing = frame["id"]
            else:
                self.structural_error = True

        self.stack.append(frame)
        if self._captures_body():
            if tag in _BLOCK_TAGS or tag == "tr":
                self.body_parts.append("\n")

            if tag == "a" and "nofollow" not in attributes.get("rel", "").lower().split():
                href = _pdf_href(attributes)
                if href and href not in self.attachments:
                    self.attachments.append(href)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID_TAGS:
            return
        matching = next(
            (index for index in range(len(self.stack) - 1, -1, -1)
             if self.stack[index]["tag"] == tag),
            None,
        )
        if matching is None:
            self.structural_error = True
            return
        if matching != len(self.stack) - 1:
            self.structural_error = True
        for frame in reversed(self.stack[matching:]):
            if self._captures_body() and frame["tag"] in _BLOCK_TAGS:
                self.body_parts.append("\n")
            if self._captures_body() and frame["tag"] in {"td", "th"}:
                self.body_parts.append("\t")
            if self._captures_body() and frame["row"]:
                self.body_parts.append("\n")
            if frame["landing"] and frame["id"] == self.active_landing:
                self.active_landing = None
                self.closed_landing = True
        del self.stack[matching:]

    def handle_data(self, data):
        if any(frame["title"] for frame in self.stack):
            self.title_parts.append(data)
        if any(frame["date"] for frame in self.stack):
            self.date_parts.append(data)
        if self._captures_body():
            self.body_parts.append(data)

    def _captures_body(self):
        return self.active_landing is not None and not any(
            frame["ignored"] for frame in self.stack
        )

    def result(self):
        body = _normalized_text(self.body_parts)
        title = _normalized_text(self.title_parts)
        date_text = _normalized_text(self.date_parts)
        complete = (
            self.landing_count == 1
            and self.closed_landing
            and self.active_landing is None
            and body is not None
            and self.body_count <= 1
            and not self.structural_error
        )
        return {
            "title": title,
            "content_text": body,
            "published_date": _published_day(date_text),
            "attachments": [] if self.no_follow else self.attachments,
            "no_follow": self.no_follow,
            "complete": complete,
        }


def extract_article(html: str) -> dict:
    """Извлечь только известные поля страницы пресс-релиза ЦБ."""
    if not isinstance(html, str):
        raise TypeError("html must be a string")
    parser = _CbrArticleParser()
    parser.feed(html)
    parser.close()
    return parser.result()
