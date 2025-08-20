import sys
import types

# ---------------------------------------------------------------------------
# Compatibility shim for Python 3.13 where the 'cgi' module has been removed.
# Feedparser still relies on cgi.parse_header. We re-create a minimal stub so
# that older libraries continue to work without modification.
# ---------------------------------------------------------------------------
try:
    import cgi  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    def _parse_header(value: str):
        """Minimal re-implementation of cgi.parse_header that returns (value, dict)."""
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

import argparse
import urllib.parse
import requests
import feedparser
from bs4 import BeautifulSoup
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer

# Ensure NLTK resources are available (punkt tokenizer)
import nltk
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:  # pragma: no cover
    nltk.download("punkt", quiet=True)


def fetch_rss_entries(company: str, max_results: int = 30):
    """Fetch news entries from Google News RSS for the specified company."""
    query = urllib.parse.quote(company)
    rss_url = (
        f"https://news.google.com/rss/search?q={query}&hl=ru&gl=RU&ceid=RU:ru"
    )
    feed = feedparser.parse(rss_url)
    return feed.entries[:max_results]


def extract_clean_text(html_content: str) -> str:
    """Strip HTML tags and return plain text."""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def build_corpus(entries):
    """Concatenate titles and descriptions of RSS entries into one text corpus."""
    corpus_parts = []
    for entry in entries:
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        corpus_parts.append(title)
        if summary:
            corpus_parts.append(extract_clean_text(summary))
    return "\n".join(corpus_parts)


def summarize_text(text: str, sentence_count: int = 5):
    """Return extractive summary of the text using LexRank."""
    parser = PlaintextParser.from_string(text, Tokenizer("russian"))
    summarizer = LexRankSummarizer()
    sentences = summarizer(parser.document, sentence_count)
    return " ".join(str(sentence) for sentence in sentences)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch latest news about a company and output a text summary."
    )
    parser.add_argument("company", help="Company name to search news for")
    parser.add_argument(
        "-n",
        "--num-articles",
        type=int,
        default=30,
        help="Maximum number of news articles to fetch (default: 30)",
    )
    parser.add_argument(
        "-s",
        "--summary-size",
        type=int,
        default=5,
        help="Number of sentences in the summary (default: 5)",
    )
    args = parser.parse_args()

    entries = fetch_rss_entries(args.company, args.num_articles)
    if not entries:
        print("Новостей не найдено.")
        return

    corpus = build_corpus(entries)
    summary = summarize_text(corpus, args.summary_size)

    print(f"Сводка новостей по компании '{args.company}':\n")
    print(summary)
    print("\n\nСписок статей:\n")
    for idx, entry in enumerate(entries, 1):
        print(f"{idx}. {entry.get('title')}\n   {entry.get('link')}")


if __name__ == "__main__":
    main()