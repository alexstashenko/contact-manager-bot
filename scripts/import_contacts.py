"""
Import Contacts Script
Скрипт для импорта контактов из различных форматов
"""

import os
import sys
import json
import pandas as pd
import vobject
from dotenv import load_dotenv
from supabase import create_client

# Загрузка переменных окружения
load_dotenv()

# Инициализация Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL и SUPABASE_KEY должны быть установлены в .env файле")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def import_from_vcard(file_path: str):
    """Импорт контактов из vCard (.vcf) файла"""
    print(f"📥 Импорт из vCard: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        vcard_data = f.read()
    
    contacts = []
    for vcard in vobject.readComponents(vcard_data):
        contact = {
            'name': str(vcard.fn.value) if hasattr(vcard, 'fn') else 'Без имени',
            'source': 'import_vcf'
        }
        
        # Email
        if hasattr(vcard, 'email'):
            contact['email'] = str(vcard.email.value)
        
        # Телефон
        if hasattr(vcard, 'tel'):
            contact['phone'] = str(vcard.tel.value)
        
        # Организация
        if hasattr(vcard, 'org'):
            contact['company'] = str(vcard.org.value[0]) if vcard.org.value else None
        
        # Должность
        if hasattr(vcard, 'title'):
            contact['position'] = str(vcard.title.value)
        
        contacts.append(contact)
    
    # Загрузка в Supabase
    return batch_insert_contacts(contacts)


def import_from_csv(file_path: str):
    """Импорт контактов из CSV файла"""
    print(f"📥 Импорт из CSV: {file_path}")
    
    df = pd.read_csv(file_path)
    
    # Ожидаемые колонки: name, company, position, email, telegram, phone, tags
    contacts = []
    
    for _, row in df.iterrows():
        contact = {
            'name': row.get('name', 'Без имени'),
            'company': row.get('company'),
            'position': row.get('position'),
            'email': row.get('email'),
            'telegram': row.get('telegram'),
            'phone': row.get('phone'),
            'source': 'import_csv'
        }
        
        # Теги
        if 'tags' in row and pd.notna(row['tags']):
            # Предполагается формат: "тег1, тег2, тег3"
            tags = [tag.strip() for tag in str(row['tags']).split(',')]
            contact['tags'] = tags
        
        contacts.append(contact)
    
    return batch_insert_contacts(contacts)


def import_from_json(file_path: str):
    """Импорт контактов из JSON файла"""
    print(f"📥 Импорт из JSON: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Формат: список объектов с полями name, company, position и т.д.
    contacts = []
    
    for item in data:
        contact = {
            'name': item.get('name', 'Без имени'),
            'company': item.get('company'),
            'position': item.get('position'),
            'email': item.get('email'),
            'telegram': item.get('telegram'),
            'phone': item.get('phone'),
            'tags': item.get('tags', []),
            'source': 'import_json'
        }
        contacts.append(contact)
    
    return batch_insert_contacts(contacts)


def batch_insert_contacts(contacts: list) -> dict:
    """Пакетная вставка контактов в Supabase"""
    if not contacts:
        print("❌ Нет контактов для импорта")
        return {'imported': 0, 'errors': 0}
    
    imported = 0
    errors = 0
    duplicates = 0
    
    for contact in contacts:
        try:
            # Проверка на дубликаты по email или telegram
            existing = None
            
            if contact.get('email'):
                check = supabase.table('contacts').select('id').eq('email', contact['email']).execute()
                if check.data:
                    existing = check.data[0]
            
            if not existing and contact.get('telegram'):
                check = supabase.table('contacts').select('id').eq('telegram', contact['telegram']).execute()
                if check.data:
                    existing = check.data[0]
            
            if existing:
                duplicates += 1
                print(f"⚠️  Контакт {contact['name']} уже существует, пропущен")
                continue
            
            # Вставка
            supabase.table('contacts').insert(contact).execute()
            imported += 1
            print(f"✅ Импортирован: {contact['name']}")
            
        except Exception as e:
            errors += 1
            print(f"❌ Ошибка импорта {contact.get('name', 'Неизвестно')}: {e}")
    
    print(f"\n📊 Результаты импорта:")
    print(f"   ✅ Импортировано: {imported}")
    print(f"   ⚠️  Дубликатов пропущено: {duplicates}")
    print(f"   ❌ Ошибок: {errors}")
    
    return {
        'imported': imported,
        'duplicates': duplicates,
        'errors': errors
    }


def main():
    """Главная функция для запуска импорта"""
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python import_contacts.py <файл>")
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
    
    if ext == '.vcf':
        import_from_vcard(file_path)
    elif ext == '.csv':
        import_from_csv(file_path)
    elif ext == '.json':
        import_from_json(file_path)
    else:
        print(f"❌ Неподдерживаемый формат: {ext}")
        print("Поддерживаются: .vcf, .csv, .json")
        sys.exit(1)


if __name__ == '__main__':
    main()
