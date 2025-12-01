"""
Contacts Manager Bot - AI Interface
Обработка естественноязычных запросов через Gemini API
"""

import os
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
    
    async def process_query(self, user_query: str) -> str:
        """
        Обработка естественноязычного запроса пользователя
        
        Args:
            user_query: Вопрос пользователя (например: "Кто у меня есть из HR?")
        
        Returns:
            Форматированный ответ для отправки в Telegram
        """
        
        # Шаг 1: Получить все контакты из базы
        contacts_data = await self._fetch_contacts_with_interactions()
        
        if not contacts_data:
            return "❌ В базе данных пока нет контактов. Добавьте их с помощью /add или /quick"
        
        # Шаг 2: Подготовить контекст для Gemini
        context = self._prepare_context(contacts_data)
        
        # Шаг 3: Создать промпт
        prompt = f"""Ты — помощник для управления контактами. У пользователя есть следующие контакты:

{context}

Вопрос пользователя: {user_query}

Проанализируй данные и дай краткий, структурированный ответ. Если это список людей, укажи:
- Имя
- Компания и должность (если есть)
- Последнее взаимодействие (если есть)

Отвечай по-русски, кратко и по делу."""

        # Шаг 4: Получить ответ от Gemini
        try:
            response = self.model.generate_content(prompt)
            return self._format_response(response.text)
        except Exception as e:
            return f"❌ Ошибка при обработке запроса: {str(e)}"
    
    async def _fetch_contacts_with_interactions(self) -> list:
        """Получить контакты с последними взаимодействиями"""
        try:
            # Используем представление contact_summary для оптимизации
            response = self.supabase.table('contact_summary').select('*').limit(200).execute()
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
            contacts_resp = self.supabase.table('contacts').select('id', count='exact').execute()
            total_contacts = contacts_resp.count
            
            # Количество взаимодействий
            interactions_resp = self.supabase.table('interactions').select('id', count='exact').execute()
            total_interactions = interactions_resp.count
            
            # Контакты с тегами
            tagged_resp = self.supabase.table('contacts').select('tags').execute()
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
