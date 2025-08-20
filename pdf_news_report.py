import base64
import os
import re
import unicodedata
import html
from uuid import uuid4
from datetime import datetime
from typing import Optional

import requests
import fitz  # PyMuPDF

from news_utils import get_news_summary

# ============================ НАСТРОЙКИ ============================
CLIENT_ID = "395c6aed-f8a0-409d-bc19-e302408bf922"
CLIENT_SECRET = "bc7a96bc-ffe4-431c-a5b1-0a4c39a0c090"
SCOPE = "GIGACHAT_API_PERS"

PDF_PATH = "/Users/chipmunks69/Documents/pdf_downloads/test.pdf"  # обновите при необходимости
OUTPUT_TXT = "report.txt"
OUTPUT_HTML = "report.html"

TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# (не обязательно, но убирает варнинги при verify=False)
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# ===================== ВСПОМОГАТЕЛЬНОЕ =====================

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s\-\.]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip(), flags=re.UNICODE)
    text = text.strip("-_.").lower()
    return text or f"id-{uuid4().hex[:8]}"


def detect_company_name(text: str) -> Optional[str]:
    """Пытаемся вытащить название компании из PDF-текста по простым паттернам."""
    patterns = [
        r"(?i)(?:обществ[оа] с ограниченной ответственностью|ооо|публичное акционерное общество|пао|закрытое акционерное общество|зао|акционерное общество|ао)\s+\"?([A-Za-zА-Яа-я0-9 ][^\n\"]{2,})\"?",
        r"(?i)Полное\s+наименование[^\n]{0,50}[\n:]+\s*\"?(.{3,120}?)\"?\s*(?:\n|$)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    # fallback: первые 5 слов первой строки
    first_line = text.split("\n", 1)[0]
    return " ".join(first_line.split()[:5]) if first_line else None


def get_access_token():
    creds_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    headers = {
        "Authorization": f"Basic {creds_b64}",
        "RqUID": str(uuid4()),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"scope": SCOPE}

    resp = requests.post(TOKEN_URL, headers=headers, data=data, verify=False, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def analyze_company(text: str, news_summary: str, news_articles: list[tuple[str, str]], token: str) -> str:
    """Формирует расширенный промпт с новостями и отправляет в GigaChat."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    news_block = ""
    if news_summary:
        news_block += "\n\nДополнительные данные из открытых источников (новости):\n"
        news_block += f"Сводка последних новостей: {news_summary}\n\n"
        if news_articles:
            news_block += "Список статей:\n" + "\n".join(
                f"- {t} ({l})" for t, l in news_articles[:10]
            )
            news_block += "\n\nИспользуй информацию из новостей для проверки фактов, поиска новых связей и возможных бенефициаров."

    prompt = (
        "Ты — эксперт по корпоративной аналитике и визуализации деловой информации. "
        "Проанализируй предоставленный PDF-файл с подробной информацией о компании и дополнительные новости о ней. "
        "Скомбинируй данные, чтобы построить цельный отчёт. "
        "Твоя задача: \n"
        "1. Составь подробное аналитическое summary с акцентом на разделы, которые помогают выявить бенефициаров (см. ниже). "
        "2. Интегрируй в отчёт релевантные факты из новостных источников. Если новости содержат сведения о собственниках, руководстве, судебных процессах, госконтрактах и пр. — обязательно приведи их с указанием источника. "
        "3. Список предполагаемых бенефициаров (только физические лица) нужно расширить, учитывая как PDF, так и свежие новости. Для каждого укажи роль и аргументацию. "
        "4. Верни результат в виде HTML-документа с минималистичным стилем и навигацией по разделам (используй те же правила разметки, что и ранее). "
        "\n\nДанные из PDF:\n" + text + news_block
    )

    payload = {
        "model": "GigaChat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    resp = requests.post(GIGACHAT_URL, headers=headers, json=payload, verify=False, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ===================== РАЗМЕТКА ТЕКСТА -> HTML =====================
# (используем функции из оригинального скрипта без изменений)
# Чтобы не копировать 350+ строк, импортируем оригинальные функции, если они есть

from types import ModuleType

# попытка импортировать utils из оригинальной директории, fallback — локальная копия ниже
try:
    from report_html_utils import clean_text, parse_to_sections, build_nav  # type: ignore
except ImportError:

    # --- мини-копия необходимых функций (упрощённая) -------------------------
    def clean_text(plain_text: str) -> str:
        t = plain_text or ""
        t = re.sub(r"^\s*#{1,6}\s*", "", t, flags=re.MULTILINE)
        t = re.sub(r"\*\*(.*?)\*\*", r"\1", t, flags=re.DOTALL)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    def parse_to_sections(text: str):
        # тривиальный парсинг: каждая строка с '##' — новый раздел
        sections = []
        current = {"title": "Отчёт", "level": 1, "id": slugify("Отчёт"), "blocks": []}
        for line in text.splitlines():
            if line.startswith("## "):
                sections.append(current)
                current = {
                    "title": line[3:],
                    "level": 2,
                    "id": slugify(line[3:]),
                    "blocks": [],
                }
            else:
                current["blocks"].append(f"<p>{html.escape(line)}</p>")
        sections.append(current)
        return sections

    def build_nav(sections):
        return "<ul class='toc'>" + "".join(
            f"<li><a href='#{s['id']}'>{html.escape(s['title'])}</a></li>" for s in sections
        ) + "</ul>"


def build_html_report(plain_text: str) -> str:
    text = clean_text(plain_text)
    sections = parse_to_sections(text)

    body_html = "".join(
        f"<section id='{s['id']}'><h2>{html.escape(s['title'])}</h2>{''.join(s['blocks'])}</section>" for s in sections
    )
    nav_html = build_nav(sections)
    gen_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    return f"""
<!doctype html><html lang='ru'><head><meta charset='utf-8'/><title>Аналитический отчёт</title></head>
<body><aside>{nav_html}</aside><main><h1>Аналитический отчёт</h1><p><em>Сгенерировано {gen_date}</em></p>{body_html}</main></body></html>
"""


# ===================== Точка входа =====================

def main():
    if not os.path.exists(PDF_PATH):
        print(f"❌ Файл {PDF_PATH} не найден")
        return

    print("🔑 Получаю токен...")
    token = get_access_token()

    print("📄 Извлекаю текст из PDF...")
    pdf_text = extract_text(PDF_PATH)

    print("🏷️  Определяю название компании...")
    company_name = detect_company_name(pdf_text) or "Неизвестная компания"
    print(f"   → Обнаружено: {company_name}")

    print("📰 Загружаю новости о компании...")
    news_summary, news_articles = get_news_summary(company_name, max_results=20, summary_sentences=5)

    print("🤖 Отправляю всё на анализ в GigaChat...")
    plain_text = analyze_company(pdf_text, news_summary, news_articles, token)

    print("💾 Сохраняю сырой текст отчёта...")
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(plain_text)

    print("🎨 Генерирую HTML-отчёт...")
    html_content = build_html_report(plain_text)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ Готово! HTML сохранён в {OUTPUT_HTML}")


if __name__ == "__main__":
    main()