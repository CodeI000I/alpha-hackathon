import unittest

from parser_service.cbr_html import extract_article


class CbrHtmlTests(unittest.TestCase):
    def test_extracts_article_date_structure_and_allowed_attachments(self):
        html = """
        <!doctype html><html><head><title>Не основной заголовок</title></head><body>
          <nav>Навигация вне статьи</nav>
          <h1>Решение Банка России</h1>
          <div class="news-info-line_date">21 октября 2026 года</div>
          <div class="landing-text">
            <p>Основной абзац.</p>
            <table><tr><th>Показатель</th><td>42</td></tr></table>
            <p class="note">Примечание к таблице.</p>
            <script>secret_script()</script><style>.hidden { display:none }</style>
            <a href="/files/report.pdf">PDF</a>
            <a rel="nofollow" href="/files/ignored.pdf">Не следовать</a>
            <a href="/SaveToPdf?url=/press/fixture">Печать</a>
          </div>
          <footer>Служебный подвал</footer>
        </body></html>
        """

        article = extract_article(html)

        self.assertEqual(article["title"], "Решение Банка России")
        self.assertEqual(article["published_date"], "2026-10-21")
        self.assertIn("Основной абзац.", article["content_text"])
        self.assertIn("Показатель", article["content_text"])
        self.assertIn("42", article["content_text"])
        self.assertIn("Примечание к таблице.", article["content_text"])
        self.assertNotIn("secret_script", article["content_text"])
        self.assertNotIn("Навигация", article["content_text"])
        self.assertEqual(article["attachments"], ["/files/report.pdf"])
        self.assertIs(article["no_follow"], False)
        self.assertIs(article["complete"], True)

    def test_document_robots_nofollow_suppresses_all_attachments(self):
        html = """
        <html><head><meta name="robots" content="index, nofollow"></head><body>
          <h1>Заголовок</h1>
          <div class="landing-text"><p>Текст.</p><a href="/files/report.pdf">PDF</a></div>
        </body></html>
        """

        article = extract_article(html)

        self.assertIs(article["no_follow"], True)
        self.assertEqual(article["attachments"], [])

    def test_missing_or_ambiguous_article_structure_is_incomplete(self):
        malformed_documents = [
            "<html><body><main>Текст всей страницы не является статьёй</main></body></html>",
            "<html><body><div class='landing-text'>Первая</div>"
            "<div class='landing-text'>Вторая</div></body></html>",
            "<html><body><h1>Незакрытый заголовок<div class='landing-text'>Текст",
            "<html><body></body><body><div class='landing-text'>Вторая body</div></body></html>",
        ]
        for html in malformed_documents:
            with self.subTest(html=html):
                article = extract_article(html)
                self.assertIs(article["complete"], False)
                self.assertNotEqual(
                    article["content_text"], "Текст всей страницы не является статьёй"
                )


if __name__ == "__main__":
    unittest.main()
