"""
Import Contacts Script
Скрипт для импорта контактов из различных форматов
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

# Добавляем родительскую директорию в путь для импорта bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.importer import parse_vcard, parse_csv, parse_json, batch_insert_contacts

# Загрузка переменных окружения
load_dotenv()

# Инициализация Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL и SUPABASE_KEY должны быть установлены в .env файле")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def main():
    """Главная функция для запуска импорта"""
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python scripts/import_contacts.py <файл>")
        print("\nПоддерживаемые форматы:")
        print("  .vcf  - vCard (экспорт из Контактов macOS)")
        print("  .csv  - CSV с колонками: name, company, position, email, telegram, phone, tags")
        print("  .json - JSON массив объектов")
        sys.exit(1)
    
    file_path = sys.argv[1]
    
    if not os.path.exists(file_path):
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)
    
    # Определить формат по расширению
    ext = os.path.splitext(file_path)[1].lower()
    
    contacts = []
    
    try:
        if ext == '.vcf':
            print(f"📥 Импорт из vCard: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            contacts = parse_vcard(content)
            
        elif ext == '.csv':
            print(f"📥 Импорт из CSV: {file_path}")
            # parse_csv принимает путь к файлу или контент
            contacts = parse_csv(file_path)
            
        elif ext == '.json':
            print(f"📥 Импорт из JSON: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            contacts = parse_json(content)
            
        else:
            print(f"❌ Неподдерживаемый формат: {ext}")
            print("Поддерживаются: .vcf, .csv, .json")
            sys.exit(1)
            
        # Импорт в базу
        result = batch_insert_contacts(supabase, contacts)
        
        print(f"\n📊 Результаты импорта:")
        print(f"   ✅ Импортировано: {result['imported']}")
        print(f"   ⚠️  Дубликатов пропущено: {result['duplicates']}")
        print(f"   ❌ Ошибок: {result['errors']}")
        
    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
