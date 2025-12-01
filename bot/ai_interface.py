"""
Contacts Manager Bot - AI Interface
Обработка естественноязычных запросов через Gemini API
"""

import os
import asyncio
import google.generativeai as genai
from supabase import Client


class AIInterface:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
        
        # Настройка Gemini API
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY не найден в переменных окружения")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
    
    async def _run_io(self, func, *args, **kwargs):
        """Выполнить блокирующую операцию в отдельном потоке"""
        return await asyncio.to_thread(func, *args, **kwargs)
    
    def _analyze_query(self, query: str) -> dict:
        """
        Анализ запроса для определения типа фильтрации.
        
        Returns:
            {
                'type': 'name_search' | 'company_search' | 'tag_search' | 'complex',
                'filter': extracted search term or None
            }
        """
        import re
        
        query_lower = query.lower().strip()
        
        # Простой поиск по имени
        name_patterns = [
            r'^(?:покажи|выведи|открой|найди|кто такой|кто такая)\s+(.+)$',
            r'^@?([a-zA-Zа-яА-ЯёЁ\s]+)$',  # Просто имя без глаголов
        ]
        
        for pattern in name_patterns:
            match = re.match(pattern, query_lower)
            if match:
                return {'type': 'name_search', 'filter': match.group(1).strip()}
        
        # Поиск по компании
        company_patterns = [
            r'(?:кто|все|контакты)\s+(?:из|в)\s+(.+)',
            r'(.+)\s+компания',
        ]
        
        for pattern in company_patterns:
            match = re.search(pattern, query_lower)
            if match:
                return {'type': 'company_search', 'filter': match.group(1).strip()}
        
        # Поиск по тегу
        tag_patterns = [
            r'(?:все|кто)\s+(hr|разработчик|менеджер|дизайнер|маркетолог)',
            r'#(\w+)',
        ]
        
        for pattern in tag_patterns:
            match = re.search(pattern, query_lower)
            if match:
                return {'type': 'tag_search', 'filter': match.group(1).strip()}
        
        # Сложный запрос (требует анализа всех контактов)
        return {'type': 'complex', 'filter': None}
    
    async def process_query(self, user_query: str) -> str:
        """
        Обработка естественноязычного запроса пользователя с умной предфильтрацией.
        
        Args:
            user_query: Вопрос пользователя (например: "Кто у меня есть из HR?")
        
        Returns:
            Форматированный ответ для отправки в Telegram
        """
        
        # Шаг 1: Анализ запроса
        query_analysis = self._analyze_query(user_query)
        
        # Шаг 2: Получить контакты с учетом фильтрации
        contacts_data = await self._fetch_filtered_contacts(
            query_type=query_analysis['type'],
            filter_value=query_analysis['filter']
        )
        
        if not contacts_data:
            return "❌ Контакты не найдены. Попробуйте изменить запрос."
        
        # Шаг 3: Подготовить контекст для Gemini
        # Для простых запросов отправляем все найденные (обычно 1-20)
        # Для сложных - ограничиваем до 30
        max_contacts = 30 if query_analysis['type'] == 'complex' else len(contacts_data)
        context = self._prepare_context(contacts_data, max_contacts=min(max_contacts, len(contacts_data)))
        
        # Шаг 4: Создать промпт
        prompt = f"""Ты — помощник для управления контактами. У пользователя есть следующие контакты:

{context}

Вопрос пользователя: {user_query}

ВАЖНО: Если пользователь просто написал имя или имя и фамилию (например: "Иван", "Иван Петров") или использовал глаголы "покажи", "выведи", "открой", "найди" с именем — это значит, что нужно показать ПОЛНУЮ карточку контакта со ВСЕМИ доступными данными.

Для каждого контакта указывай:
- Имя
- Компания и должность (если есть)
- ВСЕ контактные данные (Email, Email2, Telegram, Телефон, Телефон2 - ОБЯЗАТЕЛЬНО показывай все, что есть)
- Последнее взаимодействие (если есть)

Отвечай по-русски, кратко и структурированно."""

        # Шаг 5: Получить ответ от Gemini
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return self._format_response(response.text)
        except Exception as e:
            return f"❌ Ошибка при обработке запроса: {str(e)}"
    
    async def _fetch_filtered_contacts(self, query_type: str, filter_value: str = None) -> list:
        """
        Получить контакты с умной фильтрацией на уровне SQL.
        
        Args:
            query_type: Тип запроса ('name_search', 'company_search', 'tag_search', 'complex')
            filter_value: Значение для фильтрации (имя, компания, тег)
        
        Returns:
            Отфильтрованный список контактов
        """
        try:
            if query_type == 'name_search' and filter_value:
                # Поиск по имени (case-insensitive)
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('name', f'%{filter_value}%')
                    .limit(50)
                    .execute()
                )
                return response.data
            
            elif query_type == 'company_search' and filter_value:
                # Поиск по компании
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('company', f'%{filter_value}%')
                    .limit(100)
                    .execute()
                )
                return response.data
            
            elif query_type == 'tag_search' and filter_value:
                # Поиск по тегу (используем contains для JSONB)
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .contains('tags', [filter_value])
                    .limit(100)
                    .execute()
                )
                return response.data
            
            else:
                # Сложный запрос - возвращаем топ-30 по дате обновления
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .order('created_at', desc=True)
                    .limit(30)
                    .execute()
                )
                return response.data
                
        except Exception as e:
            print(f"Ошибка получения данных: {e}")
            return []
    
    async def _fetch_contacts_with_interactions(self) -> list:
        """Получить контакты с последними взаимодействиями"""
        try:
            # Используем представление contact_summary для оптимизации
            response = await self._run_io(
                lambda: self.supabase.table('contact_summary').select('*').limit(200).execute()
            )
            return response.data
        except Exception as e:
            print(f"Ошибка получения данных: {e}")
            return []
    
    def _prepare_context(self, contacts_data: list, max_contacts: int = 100) -> str:
        """
        Подготовить контекст для Gemini (ограничить токены)
        
        Args:
            contacts_data: Список контактов
            max_contacts: Максимальное количество контактов для передачи
        
        Returns:
            Форматированный текст контактов
        """
        # Ограничить количество для экономии токенов
        limited_contacts = contacts_data[:max_contacts]
        
        context_lines = []
        for i, contact in enumerate(limited_contacts, 1):
            tags = ', '.join(contact.get('tags', []))
            
            line = f"{i}. {contact['name']}"
            
            if contact.get('company'):
                line += f" ({contact['company']}"
                if contact.get('position'):
                    line += f", {contact['position']}"
                line += ")"
            
            if tags:
                line += f" [Теги: {tags}]"
            if contact.get('bio'):
                short_bio = contact['bio'] if len(contact['bio']) <= 120 else contact['bio'][:117] + '...'
                line += f" | Описание: {short_bio}"
            
            # Добавить информацию о последнем взаимодействии
            if contact.get('last_interaction_date'):
                line += f" | Последний контакт: {contact['last_interaction_date']}"
            
            # Контактные данные
            contact_info = []
            if contact.get('telegram'):
                contact_info.append(f"TG: {contact['telegram']}")
            if contact.get('email'):
                contact_info.append(f"Email: {contact['email']}")
            if contact.get('email2'):
                contact_info.append(f"Email2: {contact['email2']}")
            if contact.get('phone'):
                contact_info.append(f"Тел: {contact['phone']}")
            if contact.get('phone2'):
                contact_info.append(f"Тел2: {contact['phone2']}")
            
            if contact_info:
                line += f" | {', '.join(contact_info)}"
            
            context_lines.append(line)
        
        total_count = len(contacts_data)
        if total_count > max_contacts:
            context_lines.append(f"\n... и ещё {total_count - max_contacts} контактов")
        
        return '\n'.join(context_lines)
    
    def _format_response(self, ai_response: str) -> str:
        """Форматировать ответ для Telegram"""
        # Добавить эмодзи для лучшего восприятия
        formatted = "🤖 **Результат поиска:**\n\n" + ai_response
        return formatted
    
    async def get_contact_stats(self) -> str:
        """Получить статистику по контактам"""
        try:
            # Общее количество контактов
            contacts_resp = await self._run_io(
                lambda: self.supabase.table('contacts').select('id', count='exact').execute()
            )
            total_contacts = contacts_resp.count
            
            # Количество взаимодействий
            interactions_resp = await self._run_io(
                lambda: self.supabase.table('interactions').select('id', count='exact').execute()
            )
            total_interactions = interactions_resp.count
            
            # Контакты с тегами
            tagged_resp = await self._run_io(
                lambda: self.supabase.table('contacts').select('tags').execute()
            )
            all_tags = []
            for contact in tagged_resp.data:
                if contact.get('tags'):
                    all_tags.extend(contact['tags'])
            
            unique_tags = len(set(all_tags))
            
            stats = f"""📊 **Статистика:**

👥 Всего контактов: {total_contacts}
💬 Всего взаимодействий: {total_interactions}
🏷 Уникальных тегов: {unique_tags}
"""
            
            if total_contacts > 0:
                avg_interactions = total_interactions / total_contacts
                stats += f"📈 Среднее взаимодействий на контакт: {avg_interactions:.1f}"
            
            return stats
            
        except Exception as e:
            return f"❌ Ошибка получения статистики: {str(e)}"
