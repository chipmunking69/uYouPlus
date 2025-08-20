#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Программа для поиска и суммаризации новостей по компаниям
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re
from urllib.parse import quote_plus
import feedparser
from bs4 import BeautifulSoup
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NewsAggregator:
    """Класс для агрегации новостей по компаниям"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def search_google_news(self, company_name: str, days_back: int = 7) -> List[Dict]:
        """Поиск новостей через Google News"""
        news_items = []
        try:
            # Формируем запрос для Google News RSS
            query = quote_plus(f'"{company_name}" OR "{company_name}" новости')
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=ru&gl=RU&ceid=RU:ru"
            
            logger.info(f"Поиск новостей для компании: {company_name}")
            
            # Парсим RSS фид
            feed = feedparser.parse(rss_url)
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            for entry in feed.entries[:20]:  # Ограничиваем до 20 новостей
                try:
                    # Парсим дату публикации
                    pub_date = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') and entry.published_parsed else datetime.now()
                    
                    if pub_date >= cutoff_date:
                        news_item = {
                            'title': entry.title,
                            'link': entry.link,
                            'published': pub_date.strftime('%Y-%m-%d %H:%M'),
                            'source': 'Google News',
                            'description': getattr(entry, 'summary', ''),
                        }
                        news_items.append(news_item)
                except Exception as e:
                    logger.warning(f"Ошибка при обработке новости: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Ошибка при поиске в Google News: {e}")
            
        return news_items
    
    def search_yandex_news(self, company_name: str) -> List[Dict]:
        """Поиск новостей через Яндекс Новости (упрощенный вариант)"""
        news_items = []
        try:
            # Поиск через поисковый запрос
            query = f"{company_name} новости"
            search_url = f"https://yandex.ru/news/search?text={quote_plus(query)}"
            
            response = self.session.get(search_url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Ищем заголовки новостей (примерная структура)
                news_elements = soup.find_all(['h3', 'h2'], class_=re.compile(r'.*title.*|.*headline.*'))
                
                for element in news_elements[:10]:  # Ограничиваем количество
                    link_elem = element.find('a')
                    if link_elem:
                        title = element.get_text(strip=True)
                        link = link_elem.get('href', '')
                        
                        if company_name.lower() in title.lower():
                            news_item = {
                                'title': title,
                                'link': link,
                                'published': datetime.now().strftime('%Y-%m-%d %H:%M'),
                                'source': 'Яндекс Новости',
                                'description': '',
                            }
                            news_items.append(news_item)
                            
        except Exception as e:
            logger.error(f"Ошибка при поиске в Яндекс Новостях: {e}")
            
        return news_items
    
    def get_article_content(self, url: str) -> str:
        """Получение содержимого статьи по URL"""
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Удаляем ненужные элементы
                for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    element.decompose()
                
                # Ищем основной контент
                content_selectors = [
                    'article', '.article-content', '.post-content', 
                    '.content', '.entry-content', 'main', '.main-content'
                ]
                
                content = ""
                for selector in content_selectors:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        content = content_elem.get_text(separator=' ', strip=True)
                        break
                
                if not content:
                    # Если не нашли по селекторам, берем все параграфы
                    paragraphs = soup.find_all('p')
                    content = ' '.join([p.get_text(strip=True) for p in paragraphs])
                
                return content[:2000]  # Ограничиваем размер
                
        except Exception as e:
            logger.warning(f"Не удалось получить содержимое статьи {url}: {e}")
            
        return ""
    
    def summarize_news(self, news_items: List[Dict], company_name: str) -> str:
        """Создание сводки новостей"""
        if not news_items:
            return f"Новости по компании '{company_name}' не найдены."
        
        summary = f"\n🏢 СВОДКА НОВОСТЕЙ ПО КОМПАНИИ: {company_name.upper()}\n"
        summary += "=" * 60 + "\n\n"
        
        # Группируем новости по дням
        news_by_date = {}
        for news in news_items:
            date_key = news['published'].split(' ')[0]
            if date_key not in news_by_date:
                news_by_date[date_key] = []
            news_by_date[date_key].append(news)
        
        # Сортируем по дате (новые сначала)
        sorted_dates = sorted(news_by_date.keys(), reverse=True)
        
        total_news = len(news_items)
        summary += f"📊 Всего найдено новостей: {total_news}\n"
        summary += f"📅 Период: {sorted_dates[-1] if sorted_dates else 'N/A'} - {sorted_dates[0] if sorted_dates else 'N/A'}\n\n"
        
        # Выводим новости по датам
        for date in sorted_dates:
            summary += f"📅 {date}\n"
            summary += "-" * 20 + "\n"
            
            for i, news in enumerate(news_by_date[date], 1):
                summary += f"{i}. 📰 {news['title']}\n"
                summary += f"   🔗 Источник: {news['source']}\n"
                if news['description']:
                    desc = news['description'][:200] + "..." if len(news['description']) > 200 else news['description']
                    summary += f"   📝 {desc}\n"
                summary += f"   🌐 {news['link']}\n\n"
        
        # Добавляем краткий анализ
        summary += "\n📈 КРАТКИЙ АНАЛИЗ:\n"
        summary += "-" * 20 + "\n"
        
        # Анализируем ключевые слова в заголовках
        all_titles = " ".join([news['title'].lower() for news in news_items])
        
        keywords_analysis = {
            'финансы': ['прибыль', 'убыток', 'доходы', 'выручка', 'инвестиции', 'акции', 'капитал'],
            'развитие': ['расширение', 'рост', 'развитие', 'запуск', 'открытие', 'новый'],
            'проблемы': ['проблемы', 'кризис', 'убытки', 'сокращение', 'закрытие', 'банкротство'],
            'партнерство': ['сделка', 'партнерство', 'соглашение', 'контракт', 'сотрудничество']
        }
        
        found_themes = []
        for theme, keywords in keywords_analysis.items():
            if any(keyword in all_titles for keyword in keywords):
                found_themes.append(theme)
        
        if found_themes:
            summary += f"🔍 Основные темы: {', '.join(found_themes)}\n"
        else:
            summary += "🔍 Основные темы: общие новости\n"
        
        summary += f"⏰ Сводка создана: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        return summary
    
    def search_company_news(self, company_name: str, days_back: int = 7) -> str:
        """Основной метод для поиска и суммаризации новостей"""
        logger.info(f"Начинаю поиск новостей для компании: {company_name}")
        
        all_news = []
        
        # Поиск в Google News
        google_news = self.search_google_news(company_name, days_back)
        all_news.extend(google_news)
        logger.info(f"Найдено новостей в Google News: {len(google_news)}")
        
        # Поиск в Яндекс Новостях
        yandex_news = self.search_yandex_news(company_name)
        all_news.extend(yandex_news)
        logger.info(f"Найдено новостей в Яндекс Новостях: {len(yandex_news)}")
        
        # Удаляем дубликаты по заголовкам
        unique_news = []
        seen_titles = set()
        for news in all_news:
            title_key = news['title'].lower().strip()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_news.append(news)
        
        logger.info(f"Уникальных новостей: {len(unique_news)}")
        
        # Создаем сводку
        summary = self.summarize_news(unique_news, company_name)
        
        return summary


def main():
    """Главная функция программы"""
    print("🔍 АГРЕГАТОР НОВОСТЕЙ ПО КОМПАНИЯМ")
    print("=" * 50)
    
    aggregator = NewsAggregator()
    
    while True:
        try:
            company_name = input("\n📝 Введите название компании (или 'выход' для завершения): ").strip()
            
            if not company_name:
                print("❌ Пожалуйста, введите название компании.")
                continue
            
            if company_name.lower() in ['выход', 'exit', 'quit', 'q']:
                print("👋 До свидания!")
                break
            
            print(f"\n⏳ Ищу новости по компании '{company_name}'...")
            print("Это может занять несколько секунд...\n")
            
            # Получаем сводку новостей
            summary = aggregator.search_company_news(company_name)
            
            # Выводим результат
            print(summary)
            
            # Предлагаем сохранить в файл
            save_choice = input("\n💾 Сохранить сводку в файл? (y/n): ").strip().lower()
            if save_choice in ['y', 'yes', 'да', 'д']:
                filename = f"news_summary_{company_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(summary)
                    print(f"✅ Сводка сохранена в файл: {filename}")
                except Exception as e:
                    print(f"❌ Ошибка при сохранении файла: {e}")
            
        except KeyboardInterrupt:
            print("\n\n👋 Программа завершена пользователем.")
            break
        except Exception as e:
            print(f"❌ Произошла ошибка: {e}")
            print("Попробуйте еще раз или введите 'выход' для завершения.")


if __name__ == "__main__":
    main()