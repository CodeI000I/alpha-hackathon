"""Conservative static-HTML to SourceDocument conversion."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re

from .extraction_models import DocumentBlock, SourceDocument


CLEANER_VERSION = "html.semantic-blocks.v1"

_ERRORS = {
    "INPUT_INVALID": "The HTML input is invalid.",
    "INPUT_LIMIT": "The HTML input exceeds its limit.",
    "OUTPUT_LIMIT": "The cleaned document exceeds its limit.",
    "NO_CONTENT": "The HTML contains no usable content.",
}
_SUPPRESSED = {
    "script", "style", "head", "nav", "footer", "aside", "form", "template",
    "noscript", "iframe", "object", "embed",
}
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
_BLOCK = {
    "address", "article", "blockquote", "dd", "div", "dl", "dt", "figcaption",
    "figure", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main",
    "ol", "p", "pre", "section", "table", "tbody", "tfoot", "thead", "tr", "ul",
}


class HtmlCleanError(ValueError):
    def __init__(self, code: str) -> None:
        try:
            message = _ERRORS[code]
        except KeyError as exc:
            raise ValueError("Unsupported HTML cleaning error code") from exc
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CleanedDocument:
    document: SourceDocument
    incomplete_fields: tuple[str, ...]


@dataclass
class _Region:
    kind: str
    start: int
    end: int | None = None


class _SemanticParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self.stack: list[dict] = []
        self.open_positions: dict[str, list[int]] = {}
        self.regions: list[_Region] = []
        self.structural_error = False
        self.span_positions: list[int] = []

    def _suppressed(self) -> bool:
        return bool(self.stack and self.stack[-1]["suppressed"])

    def _in_pre(self) -> bool:
        return bool(self.stack and self.stack[-1]["pre"])

    def _in_cell(self) -> bool:
        return bool(self.stack and self.stack[-1]["cell"])

    def _separator(self, kind: str) -> None:
        if not self._suppressed():
            self.events.append(("space" if kind == "line" and self._in_cell() else kind, ""))

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}
        inherited = self._suppressed()
        hidden = "hidden" in attributes or (
            (attributes.get("aria-hidden") or "").strip().lower() == "true"
        )
        suppressed = inherited or tag in _SUPPRESSED or hidden
        if not suppressed and tag in {"td", "th"} and any(
            name in attributes and (attributes[name] or "").strip() != "1"
            for name in ("rowspan", "colspan")
        ):
            self.span_positions.append(len(self.events))

        if not suppressed and (tag in _BLOCK or tag == "br"):
            self._separator("line")
        region = None
        if not suppressed and tag in {"article", "main", "body"}:
            region = _Region(tag, len(self.events))
            self.regions.append(region)

        if tag in _VOID:
            return
        index = len(self.stack)
        self.stack.append({
            "tag": tag,
            "suppressed": suppressed,
            "pre": self._in_pre() or tag == "pre",
            "cell": self._in_cell() or tag in {"td", "th"},
            "region": region,
        })
        self.open_positions.setdefault(tag, []).append(index)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID:
            return
        positions = self.open_positions.get(tag)
        if not positions:
            self.structural_error = True
            return
        matching = positions[-1]
        if matching != len(self.stack) - 1:
            self.structural_error = True
        frames = self.stack[matching:]
        if not self._suppressed():
            if tag in {"td", "th"}:
                self.events.append(("cell", ""))
            elif tag in _BLOCK:
                self._separator("line")
        for frame in reversed(frames):
            if frame["region"] is not None:
                frame["region"].end = len(self.events)
        for frame in reversed(frames):
            frame_positions = self.open_positions[frame["tag"]]
            frame_positions.pop()
            if not frame_positions:
                del self.open_positions[frame["tag"]]
        del self.stack[matching:]

    def handle_data(self, data):
        if not self._suppressed() and data:
            value = data if self._in_pre() else re.sub(r"\s+", " ", data)
            if value:
                self.events.append(("text", value))

    def close(self):
        super().close()
        if self.stack:
            self.structural_error = True
            for frame in self.stack:
                if frame["region"] is not None:
                    frame["region"].end = len(self.events)


def _canonical_blocks(events: list[tuple[str, str]]) -> list[str]:
    stream = []
    for kind, value in events:
        if kind == "text":
            stream.append(value)
        elif kind == "space":
            stream.append(" ")
        elif kind == "cell":
            stream.append("\t")
        else:
            stream.append("\n")
    text = "".join(stream).replace("\xa0", " ").replace("\r", "\n")
    blocks = []
    for raw_line in text.split("\n"):
        cells = [re.sub(r"[ \f\v]+", " ", cell).strip() for cell in raw_line.split("\t")]
        if "\t" in raw_line and cells and cells[-1] == "":
            cells.pop()
        line = "\t".join(cells)
        if any(cells):
            blocks.append(line)
    return blocks


def _positive_cap(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def clean_html(
    html: str,
    *,
    document_revision: str,
    max_input_chars: int,
    max_output_chars: int,
) -> CleanedDocument:
    """Extract stable visible blocks from one conservative semantic region."""
    _positive_cap("max_input_chars", max_input_chars)
    _positive_cap("max_output_chars", max_output_chars)
    if not isinstance(document_revision, str) or not document_revision.strip():
        raise ValueError("document_revision must not be blank")
    if not isinstance(html, str) or not html:
        raise HtmlCleanError("INPUT_INVALID") from None
    if len(html) > max_input_chars:
        raise HtmlCleanError("INPUT_LIMIT") from None

    parser = _SemanticParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        raise HtmlCleanError("INPUT_INVALID") from None

    text_prefix = [0]
    for kind, value in parser.events:
        text_prefix.append(text_prefix[-1] + int(kind == "text" and bool(value.strip())))

    def usable(kind: str):
        result = []
        for region in parser.regions:
            if region.kind != kind:
                continue
            end = len(parser.events) if region.end is None else region.end
            if text_prefix[end] > text_prefix[region.start]:
                result.append(region)
        return result

    incomplete = []
    articles = usable("article")
    mains = usable("main")
    bodies = usable("body")
    if len(articles) == 1:
        chosen = articles[0]
    elif len(mains) == 1:
        chosen = mains[0]
        if articles:
            incomplete.append("content_text")
    elif len(bodies) == 1:
        chosen = bodies[0]
        incomplete.append("content_text")
    else:
        chosen = _Region("root", 0, len(parser.events))
        incomplete.append("content_text")

    end = len(parser.events) if chosen.end is None else chosen.end
    canonical = _canonical_blocks(parser.events[chosen.start:end])
    if not canonical:
        raise HtmlCleanError("NO_CONTENT") from None
    text = "\n".join(canonical)
    if len(text) > max_output_chars:
        raise HtmlCleanError("OUTPUT_LIMIT") from None
    if parser.structural_error:
        incomplete.append("html_structure")
    if any(chosen.start <= position < end for position in parser.span_positions):
        incomplete.append("table_structure")
    incomplete = list(dict.fromkeys(incomplete))

    blocks = []
    offset = 0
    for index, value in enumerate(canonical, 1):
        start = offset
        end = start + len(value)
        blocks.append(DocumentBlock(block_id=f"b{index:06d}", start=start, end=end))
        offset = end + 1
    return CleanedDocument(
        document=SourceDocument(
            document_revision=document_revision,
            text=text,
            blocks=blocks,
        ),
        incomplete_fields=tuple(incomplete),
    )
