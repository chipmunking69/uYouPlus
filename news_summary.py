#!/usr/bin/env python3
import argparse
import concurrent.futures
import dataclasses
import html
import logging
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple

import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)


# A compact Russian stopword list (can be extended as needed)
RUSSIAN_STOPWORDS: Set[str] = {
    "и",
    "в",
    "во",
    "не",
    "что",
    "он",
    "на",
    "я",
    "с",
    "со",
    "как",
    "а",
    "то",
    "все",
    "она",
    "так",
    "его",
    "но",
    "да",
    "ты",
    "к",
    "у",
    "же",
    "вы",
    "за",
    "бы",
    "по",
    "только",
    "ее",
    "мне",
    "было",
    "вот",
    "от",
    "меня",
    "еще",
    "нет",
    "о",
    "из",
    "ему",
    "теперь",
    "когда",
    "даже",
    "ну",
    "вдруг",
    "ли",
    "если",
    "же",
    "уже",
    "или",
    "ни",
    "быть",
    "был",
    "него",
    "до",
    "вас",
    "нибудь",
    "опять",
    "уж",
    "вам",
    "ведь",
    "там",
    "потом",
    "себя",
    "ничего",
    "ей",
    "может",
    "они",
    "тут",
    "где",
    "есть",
    "надо",
    "ней",
    "для",
    "мы",
    "тебя",
    "их",
    "чем",
    "была",
    "сам",
    "чтоб",
    "без",
    "будто",
    "чего",
    "раз",
    "тоже",
    "себе",
    "под",
    "будет",
    "ж",
    "тогда",
    "кто",
    "этот",
    "того",
    "потому",
    "этого",
    "какой",
    "совсем",
    "ним",
    "здесь",
    "этом",
    "один",
    "почти",
    "мой",
    "тем",
    "чтобы",
    "нее",
    "сейчас",
    "были",
    "куда",
    "зачем",
    "всех",
    "никогда",
    "можно",
    "при",
    "наконец",
    "два",
    "об",
    "другой",
    "хоть",
    "после",
    "над",
    "больше",
    "тот",
    "через",
    "эти",
    "нас",
    "про",
    "всего",
    "них",
    "какая",
    "много",
    "разве",
    "три",
    "эту",
    "моя",
    "впрочем",
    "хорошо",
    "свою",
    "этой",
    "перед",
    "иногда",
    "лучше",
    "чуть",
    "том",
}


@dataclasses.dataclass
class NewsItem:
    title: str
    link: str
    published: Optional[datetime]
    summary: str
    content: Optional[str] = None


def _http_get_text(url: str, timeout_seconds: int = 10) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            data = resp.read()
            if not data:
                return None
            content_type = resp.headers.get("Content-Type", "")
            charset = None
            for part in content_type.split(";"):
                part = part.strip().lower()
                if part.startswith("charset="):
                    charset = part.split("=", 1)[1]
                    break
            try:
                return data.decode(charset or "utf-8", errors="replace")
            except Exception:
                return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def _clean_html(html_text: str) -> str:
    if not html_text:
        return ""
    text = html.unescape(html_text)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None


def _fetch_feed(url: str) -> List[NewsItem]:
    text = _http_get_text(url, timeout_seconds=15)
    if not text:
        return []
    items: List[NewsItem] = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = _clean_html((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            pub = _parse_datetime(item.findtext("pubDate"))
            desc = _clean_html((item.findtext("description") or "").strip())
            if not title and not desc:
                continue
            items.append(NewsItem(title=title, link=link, published=pub, summary=desc))
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = _clean_html((entry.findtext("atom:title", default="", namespaces=ns) or "").strip())
        link_el = entry.find("atom:link", ns)
        link = ""
        if link_el is not None:
            link = link_el.attrib.get("href", "").strip()
        pub = _parse_datetime(entry.findtext("atom:updated", default=None, namespaces=ns))
        summary = _clean_html((entry.findtext("atom:summary", default="", namespaces=ns) or "").strip())
        if not title and not summary:
            continue
        items.append(NewsItem(title=title, link=link, published=pub, summary=summary))
    return items


def fetch_news_from_sources(query: str, max_items_per_source: int = 50) -> List[NewsItem]:
    google_url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=ru&gl=RU&ceid=RU:ru"
    )
    bing_url = (
        "https://www.bing.com/news/search?q="
        + urllib.parse.quote(query)
        + "&format=rss&cc=ru"
    )

    items: List[NewsItem] = []
    for url in (google_url, bing_url):
        fetched = _fetch_feed(url)[:max_items_per_source]
        items.extend(fetched)

    seen: Set[str] = set()
    unique_items: List[NewsItem] = []
    for item in items:
        key = (item.link or item.title).strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_items.append(item)

    unique_items.sort(key=lambda i: i.published or datetime.min, reverse=True)
    return unique_items


def _extract_main_text_from_html(html_content: str) -> str:
    return _clean_html(html_content)


def enrich_with_article_content(items: List[NewsItem], max_workers: int = 8, per_request_timeout: int = 10, max_fetch: int = 20) -> None:
    targets = items[:max_fetch]

    def _fetch(idx_and_item: Tuple[int, NewsItem]) -> Tuple[int, Optional[str]]:
        idx, news_item = idx_and_item
        if not news_item.link:
            return idx, None
        html_text = _http_get_text(news_item.link, timeout_seconds=per_request_timeout)
        if not html_text:
            return idx, None
        content_text = _extract_main_text_from_html(html_text)
        return idx, content_text

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch, (idx, item)) for idx, item in enumerate(targets)]
        for future in concurrent.futures.as_completed(futures):
            try:
                idx, content = future.result()
            except Exception:
                continue
            if content:
                items[idx].content = content


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[\.!?])\s+(?=[А-ЯA-ZЁ])", text)
    sentences: List[str] = []
    for p in parts:
        subparts = re.split(r"(?<=[;:])\s+", p)
        for s in subparts:
            s = s.strip()
            if len(s) >= 30:
                sentences.append(s)
    return sentences


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text.lower())
    return [t for t in tokens if t not in RUSSIAN_STOPWORDS and len(t) > 2]


