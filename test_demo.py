#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Демонстрационный тест агрегатора новостей
"""

from news_aggregator import NewsAggregator
import sys

def test_aggregator():
    """Тестирование основных функций агрегатора"""
    print("🔍 ТЕСТ АГРЕГАТОРА НОВОСТЕЙ")
    print("=" * 50)
    
    # Создаем экземпляр агрегатора
    aggregator = NewsAggregator()
    
    # Тестовая компания
    test_company = "Сбербанк"
    
    print(f"\n🏢 Тестируем поиск новостей для: {test_company}")
    print("⏳ Начинаем поиск...")
    
    try:
        # Получаем сводку новостей
        summary = aggregator.search_company_news(test_company, days_back=3)
        
        print("\n✅ РЕЗУЛЬТАТ ТЕСТА:")
        print("-" * 30)
        print(summary)
        
        # Сохраняем результат
        filename = f"test_result_{test_company.replace(' ', '_')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        print(f"\n💾 Результат сохранен в файл: {filename}")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_aggregator()
    sys.exit(0 if success else 1)