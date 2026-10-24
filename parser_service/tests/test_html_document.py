import unittest

from parser_service.html_document import CLEANER_VERSION, HtmlCleanError, clean_html


class HtmlDocumentTests(unittest.TestCase):
    def test_prefers_article_and_preserves_semantic_blocks(self):
        html = """<!doctype html><html><head><title>Скрытый title</title></head><body>
        <nav>Меню</nav><main><article><h1>Решение &amp; прогноз</h1>
        <p>Ставка <a href='/ignored'>составит</a> 16 процентов.</p>
        <time>22 октября 2026</time><table><tr><th>Период</th><td>Значение</td></tr></table>
        <p class='footnote'>Примечание.</p><script>steal()</script>
        <div hidden>Скрыто</div><aside><article>Ложная статья</article></aside>
        </article></main><footer>Подвал</footer></body></html>"""

        cleaned = clean_html(
            html, document_revision="revision-1",
            max_input_chars=len(html), max_output_chars=10_000,
        )

        text = cleaned.document.text
        for expected in ("Решение & прогноз", "Ставка составит 16 процентов.",
                         "22 октября 2026", "Период\tЗначение", "Примечание."):
            self.assertIn(expected, text)
        for excluded in ("Меню", "steal", "Скрыто", "Ложная статья", "Подвал"):
            self.assertNotIn(excluded, text)
        self.assertEqual(text.count("Ставка составит 16 процентов."), 1)
        self.assertEqual(cleaned.incomplete_fields, ())
        self.assertEqual(CLEANER_VERSION, "html.semantic-blocks.v1")
        self.assertEqual(
            [text[block.start:block.end] for block in cleaned.document.blocks],
            text.splitlines(),
        )
        for index, block in enumerate(cleaned.document.blocks, 1):
            self.assertEqual(block.block_id, f"b{index:06d}")
            self.assertEqual(text[block.start:block.end].strip(), text[block.start:block.end])

    def test_is_stable_and_falls_back_with_explicit_incompleteness(self):
        cases = [
            ("<html><body><main><p>Основной текст.</p></main></body></html>", False),
            ("<html><body><article>Один</article><article>Два</article>"
             "<main><p>Fallback.</p></main></body></html>", True),
            ("<div><p>Фрагмент.</p></div>", True),
            ("<html><body><p>Незакрытый", True),
        ]
        for html, incomplete in cases:
            with self.subTest(html=html):
                first = clean_html(html, document_revision="r", max_input_chars=1000,
                                   max_output_chars=1000)
                second = clean_html(html, document_revision="r", max_input_chars=1000,
                                    max_output_chars=1000)
                self.assertEqual(first, second)
                self.assertEqual(first.document.text_hash, second.document.text_hash)
                self.assertEqual(bool(first.incomplete_fields), incomplete)

    def test_preserves_table_cells_and_normalizes_formatting_newlines_inside_paragraph(self):
        table = clean_html(
            "<article><table>\n<tr>\n<td><p>Период</p></td>\n"
            "<td><p>2026</p></td>\n</tr></table></article>",
            document_revision="table", max_input_chars=1000, max_output_chars=1000,
        )
        paragraph = clean_html(
            "<article><p>Первая строка\n    вторая строка</p></article>",
            document_revision="paragraph", max_input_chars=1000, max_output_chars=1000,
        )

        self.assertEqual(table.document.text, "Период\t2026")
        self.assertEqual(paragraph.document.text, "Первая строка вторая строка")
        self.assertEqual(len(paragraph.document.blocks), 1)

    def test_handles_deep_nested_article_without_duplicating_text(self):
        depth = 600
        html = "<article>" + "<div>" * depth + "Глубокий текст." + "</div>" * depth + "</article>"

        cleaned = clean_html(
            html, document_revision="deep", max_input_chars=len(html),
            max_output_chars=1000,
        )

        self.assertEqual(cleaned.document.text, "Глубокий текст.")
        self.assertEqual(len(cleaned.document.blocks), 1)

    def test_preserves_empty_table_cells_and_marks_spanning_cells_incomplete(self):
        rows = [
            ("<td></td><td>2026</td><td>42</td>", "\t2026\t42"),
            ("<td>2026</td><td></td><td>42</td>", "2026\t\t42"),
            ("<td>2026</td><td>42</td><td></td>", "2026\t42\t"),
        ]
        for cells, expected in rows:
            with self.subTest(cells=cells):
                cleaned = clean_html(
                    f"<article><table><tr>{cells}</tr></table></article>",
                    document_revision="empty-cell", max_input_chars=1000,
                    max_output_chars=1000,
                )
                self.assertEqual(cleaned.document.text, expected)

        for attribute in ('colspan="2"', 'rowspan="2"'):
            with self.subTest(attribute=attribute):
                cleaned = clean_html(
                    f"<article><table><tr><td {attribute}>Значение</td>"
                    "<td>42</td></tr></table></article>",
                    document_revision="spanning-cell", max_input_chars=1000,
                    max_output_chars=1000,
                )
                self.assertIn("table_structure", cleaned.incomplete_fields)

    def test_ignores_table_structure_outside_selected_article(self):
        outside_tables = [
            "<nav><table><tr><td colspan='2'>Меню</td></tr></table></nav>",
            "<aside hidden><table><tr><td rowspan='2'>Скрыто</td></tr></table></aside>",
            "<table><tr><td colspan='2'>Внешняя таблица</td></tr></table>",
        ]
        for outside in outside_tables:
            with self.subTest(outside=outside):
                cleaned = clean_html(
                    f"<html><body>{outside}<article><p>Только статья.</p></article>"
                    "</body></html>",
                    document_revision="selected-article", max_input_chars=1000,
                    max_output_chars=1000,
                )
                self.assertEqual(cleaned.document.text, "Только статья.")
                self.assertEqual(cleaned.incomplete_fields, ())

    def test_rejects_invalid_input_limits_and_empty_content_without_truncation(self):
        for kwargs in (
            {"html": 123, "document_revision": "r", "max_input_chars": 10,
             "max_output_chars": 10, "code": "INPUT_INVALID"},
            {"html": "", "document_revision": "r", "max_input_chars": 10,
             "max_output_chars": 10, "code": "INPUT_INVALID"},
            {"html": "<p>too long</p>", "document_revision": "r", "max_input_chars": 2,
             "max_output_chars": 100, "code": "INPUT_LIMIT"},
            {"html": "<article>too long</article>", "document_revision": "r",
             "max_input_chars": 100, "max_output_chars": 2, "code": "OUTPUT_LIMIT"},
            {"html": "<html><nav>only menu</nav></html>", "document_revision": "r",
             "max_input_chars": 100, "max_output_chars": 100, "code": "NO_CONTENT"},
        ):
            code = kwargs.pop("code")
            with self.subTest(code=code), self.assertRaises(HtmlCleanError) as raised:
                clean_html(**kwargs)
            self.assertEqual(raised.exception.code, code)
            if isinstance(kwargs["html"], str) and kwargs["html"]:
                self.assertNotIn(kwargs["html"], str(raised.exception))

        for changes in ({"document_revision": " "}, {"max_input_chars": True},
                        {"max_output_chars": 0}):
            options = {"html": "<p>text</p>", "document_revision": "r",
                       "max_input_chars": 100, "max_output_chars": 100, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                clean_html(**options)


if __name__ == "__main__":
    unittest.main()
