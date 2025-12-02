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
        
        Новая стратегия для 7000+ контактов:
        - Извлекаем ключевые слова из запроса
        - SQL фильтрует все подходящие контакты (не ограничиваем!)
        - AI только красиво форматирует результаты
        
        Returns:
            {
                'type': 'name_search' | 'company_search' | 'position_search' | 'general',
                'filter': search terms (string or list)
            }
        """
        import re
        
        query_lower = query.lower().strip()
        original_query = query.strip()
        
        # Поиск по компании (явные маркеры)
        company_patterns = [
            r'(?:из|в)\s+([А-ЯЁа-яё\w\s]+)',
            r'([А-ЯЁа-яё\w]+)\s+компания',
        ]
        
        for pattern in company_patterns:
            match = re.search(pattern, original_query)
            if match:
                return {'type': 'company_search', 'filter': match.group(1).strip()}
        
        # Поиск по должности (ключевые слова)
        position_keywords = ['тестировщик', 'разработчик', 'менеджер', 'дизайнер', 'маркетолог', 'hr']
        for keyword in position_keywords:
            if keyword in query_lower:
                # Убираем окончания
                base = re.sub(r'(ов|ам|ами|ах|а|у|ом|е|и)$', '', keyword)
                return {'type': 'position_search', 'filter': base}
        
        # Извлечение имён/слов для поиска
        # Убираем стоп-слова и извлекаем значимые слова
        stop_words = {'найди', 'найд', 'покажи', 'покаж', 'кто', 'мне', 'нужен', 'нужна', 'нужны', 
                      'все', 'всех', 'человек', 'людей', 'контакт', 'контакты', 'есть', 'у', 'меня',
                      'из', 'в', 'с', 'на', 'по', 'для', 'или', 'и', 'а', 'но'}
        
        # Разбиваем на слова и фильтруем
        words = re.findall(r'[А-ЯЁа-яёA-Za-z]+', original_query)
        search_terms = [w for w in words if w.lower() not in stop_words and len(w) > 1]
        
        if search_terms:
            # Если есть слова с заглавной буквы - скорее всего имена
            capitalized = [w for w in search_terms if w[0].isupper()]
            if capitalized:
                return {'type': 'name_search', 'filter': capitalized}
            # Иначе ищем по всем словам
            return {'type': 'name_search', 'filter': search_terms}
        
        # Если ничего не нашли - общий поиск
        return {'type': 'general', 'filter': query}
    
    async def process_query(self, user_query: str) -> str:
        """
        Обработка естественноязычного запроса пользователя с умной предфильтрацией.
        
        Args:
            user_query: Вопрос пользователя (например: "Кто у меня есть из HR?")
        
        Returns:
            Форматированный ответ для отправки в Telegram
        """
        try:
            # Шаг 1: Анализ запроса
            query_analysis = self._analyze_query(user_query)
            
            # Шаг 2: Получить контакты с учетом фильтрации
            contacts_data = await self._fetch_filtered_contacts(
                query_type=query_analysis['type'],
                filter_value=query_analysis['filter']
            )
            
            if not contacts_data:
                return "❌ Контакты не найдены. Попробуйте изменить запрос."
            
            total_found = len(contacts_data)
            
            # Шаг 3: Ограничить до 10 для показа, но AI знает сколько всего
            display_contacts = contacts_data[:10]
            context = self._prepare_context(display_contacts, max_contacts=10)
            
            # Шаг 4: Создать промпт
            # AI теперь ТОЛЬКО форматирует результаты, НЕ ищет
            prompt = f"""У пользователя {total_found} контакт(ов), подходящих под запрос "{user_query}".

Вот первые {len(display_contacts)} из них:

{context}

ЗАДАЧА: Красиво отформатируй эти контакты для пользователя.

Для каждого контакта покажи:
- Имя
- Компания и должность (если есть)
- Контактные данные (Email, Telegram, Телефон)
- Последнее взаимодействие (если есть)

В КОНЦЕ обязательно добавь:
{"- Найдено еще " + str(total_found - 10) + " контакт(ов)" if total_found > 10 else ""}

Отвечай по-русски, кратко и структурированно."""

            # Шаг 5: Получить ответ от Gemini
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return self._format_response(response.text)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"❌ Ошибка при обработке запроса: {str(e)}"
    
    async def _fetch_filtered_contacts(self, query_type: str, filter_value) -> list:
        """
        Получить контакты с SQL фильтрацией.
        
        Новый подход: SQL находит ВСЕ подходящие контакты (без лимитов),
        AI потом отформатирует топ-10 и скажет "найдено еще N"
        
        Args:
            query_type: 'name_search' | 'company_search' | 'position_search' | 'general'
            filter_value: строка или список строк для поиска
        
        Returns:
            Список ВСЕХ найденных контактов
        """
        try:
            if query_type == 'name_search' and filter_value:
                # Поиск по нескольким словам (имя, фамилия, отчество)
                search_terms = filter_value if isinstance(filter_value, list) else [filter_value]
                
                # Строим OR условия для каждого слова
                conditions = []
                for term in search_terms:
                    term_lower = term.lower()
                    conditions.append(f"name.ilike.%{term_lower}%")
                
                or_condition = ",".join(conditions)
                
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .or_(or_condition)
                    .order('created_at', desc=True)
                    .execute()  # БЕЗ ЛИМИТА - находим всех!
                )
                return response.data
            
            elif query_type == 'company_search' and filter_value:
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('company', f'%{filter_value}%')
                    .order('created_at', desc=True)
                    .execute()
                )
                return response.data
            
            elif query_type == 'position_search' and filter_value:
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .ilike('position', f'%{filter_value}%')
                    .order('created_at', desc=True)
                    .execute()
                )
                return response.data
            
            else:
                # General search - топ-100 последних
                response = await self._run_io(
                    lambda: self.supabase.table('contact_summary')
                    .select('*')
                    .order('created_at', desc=True)
                    .limit(100)
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
