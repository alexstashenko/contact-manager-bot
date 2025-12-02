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
        
        Стратегия: Фильтруем только очевидные случаи (компания, должность).
        Всё остальное передаём AI - он умнее и лучше поймёт контекст.
        
        Returns:
            {
                'type': 'company_search' | 'position_search' | 'ai_search',
                'filter': extracted search term or None
            }
        """
        import re
        
        query_lower = query.lower().strip()
        
        # Поиск по компании (явные маркеры)
        company_patterns = [
            r'(?:из|в)\s+([А-ЯЁа-яё\w\s]+)',  # "из Google", "в Яндекс"
            r'([А-ЯЁа-яё\w]+)\s+компания',
        ]
        
        for pattern in company_patterns:
            match = re.search(pattern, query)
            if match:
                return {'type': 'company_search', 'filter': match.group(1).strip()}
        
        # Поиск по должности (ключевые слова)
        position_patterns = [
            r'\b(тестировщик\w*)\b',
            r'\b(разработчик\w*)\b',
            r'\b(менеджер\w*)\b',
            r'\b(дизайнер\w*)\b',
            r'\b(маркетолог\w*)\b',
            r'\bhr\b',
        ]
        
        for pattern in position_patterns:
            match = re.search(pattern, query_lower)
            if match:
                # Убираем окончания для поиска
                position = match.group(1) if match.lastindex else 'hr'
                base_position = re.sub(r'(ов|ам|ами|ах|а|у|ом|е|и)$', '', position)
                return {'type': 'position_search', 'filter': base_position}
        
        # Всё остальное - пусть AI сам разбирается (имена, сложные запросы, и т.д.)
        return {'type': 'ai_search', 'filter': None}
    
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
        # Для специфичных запросов (компания, должность) - все найденные
        # Для AI search - передаём до 100 контактов для анализа
        if query_analysis['type'] in ['company_search', 'position_search']:
            max_contacts = len(contacts_data)
        else:
            max_contacts = min(100, len(contacts_data))
        
        context = self._prepare_context(contacts_data, max_contacts=max_contacts)
        
        # Шаг 4: Создать промпт
        prompt = f"""Ты — помощник для управления контактами. У пользователя есть следующие контакты:

{context}

Вопрос пользователя: {user_query}

ВАЖНО: Если пользователь просто написал имя или имя и фамилию (например: "Иван", "Иван Петров") или использовал глаголы "покажи", "выведи", "открой", "найди" с именем — это значит, что нужно показать ПОЛНУЮ карточку контакта со ВСЕМИ доступными данными.

Для каждого контакта указывай:
- Имя
- Компания и должность (если есть)
- ВСЕ контактные данные (Email, Telegram, Телефон - показывай все, что есть)
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
            query_type: Тип запроса ('company_search', 'position_search', 'ai_search')
            filter_value: Значение для фильтрации (компания, должность)
        
        Returns:
            Отфильтрованный список контактов
        """
        try:
            if query_type == 'company_search' and filter_value:
                # Поиск по компании
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('company', f'%{filter_value}%')
                    .order('created_at', desc=True)
                    .limit(100)
                    .execute()
                )
                return response.data
            
            elif query_type == 'position_search' and filter_value:
                # Поиск по должности
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('position', f'%{filter_value}%')
                    .order('created_at', desc=True)
                    .limit(100)
                    .execute()
                )
                return response.data
            
            else:
                # AI Search - возвращаем все контакты (или топ-200 для production)
                # AI сам разберётся что искать: имя, фамилию, заметки, всё что угодно
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .order('created_at', desc=True)
                    .limit(200)  # Увеличили лимит для лучшего контекста
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

            if contact.get('phone'):
                contact_info.append(f"Тел: {contact['phone']}")

            
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