def _build_sentence_scores(sentences: List[str]) -> Dict[int, float]:
    sentence_tokens: List[List[str]] = [_tokenize(s) for s in sentences]
    df: Counter[str] = Counter()
    for tokens in sentence_tokens:
        for term in set(tokens):
            df[term] += 1
    num_docs = max(1, len(sentences))
    idf: Dict[str, float] = {term: math.log((num_docs + 1) / (df_count + 1)) + 1 for term, df_count in df.items()}

    scores: Dict[int, float] = {}
    for idx, tokens in enumerate(sentence_tokens):
        tf = Counter(tokens)
        score = 0.0
        for term, freq in tf.items():
            score += (freq / max(1, len(tokens))) * idf.get(term, 0.0)
        length_norm = 1.0 / math.log(8 + len(tokens))
        scores[idx] = score * length_norm
    return scores


def _select_top_sentences(sentences: List[str], top_k: int = 6) -> List[str]:
    if not sentences:
        return []
    scores = _build_sentence_scores(sentences)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    selected_indices: List[int] = []
    selected_texts: Set[str] = set()
    def _similarity(a: str, b: str) -> float:
        ta, tb = set(_tokenize(a)), set(_tokenize(b))
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union

    for idx, _ in ranked:
        candidate = sentences[idx]
        if any(_similarity(candidate, sentences[s]) > 0.7 for s in selected_indices):
            continue
        if candidate in selected_texts:
            continue
        selected_indices.append(idx)
        selected_texts.add(candidate)
        if len(selected_indices) >= top_k:
            break

    selected_indices.sort()
    return [sentences[i] for i in selected_indices]


def build_summary(items: List[NewsItem], max_sentences: int = 6) -> str:
    texts: List[str] = []
    for item in items:
        if item.content:
            texts.append(item.content)
        else:
            if item.summary:
                texts.append(item.summary)
            else:
                texts.append(item.title)

    combined_text = "\n".join(texts)
    sentences = _split_sentences(combined_text)
    if not sentences:
        titles = [it.title for it in items[:max_sentences]]
        return " ".join(titles)

    top_sentences = _select_top_sentences(sentences, top_k=max_sentences)
    summary = " ".join(top_sentences)
    return summary


def summarize_company_news(query: str, max_articles: int = 30, fetch_article_content: bool = True) -> Tuple[str, List[NewsItem]]:
    items = fetch_news_from_sources(query, max_items_per_source=max_articles)
    if not items:
        return "Не удалось найти новости по запросу.", []

    if fetch_article_content:
        enrich_with_article_content(items, max_fetch=min(20, len(items)))

    used_items = items[: max_articles]
    summary_text = build_summary(used_items)
    return summary_text, used_items


def _format_sources(items: List[NewsItem], max_sources: int = 10) -> str:
    lines: List[str] = []
    for item in items[:max_sources]:
        published = item.published.isoformat(sep=" ") if item.published else ""
        line = f"- {item.title} ({published})\n  {item.link}"
        lines.append(line)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Сводка новостей по компании (RU)")
    parser.add_argument("query", help="Название компании или поисковый запрос")
    parser.add_argument("-n", "--num", type=int, default=30, help="Максимум новостей с источника (по умолчанию 30)")
    parser.add_argument("--no-fetch-content", action="store_true", help="Не загружать полный текст статей (только анонсы)")
    parser.add_argument("--max-summary-sentences", type=int, default=6, help="Максимум предложений в сводке")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    start = time.time()
    summary, items = summarize_company_news(
        args.query,
        max_articles=max(5, min(100, args.num)),
        fetch_article_content=not args.no_fetch_content,
    )
    elapsed = time.time() - start

    print("Сводка:")
    print(summary.strip())
    print()
    print("Источники:")
    print(_format_sources(items))
    print()
    print(f"Завершено за {elapsed:.1f} c, источников: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())