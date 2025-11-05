# Quick Start - Terminal Commands

## ⚡ Швидкий старт (одна команда)

```bash
# Запуск обох скраперів + автоматичний експорт у Excel
python3 scripts/run_all_scrapers.py
```

Ця команда:
- ✅ Запускає Fora та Novus скрапери
- ✅ Показує загальну кількість знайдених продуктів
- ✅ Зберігає дані у `data/all_listings.xlsx`
- ✅ Виводить підсумкову статистику

## 📦 Встановлення

```bash
# Перейдіть до директорії проєкту
cd /Users/getapple/Desktop/repo/scraper

# Встановіть залежності
pip3 install -r requirements.txt

# Або якщо потрібні права адміністратора
pip3 install --user -r requirements.txt
```

## 🚀 Запуск скраперів

### Запуск Fora скрапера

```bash
# Базовий запуск
python3 scripts/run_scraper.py --site fora

# З обмеженням кількості сторінок (для тестування)
python3 scripts/run_scraper.py --site fora --max-pages 2

# Тихий режим (менше логів)
python3 scripts/run_scraper.py --site fora --quiet

# З використанням власної БД
python3 scripts/run_scraper.py --site fora --db data/custom_fora.db
```

### Запуск Novus скрапера

```bash
# Базовий запуск
python3 scripts/run_scraper.py --site novus

# З обмеженням сторінок
python3 scripts/run_scraper.py --site novus --max-pages 2

# Тихий режим
python3 scripts/run_scraper.py --site novus --quiet
```

## 📊 Моніторинг та статистика

```bash
# Показати загальну статистику
python3 scripts/monitor.py

# Статистика для конкретного сайту
python3 scripts/monitor.py --site fora
python3 scripts/monitor.py --site novus

# Логування прогресу у файл
python3 scripts/monitor.py --site fora --log-progress
python3 scripts/monitor.py --site novus --log-progress
```

## 📤 Експорт даних

```bash
# Експорт у Excel
python3 scripts/analyze.py --export-excel data/listings.xlsx

# Експорт для конкретного сайту
python3 scripts/analyze.py --site fora --export-excel data/fora_listings.xlsx
python3 scripts/analyze.py --site novus --export-excel data/novus_listings.xlsx

# Експорт у JSON
python3 scripts/analyze.py --export-json data/listings.json

# Експорт у CSV
python3 scripts/analyze.py --export-csv data/listings.csv
```

## 📈 Аналіз змін цін

```bash
# Аналіз усіх змін цін
python3 scripts/analyze.py --analyze-prices

# Аналіз для конкретного сайту
python3 scripts/analyze.py --site fora --analyze-prices
python3 scripts/analyze.py --site novus --analyze-prices
```

## 🔄 Повний цикл (скрапінг + експорт + моніторинг)

```bash
# Fora
python3 scripts/run_scraper.py --site fora
python3 scripts/analyze.py --site fora --export-excel data/fora_listings.xlsx
python3 scripts/monitor.py --site fora --log-progress

# Novus
python3 scripts/run_scraper.py --site novus
python3 scripts/analyze.py --site novus --export-excel data/novus_listings.xlsx
python3 scripts/monitor.py --site novus --log-progress
```

## ✅ Перевірка встановлення

```bash
# Перевірити, чи встановлені всі залежності
python3 -c "import requests, bs4, backoff, pandas; print('✅ Всі залежності встановлено!')"

# Перевірити імпорти модулів
python3 -c "from src.scrapers.fora_scraper import ForaScraper; from src.scrapers.novus_scraper import NovusScraper; print('✅ Модулі імпортуються правильно!')"

# Перевірити конфігураційні файли
python3 -m json.tool config/fora.json > /dev/null && python3 -m json.tool config/novus.json > /dev/null && echo "✅ Конфігураційні файли валідні!"
```

## 🛠️ Допомога (Help)

```bash
# Допомога для run_scraper
python3 scripts/run_scraper.py --help

# Допомога для monitor
python3 scripts/monitor.py --help

# Допомога для analyze
python3 scripts/analyze.py --help
```

## 📝 Приклади використання

### Приклад 1: Швидке тестування Fora скрапера

```bash
# Запустити з обмеженням 1 сторінки та переглянути статистику
python3 scripts/run_scraper.py --site fora --max-pages 1
python3 scripts/monitor.py --site fora
```

### Приклад 2: Повний скрапінг з експортом

```bash
# Скрапити Fora
python3 scripts/run_scraper.py --site fora

# Експортувати у Excel та JSON
python3 scripts/analyze.py --site fora --export-excel data/fora_listings.xlsx
python3 scripts/analyze.py --site fora --export-json data/fora_listings.json

# Зберегти прогрес
python3 scripts/monitor.py --site fora --log-progress
```

### Приклад 3: Перевірка змін цін

```bash
# Запустити скрапер двічі (з інтервалом)
python3 scripts/run_scraper.py --site fora
# ... почекати ...
python3 scripts/run_scraper.py --site fora

# Перевірити зміни цін
python3 scripts/analyze.py --site fora --analyze-prices
```

## 🎯 Уніфікована команда (запуск обох скраперів)

```bash
# Запуск обох скраперів (Fora + Novus) з автоматичним експортом у Excel
python3 scripts/run_all_scrapers.py

# З обмеженням сторінок (для тестування)
python3 scripts/run_all_scrapers.py --max-pages 2

# Пропустити один зі скраперів
python3 scripts/run_all_scrapers.py --skip-fora
python3 scripts/run_all_scrapers.py --skip-novus

# Власний шлях до Excel файлу
python3 scripts/run_all_scrapers.py --excel data/my_listings.xlsx
```

## ⚡ Швидкі команди (копіювати-вставити)

```bash
# УНІФІКОВАНА КОМАНДА: Запуск обох скраперів + експорт у Excel
python3 scripts/run_all_scrapers.py

# Один рядок: скрапінг + експорт + моніторинг для Fora
python3 scripts/run_scraper.py --site fora && python3 scripts/analyze.py --site fora --export-excel data/fora_listings.xlsx && python3 scripts/monitor.py --site fora --log-progress

# Один рядок: скрапінг + експорт + моніторинг для Novus
python3 scripts/run_scraper.py --site novus && python3 scripts/analyze.py --site novus --export-excel data/novus_listings.xlsx && python3 scripts/monitor.py --site novus --log-progress
```

## 🔍 Перегляд результатів

```bash
# Переглянути базу даних (потрібен sqlite3)
sqlite3 data/listings.db "SELECT COUNT(*) FROM listings;"
sqlite3 data/listings.db "SELECT site, COUNT(*) FROM listings GROUP BY site;"

# Переглянути файли прогресу
cat data/fora_progress.txt
cat data/novus_progress.txt
```
