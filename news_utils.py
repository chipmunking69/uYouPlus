import sys
import types
import urllib.parse
import re
from typing import List, Tuple

import requests
import feedparser
from bs4 import BeautifulSoup

# --- Compatibility shim for removed 'cgi' in Python 3.13 ----------------------
try:
    import cgi  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    def _parse_header(value: str):
        parts = value.split(';')
        main = parts[0].strip().lower()
        params = {}
        for part in parts[1:]:
            if '=' in part:
                k, v = part.strip().split('=', 1)
                params[k.strip().lower()] = v.strip().strip('"')
        return main, params

    cgi_stub = types.ModuleType("cgi")
    cgi_stub.parse_header = _parse_header  # type: ignore
    sys.modules["cgi"] = cgi_stub

# --- Summarisation -----------------------------------------------------------
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer

# NLTK resource check (punkt + punkt_tab)
import nltk
for _res in ("punkt", "punkt_tab"):
    try:
        nltk.data.find(f"tokenizers/{_res}")
    except LookupError:
        nltk.download(_res, quiet=True)


__all__ = [
    "fetch_rss_entries",
    "get_news_summary",
]


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/118.0 Safari/537.36"
)


def fetch_rss_entries(company: str, max_results: int = 30):
    """Fetch latest news RSS entries from Google News for the given company."""
    query = urllib.parse.quote(company)
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ru&gl=RU&ceid=RU:ru"
    headers = {"User-Agent": USER_AGENT}
    # feedparser can fetch by itself; but set headers via requests for better control
    resp = requests.get(rss_url, headers=headers, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    return feed.entries[:max_results]


def extract_clean_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content or "", "html.parser")
    return soup.get_text(separator=" ", strip=True)


def build_corpus(entries):
    parts = []
    for entry in entries:
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        parts.append(title)
        if summary:
            parts.append(extract_clean_text(summary))
    return "\n".join(parts)


def summarize_text(text: str, sentence_count: int = 5):
    parser = PlaintextParser.from_string(text, Tokenizer("russian"))
    summarizer = LexRankSummarizer()
    sentences = summarizer(parser.document, sentence_count)
    return " ".join(str(s) for s in sentences)


def get_news_summary(company: str, max_results: int = 30, summary_sentences: int = 5) -> Tuple[str, List[Tuple[str, str]]]:
    """Return (summary, list[(title, link)]) for company news."""
    try:
        entries = fetch_rss_entries(company, max_results)
    except Exception as exc:
        return (f"Не удалось получить новости: {exc}", [])

    if not entries:
        return ("Новости не найдены.", [])

    corpus = build_corpus(entries)
    summary = summarize_text(corpus, summary_sentences)
    articles = [(e.get("title", "Без названия"), e.get("link", "")) for e in entries]
    return summary, articles