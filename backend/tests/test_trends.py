from app.services.trends.feeds import parse_feed, parse_github
from app.services.trends.scan import keywords, term_regex

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>GraphRAG beats naive RAG</title><link>https://ex.com/a</link>
<description>&lt;p&gt;New retrieval method&lt;/p&gt;</description><pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>No link</title></item></channel></rss>"""


def test_parse_feed():
    items = parse_feed(RSS)
    assert len(items) == 1
    assert items[0]["url"] == "https://ex.com/a" and items[0]["summary"] == "New retrieval method"
    assert items[0]["published_at"].year == 2026


def test_parse_github():
    items = parse_github({"items": [{"full_name": "a/b", "html_url": "https://github.com/a/b", "description": "x",
                                     "stargazers_count": 5, "created_at": "2026-10-01T00:00:00Z"}]})
    assert items[0]["title"] == "a/b (★5)"


def test_keywords_and_matching():
    kws = keywords(["RAG fundamentals", "Build a RAG project with LangChain"])
    assert "rag" in kws and "langchain" in kws and "fundamentals" not in kws
    assert term_regex("RAG").search("graphrag beats naive rag")  # whole word "rag", not the one inside "graphrag"
    assert not term_regex("RAG").search("graphrag only")
    assert term_regex("transformer").search("linear-time transformers") and term_regex("reranker").search("rerankers")
