import os
import re
import sys
import html
import base64
import types
import unicodedata
import argparse
import urllib.parse
from uuid import uuid4
from datetime import datetime

import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Compatibility shim for Python 3.13 where the 'cgi' module has been removed.
# Feedparser still relies on cgi.parse_header. Minimal stub keeps it working.
# ---------------------------------------------------------------------------
try:
    import cgi  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    def _parse_header(value: str):
        parts = value.split(";")
        main = parts[0].strip().lower()
        params = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                params[k.strip().lower()] = v.strip().strip('"')
        return main, params

    cgi_stub = types.ModuleType("cgi")
    cgi_stub.parse_header = _parse_header  # type: ignore
    sys.modules["cgi"] = cgi_stub

# Import feedparser after the CGI shim so it can find cgi.parse_header
import feedparser


# Silence urllib3 InsecureRequestWarning for verify=False
try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


# ===================== Configuration =====================
DEFAULT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID", "395c6aed-f8a0-409d-bc19-e302408bf922")
DEFAULT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET", "bc7a96bc-ffe4-431c-a5b1-0a4c39a0c090")
DEFAULT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

TOKEN_URL = os.getenv(
    "GIGACHAT_TOKEN_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
)
GIGACHAT_URL = os.getenv(
    "GIGACHAT_CHAT_URL", "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
)


# ===================== Utilities =====================
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s\-\.]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip(), flags=re.UNICODE)
    text = text.strip("-_.").lower()
    return text or f"id-{uuid4().hex[:8]}"


def get_access_token(client_id: str, client_secret: str, scope: str) -> str:
    credentials_b64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials_b64}",
        "RqUID": str(uuid4()),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"scope": scope}
    response = requests.post(TOKEN_URL, headers=headers, data=data, verify=False)
    response.raise_for_status()
    return response.json()["access_token"]


def extract_pdf_text(pdf_path: str) -> str:
    document = fitz.open(pdf_path)
    text_chunks = []
    for page in document:
        text_chunks.append(page.get_text())
    return "\n".join(text_chunks)


# ===================== News (Google RSS) =====================
def fetch_rss_entries(company: str, max_results: int = 30):
    query = urllib.parse.quote(company)
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ru&gl=RU&ceid=RU:ru"
    feed = feedparser.parse(rss_url)
    return feed.entries[:max_results]


def extract_clean_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def build_news_corpus(entries) -> str:
    text_parts = []
    for entry in entries:
        title = entry.get("title", "")
        summary_html = entry.get("summary", "") or entry.get("description", "")
        text_parts.append(title)
        if summary_html:
            text_parts.append(extract_clean_text(summary_html))
    return "\n".join(text_parts)


def build_links_list(entries) -> str:
    lines = []
    for index, entry in enumerate(entries, 1):
        title = entry.get("title", "")
        link = entry.get("link", "")
        lines.append(f"{index}. {title} — {link}")
    return "\n".join(lines)


# ===================== GigaChat =====================
def analyze_company_combined(pdf_text: str, news_corpus: str, article_links: str, token: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    prompt = (
        "Ты — эксперт по корпоративной разведке и визуальной аналитике.\n"
        "Тебе переданы два источника данных: (1) текст из корпоративного PDF-документа и (2) новости из поиска.\n"
        "Задачи: \n"
        "1) Подготовь детальный аналитический отчёт (HTML) на русском, используя только подтверждённые данные из источников.\n"
        "2) Сформируй список предполагаемых бенефициаров (только физические лица) с обоснованием (на какие факты из PDF/новостей опираешься).\n"
        "3) Если встречаются визуальные структуры (цепочки владения, схемы), опиши их и вставь как текстовые блоки/таблицы.\n"
        "4) Структура HTML: навигация, заголовки, списки/таблицы; без домыслов.\n\n"
        "Рекомендуемые разделы: Общая информация; Руководство и участники; Структура собственности; Связанные лица; Деятельность и контракты; Финансовые показатели; Судебные сведения; Список бенефициаров; Приложение (источники).\n\n"
        "Источник A — PDF (сырой текст):\n"
        f"{pdf_text}\n\n"
        "Источник B — Новости (выжимка из заголовков/аннотаций):\n"
        f"{news_corpus}\n\n"
        "Ссылки на материалы (B):\n"
        f"{article_links}\n"
    )

    payload = {
        "model": "GigaChat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    response = requests.post(GIGACHAT_URL, headers=headers, json=payload, verify=False)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# ===================== Plain text -> HTML rendering =====================
def clean_text(plain_text: str) -> str:
    text = plain_text or ""
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_heading_num = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]\s+(.*\S)\s*$")
_heading_md = re.compile(r"^\s*(#{1,6})\s+(.*\S)\s*$")
_ul_item = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_ol_item = re.compile(r"^\s*\d+\.\s+(.*\S)\s*$")
_table_row = re.compile(r"^\s*\|(.+)\|\s*$")
_table_sep = re.compile(r"^\s*\|?\s*(:?-{3,}:?\s*\|)+\s*(?:[:\-]{3,})?\s*\|?\s*$")


def parse_to_sections(text: str):
    lines = text.splitlines()
    sections = []
    current = None

    def start_section(title: str, level: int):
        nonlocal current
        if current:
            close_open_blocks(current)
            sections.append(current)
        current = {
            "title": title.strip(),
            "level": level,
            "id": slugify(title),
            "blocks": [],
            "list_type": None,
            "table_rows": None,
            "in_code": False,
            "code_buf": [],
        }

    def close_open_blocks(sec):
        if sec["in_code"]:
            code_html = "<pre><code>{}</code></pre>".format(
                html.escape("\n".join(sec["code_buf"]))
            )
            sec["blocks"].append(code_html)
            sec["in_code"] = False
            sec["code_buf"].clear()
        if sec["list_type"] == "ul":
            sec["blocks"].append("</ul>")
            sec["list_type"] = None
        elif sec["list_type"] == "ol":
            sec["blocks"].append("</ol>")
            sec["list_type"] = None
        if sec["table_rows"]:
            sec["blocks"].append(render_table(sec["table_rows"]))
            sec["table_rows"] = None

    def render_table(rows):
        if not rows:
            return ""
        if len(rows) >= 2 and _table_sep.match(rows[1]):
            rows = [rows[0]] + rows[2:]
        tr_html = []
        for idx, raw in enumerate(rows):
            m = _table_row.match(raw)
            if not m:
                continue
            cells = [c.strip() for c in m.group(1).split("|")]
            tag = "th" if idx == 0 else "td"
            tr_html.append(
                "<tr>{}</tr>".format(
                    "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells)
                )
            )
        if not tr_html:
            return ""
        return (
            "<div class='table-wrap'>"
            "<table>"
            "<thead>{}</thead><tbody>{}</tbody>"
            "</table></div>"
        ).format(tr_html[0], "".join(tr_html[1:]))

    def add_paragraph(sec, text_line):
        if not text_line.strip():
            return
        sec["blocks"].append("<p>{}</p>".format(html.escape(text_line.strip())))

    start_section("Аналитический отчёт", 1)

    for raw in lines:
        line = raw.rstrip("\r")

        if line.strip().startswith("```"):
            if not current["in_code"]:
                close_open_blocks(current)
                current["in_code"] = True
                current["code_buf"] = []
            else:
                current["blocks"].append(
                    "<pre><code>{}</code></pre>".format(
                        html.escape("\n".join(current["code_buf"]))
                    )
                )
                current["in_code"] = False
                current["code_buf"].clear()
            continue

        if current["in_code"]:
            current["code_buf"].append(raw)
            continue

        mnum = _heading_num.match(line)
        if mnum:
            title_num, rest = mnum.groups()
            level = len(title_num.split("."))
            start_section(f"{title_num} {rest}", level)
            continue

        mmd = _heading_md.match(raw)
        if mmd:
            hashes, rest = mmd.groups()
            level = len(hashes)
            start_section(rest, level)
            continue

        if _table_row.match(line):
            if current["table_rows"] is None:
                close_open_blocks(current)
                current["table_rows"] = []
            current["table_rows"].append(line)
            continue
        elif current["table_rows"] and (not line.strip() or not _table_row.match(line)):
            current["blocks"].append(render_table(current["table_rows"]))
            current["table_rows"] = None
            if not line.strip():
                continue

        mul = _ul_item.match(line)
        mol = _ol_item.match(line)
        if mul:
            if current["list_type"] != "ul":
                close_open_blocks(current)
                current["blocks"].append("<ul>")
                current["list_type"] = "ul"
            current["blocks"].append(f"<li>{html.escape(mul.group(1))}</li>")
            continue
        elif mol:
            if current["list_type"] != "ol":
                close_open_blocks(current)
                current["blocks"].append("<ol>")
                current["list_type"] = "ol"
            current["blocks"].append(f"<li>{html.escape(mol.group(1))}</li>")
            continue
        else:
            if current["list_type"]:
                if current["list_type"] == "ul":
                    current["blocks"].append("</ul>")
                else:
                    current["blocks"].append("</ol>")
                current["list_type"] = None

        if re.match(r"^\s*(Внимание|Важно|Примечание)\s*[:\-–]", line, flags=re.IGNORECASE):
            current["blocks"].append(
                f"<div class='callout'><strong>{html.escape(line.split(':',1)[0])}:</strong> {html.escape(':'.join(line.split(':')[1:]).strip())}</div>"
            )
            continue

        if line.strip():
            add_paragraph(current, line)
        else:
            current["blocks"].append("<div class='spacer'></div>")

    if current:
        close_open_blocks(current)
        sections.append(current)

    return sections


def build_nav(sections):
    html_nav = []
    level_stack = [0]

    def open_ul():
        html_nav.append("<ul class='toc'>")
        level_stack.append(1)

    def close_ul():
        if len(level_stack) > 1:
            html_nav.append("</ul>")
            level_stack.pop()

    prev_level = 1
    opened = False
    for sec in sections:
        lvl = max(1, min(6, sec["level"]))
        if not opened:
            open_ul()
            opened = True

        while lvl > prev_level:
            open_ul()
            prev_level += 1
        while lvl < prev_level:
            close_ul()
            prev_level -= 1

        html_nav.append(
            "<li><a href='#{}' data-target='{}'>{}</a></li>".format(
                sec["id"], sec["id"], html.escape(sec["title"]) 
            )
        )

    while len(level_stack) > 1:
        close_ul()
    return "".join(html_nav)


def build_html_report(plain_text: str) -> str:
    text = clean_text(plain_text)
    sections = parse_to_sections(text)

    content_blocks = []
    for sec in sections:
        body = "".join(sec["blocks"])
        content_blocks.append(
            f"<section id='{sec['id']}' class='card level-{sec['level']}'><h2>{html.escape(sec['title'])}</h2>{body}</section>"
        )

    nav_html = build_nav(sections)
    gen_date = datetime.now().strftime("%d.%m.%Y %H:%M")

    html_doc = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Аналитический отчёт</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #0f172a;
      --panel-2: #111827;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --accent: #2563eb;
      --accent-2: #38bdf8;
      --border: #e5e7eb;
      --shadow: 0 10px 25px rgba(2,6,23,0.08);
      --radius: 14px;
    }}

    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Arial, "Noto Sans", "Apple Color Emoji","Segoe UI Emoji";
      background: var(--bg);
      color: var(--text);
      display: grid;
      grid-template-columns: 300px 1fr;
      min-height: 100vh;
    }}

    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 22px 20px;
      background: linear-gradient(180deg, var(--panel), var(--panel-2));
      color: #e5e7eb;
      box-shadow: inset 0 -1px 0 rgba(255,255,255,0.05);
      overflow-y: auto;
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }}
    .brand .dot {{ width: 12px; height: 12px; border-radius: 50%; background: radial-gradient(circle at 30% 30%, var(--accent-2), var(--accent)); box-shadow: 0 0 12px rgba(56,189,248,.8); }}
    .brand h1 {{ font-size: 18px; margin: 0; color: #fff; letter-spacing: .2px; }}
    .meta {{ font-size: 12px; color: #9ca3af; margin-bottom: 16px; }}
    .toc {{ list-style: none; margin: 0; padding-left: 0; }}
    .toc > li {{ margin: 6px 0; }}
    .toc a {{ display: block; padding: 9px 12px; text-decoration: none; color: #cbd5e1; border-radius: 10px; line-height: 1.2; transition: background .2s, color .2s, transform .05s; border: 1px solid rgba(255,255,255,0.06); }}
    .toc a:hover {{ background: rgba(255,255,255,0.06); color: #fff; }}
    .toc a.active {{ background: rgba(56,189,248,0.15); color: #e6f9ff; border-color: rgba(56,189,248,0.35); box-shadow: 0 0 0 2px rgba(56,189,248,0.18) inset; }}
    .toc ul {{ margin-left: 10px; padding-left: 12px; border-left: 1px dashed rgba(255,255,255,0.12); }}

    .topbar {{ display: none; grid-column: 1 / -1; padding: 12px 16px; background: var(--panel); color: #fff; align-items: center; gap: 10px; }}
    .burger {{ display: inline-flex; width: 40px; height: 36px; align-items:center; justify-content:center; border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; background: transparent; color:#fff; }}

    main {{ padding: 28px 34px; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}

    .header {{ display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }}
    .header .title {{ font-size: 28px; margin: 0; letter-spacing: .2px; }}
    .header .subtitle {{ color: var(--muted); font-size: 14px; }}

    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 22px; margin: 18px 0 22px; box-shadow: var(--shadow); }}
    .card h2 {{ margin: 0 0 12px 0; font-size: 20px; padding-left: 12px; border-left: 4px solid var(--accent-2); }}
    .level-2 h2 {{ border-left-color: #60a5fa; }}
    .level-3 h2 {{ border-left-color: #a78bfa; }}
    .level-4 h2 {{ border-left-color: #f59e0b; }}

    p {{ line-height: 1.7; margin: 10px 0; color: #111827; }}
    .spacer {{ height: 6px; }}
    .callout {{ margin: 12px 0; padding: 12px 14px; border-radius: 12px; background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a; }}

    ul, ol {{ padding-left: 18px; }}
    li {{ margin: 6px 0; }}

    .table-wrap {{ overflow: auto; border-radius: 10px; border: 1px solid var(--border); }}
    table {{ border-collapse: collapse; min-width: 540px; width: 100%; background: #fff; }}
    thead tr {{ background: #f8fafc; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 10px 12px; text-align: left; font-size: 14px; }}
    tbody tr:nth-child(odd) {{ background: #fcfdff; }}

    pre {{ background: #0b1220; color: #e5e7eb; padding: 14px; border-radius: 12px; overflow: auto; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 13px; }}

    .to-top {{ position: fixed; right: 22px; bottom: 22px; z-index: 50; background: var(--panel); color: #fff; border: none; border-radius: 12px; padding: 10px 12px; box-shadow: var(--shadow); opacity: .9; display: none; }}
    .to-top.show {{ display: inline-flex; }}

    @media (max-width: 1024px) {{
      body {{ grid-template-columns: 1fr; }}
      aside {{ display: none; }}
      .topbar {{ display: flex; }}
    }}
  </style>
</head>
<body>

  <div class="topbar">
    <button class="burger" id="openToc" aria-label="Открыть оглавление">☰</button>
    <div style="font-weight:600">Аналитический отчёт</div>
  </div>

  <aside id="sidebar">
    <div class="brand">
      <div class="dot"></div>
      <h1>Навигация</h1>
    </div>
    <div class="meta">Сгенерировано: {gen_date}</div>
    {nav_html}
  </aside>

  <main>
    <div class="container">
      <div class="header">
        <h2 class="title">Аналитический отчёт</h2>
        <div class="subtitle">Автоматический разбор PDF и новостного поиска</div>
      </div>

      {''.join(content_blocks)}
    </div>
  </main>

  <button class="to-top" id="toTop" title="Наверх">▲</button>

  <script>
    const links = Array.from(document.querySelectorAll('aside .toc a'));
    const sections = links.map(a => document.getElementById(a.dataset.target));
    const obs = new IntersectionObserver((entries) => {{
      entries.forEach(e => {{
        if (e.isIntersecting) {{
          links.forEach(l => l.classList.toggle('active', l.dataset.target === e.target.id));
        }}
      }});
    }}, {{ rootMargin: "-40% 0px -50% 0px", threshold: [0, 1] }});
    sections.forEach(s => s && obs.observe(s));

    const toTop = document.getElementById('toTop');
    window.addEventListener('scroll', () => {{
      if (window.scrollY > 400) toTop.classList.add('show');
      else toTop.classList.remove('show');
    }});
    toTop.addEventListener('click', () => window.scrollTo({{ top: 0, behavior: 'smooth' }}));

    const sidebar = document.getElementById('sidebar');
    const openToc = document.getElementById('openToc');
    openToc && openToc.addEventListener('click', () => {{
      if (getComputedStyle(sidebar).display === 'none') {{
        sidebar.style.display = 'block';
        sidebar.style.position = 'fixed';
        sidebar.style.zIndex = 60;
        sidebar.style.width = 'min(88vw, 340px)';
        sidebar.style.boxShadow = '0 20px 50px rgba(0,0,0,0.35)';
      }} else {{
        sidebar.style.display = 'none';
      }}
    }});
    document.querySelectorAll('#sidebar a').forEach(a => a.addEventListener('click', () => {{
      if (window.innerWidth <= 1024) sidebar.style.display = 'none';
    }}));
  </script>

</body>
</html>
"""
    return html_doc


# ===================== Entry point =====================
def main():
    parser = argparse.ArgumentParser(
        description=(
            "Комбинированный анализ: новости по компании + текст из PDF отправляются в GigaChat; "
            "на выходе HTML-отчёт и список бенефициаров."
        )
    )
    parser.add_argument("company", help="Название компании для новостного поиска")
    parser.add_argument(
        "--pdf",
        dest="pdf_path",
        required=True,
        help="Путь к PDF-файлу с корпоративной информацией",
    )
    parser.add_argument(
        "--output-html",
        dest="output_html",
        default="report.html",
        help="Путь для сохранения HTML-отчёта (по умолчанию report.html)",
    )
    parser.add_argument(
        "--output-txt",
        dest="output_txt",
        default="report_raw.txt",
        help="Путь для сохранения сырого текста ответа (по умолчанию report_raw.txt)",
    )
    parser.add_argument(
        "-n",
        "--num-articles",
        type=int,
        default=30,
        help="Максимум новостей для загрузки (по умолчанию 30)",
    )
    parser.add_argument(
        "--client-id",
        dest="client_id",
        default=DEFAULT_CLIENT_ID,
        help="GigaChat CLIENT_ID (или переменная окружения GIGACHAT_CLIENT_ID)",
    )
    parser.add_argument(
        "--client-secret",
        dest="client_secret",
        default=DEFAULT_CLIENT_SECRET,
        help="GigaChat CLIENT_SECRET (или переменная окружения GIGACHAT_CLIENT_SECRET)",
    )
    parser.add_argument(
        "--scope",
        dest="scope",
        default=DEFAULT_SCOPE,
        help="GigaChat scope (по умолчанию GIGACHAT_API_PERS)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"❌ Файл {args.pdf_path} не найден")
        sys.exit(1)

    print("🔑 Получаю токен...")
    token = get_access_token(args.client_id, args.client_secret, args.scope)

    print("📰 Загружаю новости...")
    entries = fetch_rss_entries(args.company, args.num_articles)
    news_corpus = build_news_corpus(entries) if entries else ""
    links_text = build_links_list(entries) if entries else "Источник новостей не дал результатов"

    print("📄 Извлекаю текст из PDF...")
    pdf_text = extract_pdf_text(args.pdf_path)

    print("🤖 Отправляю на анализ в GigaChat (PDF + новости)...")
    combined_plain = analyze_company_combined(pdf_text, news_corpus, links_text, token)

    print("💾 Сохраняю сырой текст ответа...")
    with open(args.output_txt, "w", encoding="utf-8") as f:
        f.write(combined_plain)

    print("🎨 Генерирую HTML-отчёт...")
    html_content = build_html_report(combined_plain)
    with open(args.output_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ Готово! HTML сохранён в {args.output_html}")
    if entries:
        print("\nСписок статей:\n")
        for idx, entry in enumerate(entries, 1):
            print(f"{idx}. {entry.get('title')}\n   {entry.get('link')}")


if __name__ == "__main__":
    main()

