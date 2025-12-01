"""
Contacts Manager Bot - Handlers
Обработчики команд для работы с контактами
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from supabase import Client
from datetime import datetime
import re
import shlex


class ContactHandlers:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
    
    async def add_contact_interactive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Интерактивное добавление контакта"""
        await update.message.reply_text(
            "📝 Давайте добавим новый контакт!\n\n"
            "Отправьте данные в формате:\n"
            "`Имя Фамилия, Компания, Должность, email@example.com, @telegram`\n\n"
            "Или используйте /quick для быстрого добавления",
            parse_mode='Markdown'
        )
    
    async def quick_add_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Быстрое добавление контакта одной командой
        Формат: /quick Иван Петров, TechCorp, HR Manager, ivan@tech.com, @ivan_hr
        """
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите данные контакта после команды\n\n"
                "Формат:\n"
                "`/quick Имя Фамилия, Компания, Должность, email, @telegram`\n\n"
                "Пример:\n"
                "`/quick Иван Петров, TechCorp, HR Manager, ivan@tech.com, @ivan_hr`",
                parse_mode='Markdown'
            )
            return
        
        # Парсинг данных
        data_string = ' '.join(context.args)
        contact_data = self._parse_contact_string(data_string)
        
        if not contact_data.get('name'):
            await update.message.reply_text("❌ Не удалось определить имя контакта")
            return
        
        # Сохранение в базу
        try:
            result = self.supabase.table('contacts').insert({
                'name': contact_data['name'],
                'company': contact_data.get('company'),
                'position': contact_data.get('position'),
                'email': contact_data.get('email'),
                'telegram': contact_data.get('telegram'),
                'source': 'telegram_bot'
            }).execute()
            
            contact_id = result.data[0]['id']
            
            # Спросить про первую заметку
            context.user_data['pending_note_contact_id'] = contact_id
            
            await update.message.reply_text(
                f"✅ Контакт **{contact_data['name']}** добавлен!\n\n"
                f"Хотите добавить заметку о том, где познакомились? "
                f"Просто отправьте сообщение или используйте /skip",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при сохранении: {str(e)}")
    
    async def add_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Добавить заметку к существующему контакту
        Формат: /note @username Текст заметки
        или: /note email@example.com Текст заметки
        """
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "❌ Укажите контакт и заметку\n\n"
                "Формат:\n"
                "`/note @username Текст заметки`\n"
                "или\n"
                "`/note email@example.com Текст заметки`\n\n"
                "Пример:\n"
                "`/note @ivan_hr Созвонились, обсудили вакансию`",
                parse_mode='Markdown'
            )
            return
        
        identifier = context.args[0]
        note_text = ' '.join(context.args[1:])
        
        # Найти контакт
        contact = await self._find_contact(identifier)
        
        if not contact:
            await update.message.reply_text(
                f"❌ Контакт `{identifier}` не найден\n\n"
                f"Используйте /find для поиска или /quick для добавления",
                parse_mode='Markdown'
            )
            return
        
        # Определить тип взаимодействия
        interaction_type = self._detect_interaction_type(note_text)
        
        # Извлечь сумму, если это покупка
        amount = self._extract_amount(note_text) if interaction_type == 'покупка' else None
        
        # Сохранить взаимодействие
        try:
            self.supabase.table('interactions').insert({
                'contact_id': contact['id'],
                'type': interaction_type,
                'note': note_text,
                'amount': amount,
                'date': datetime.now().date().isoformat()
            }).execute()
            
            await update.message.reply_text(
                f"✅ Заметка добавлена для **{contact['name']}**\n"
                f"Тип: {interaction_type}\n"
                f"Дата: {datetime.now().date().strftime('%d.%m.%Y')}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    async def find_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Поиск контакта по имени, компании или тегу"""
        if not context.args:
            await update.message.reply_text(
                "🔍 Укажите, что искать:\n"
                "`/find Иван`\n"
                "`/find TechCorp`\n"
                "`/find HR`",
                parse_mode='Markdown'
            )
            return
        
        original_query = ' '.join(context.args).strip()
        search_query = original_query.lower()
        
        try:
            query = self.supabase.table('contacts').select('*')
            
            if original_query.startswith('@'):
                query = query.ilike('telegram', original_query)
            elif '@' in original_query and ' ' not in original_query:
                query = query.ilike('email', original_query)
            else:
                like = f"%{search_query}%"
                query = query.or_(
                    f"name.ilike.{like},company.ilike.{like},position.ilike.{like}"
                ).limit(200)
            
            response = query.execute()
            
            results = []
            for contact in response.data:
                if (search_query in contact.get('name', '').lower() or
                    search_query in contact.get('company', '').lower() or
                    search_query in str(contact.get('tags', [])).lower()):
                    results.append(contact)
                elif original_query.startswith('@') and contact.get('telegram') == original_query:
                    results.append(contact)
                elif '@' in original_query and contact.get('email') == original_query:
                    results.append(contact)
            
            if not results:
                await update.message.reply_text(f"❌ Контакты по запросу `{search_query}` не найдены", parse_mode='Markdown')
                return
            
            # Форматировать результаты
            message = f"🔍 Найдено контактов: {len(results)}\n\n"
            
            for contact in results[:10]:  # Показать первые 10
                message += f"👤 **{contact['name']}**\n"
                
                if contact.get('company'):
                    message += f"   🏢 {contact['company']}"
                    if contact.get('position'):
                        message += f", {contact['position']}"
                    message += "\n"
                
                if contact.get('telegram'):
                    message += f"   📱 {contact['telegram']}\n"
                if contact.get('email'):
                    message += f"   📧 {contact['email']}\n"
                
                message += "\n"
            
            if len(results) > 10:
                message += f"... и ещё {len(results) - 10} контактов"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка поиска: {str(e)}")
    
    async def list_recent_contacts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать последние добавленные контакты"""
        try:
            response = self.supabase.table('contacts').select('*').order('created_at', desc=True).limit(10).execute()
            
            if not response.data:
                await update.message.reply_text("📝 Контактов пока нет. Добавьте их с помощью /add или /quick")
                return
            
            message = "📋 **Последние контакты:**\n\n"
            
            for contact in response.data:
                message += f"👤 {contact['name']}\n"
                if contact.get('company'):
                    message += f"   🏢 {contact['company']}\n"
                if contact.get('telegram'):
                    message += f"   📱 {contact['telegram']}\n"
                message += "\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def import_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Получить данные о контакте из Telegram по username и сохранить описание.
        Формат: /profile @username
        """
        if not context.args:
            await update.message.reply_text(
                "🔗 Укажите username контакта:\n"
                "`/profile @username`\n\n"
                "Бот получит имя и описание из Telegram и сохранит их в базу.",
                parse_mode='Markdown'
            )
            return
        
        username = context.args[0].strip()
        if username.startswith('@'):
            username = username[1:]
        
        if not username:
            await update.message.reply_text("❌ Некорректный username.")
            return
        
        telegram_handle = f"@{username}"
        
        try:
            chat = await context.bot.get_chat(username)
        except BadRequest as e:
            error_text = str(e)
            if 'chat not found' in error_text.lower():
                await update.message.reply_text(
                    "❌ Telegram не даёт доступ к профилю: пользователь ещё не писал боту.\n"
                    "Попросите человека открыть бота и набрать любое сообщение, после этого повторите /profile.",
                    parse_mode='Markdown'
                )
            elif 'bot was blocked' in error_text.lower():
                await update.message.reply_text(
                    "❌ Пользователь заблокировал бота. Сначала попросите его разблокировать и написать /start."
                )
            else:
                await update.message.reply_text(f"❌ Не удалось получить профиль: {error_text}")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка Telegram API: {str(e)}")
            return
        
        display_name = chat.full_name or chat.title or telegram_handle
        bio_text = chat.bio or chat.description
        
        contact = await self._find_contact(telegram_handle)
        try:
            if contact:
                updates = {'telegram': telegram_handle}
                if display_name and display_name != contact.get('name'):
                    updates['name'] = display_name
                if bio_text:
                    updates['bio'] = bio_text
                    updates['bio_source'] = 'telegram_profile'
                
                if len(updates) == 1 and updates.get('telegram') == contact.get('telegram'):
                    await update.message.reply_text("ℹ️ Данные уже актуальны, изменений нет.")
                    return
                
                self.supabase.table('contacts').update(updates).eq('id', contact['id']).execute()
                await update.message.reply_text(
                    f"✅ Контакт **{contact['name']}** обновлён.\n"
                    f"{'Описание обновлено.' if bio_text else 'Описание отсутствует в профиле.'}",
                    parse_mode='Markdown'
                )
            else:
                new_contact = {
                    'name': display_name,
                    'telegram': telegram_handle,
                    'bio': bio_text,
                    'bio_source': 'telegram_profile',
                    'source': 'telegram_profile'
                }
                self.supabase.table('contacts').insert(new_contact).execute()
                await update.message.reply_text(
                    f"✅ Контакт **{display_name}** создан на основе профиля Telegram.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при сохранении: {str(e)}")
    
    async def edit_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Редактирование существующего контакта.
        Формат: /edit @username поле=значение поле2="значение с пробелами"
        Доступные поля: name, company, position, email, telegram, phone, tags, bio
        """
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "✏️ Укажите контакт и изменения.\n\n"
                "Формат:\n"
                "`/edit @username company=\"New Corp\" position=\"Lead\"`\n"
                "`/edit ivan@tech.com name=\"Иван Петров\" tags=\"HR, рекрутинг\"`\n\n"
                "Доступные поля: name, company, position, email, telegram, phone, tags, bio\n"
                "Используйте кавычки, если в значении есть пробелы.",
                parse_mode='Markdown'
            )
            return
        
        identifier = context.args[0]
        updates = self._parse_update_fields(context.args[1:])
        
        if not updates:
            await update.message.reply_text(
                "❌ Не удалось распознать изменения. Используйте формат `поле=значение`.",
                parse_mode='Markdown'
            )
            return
        
        contact = await self._find_contact(identifier)
        if not contact:
            await update.message.reply_text(
                f"❌ Контакт `{identifier}` не найден.",
                parse_mode='Markdown'
            )
            return
        
        try:
            self.supabase.table('contacts').update(updates).eq('id', contact['id']).execute()
            fields_pretty = ', '.join(f"{key} → {value}" if key != 'tags' else f"tags → {', '.join(value)}"
                                      for key, value in updates.items())
            await update.message.reply_text(
                f"✅ Контакт **{contact['name']}** обновлён.\n"
                f"Изменения: {fields_pretty}",
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при обновлении: {str(e)}")
    
    # === Вспомогательные методы ===
    
    def _parse_contact_string(self, data_string: str) -> dict:
        """Парсинг строки с данными контакта"""
        parts = [p.strip() for p in data_string.split(',')]
        
        contact_data = {
            'name': parts[0] if len(parts) > 0 else None,
            'company': parts[1] if len(parts) > 1 else None,
            'position': parts[2] if len(parts) > 2 else None,
        }
        
        # Найти email и telegram среди оставшихся частей
        for part in parts[3:]:
            if '@' in part:
                if part.startswith('@'):
                    contact_data['telegram'] = part
                elif re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', part):
                    contact_data['email'] = part
            elif re.match(r'^\+?\d[\d\s\-\(\)]+$', part):
                contact_data['phone'] = part
        
        return contact_data
    
    async def _find_contact(self, identifier: str) -> dict:
        """Найти контакт по telegram или email"""
        try:
            if identifier.startswith('@'):
                response = self.supabase.table('contacts').select('*').eq('telegram', identifier).execute()
            elif '@' in identifier:
                response = self.supabase.table('contacts').select('*').eq('email', identifier).execute()
            else:
                # Попытка поиска по имени
                response = self.supabase.table('contacts').select('*').ilike('name', f'%{identifier}%').execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            print(f"Ошибка поиска контакта: {e}")
            return None
    
    def _detect_interaction_type(self, note_text: str) -> str:
        """Определить тип взаимодействия по ключевым словам"""
        note_lower = note_text.lower()
        
        if any(word in note_lower for word in ['купил', 'покупка', 'оплатил', 'заказал', 'продал']):
            return 'покупка'
        elif any(word in note_lower for word in ['встреча', 'встретились', 'кофе', 'обед', 'конференция']):
            return 'встреча'
        elif any(word in note_lower for word in ['звонок', 'созвонились', 'позвонил']):
            return 'звонок'
        elif any(word in note_lower for word in ['email', 'письмо', 'написал']):
            return 'email'
        else:
            return 'другое'
    
    def _extract_amount(self, note_text: str) -> float:
        """Извлечь сумму из текста заметки"""
        # Поиск числа с рублями, долларами и т.д.
        pattern = r'(\d[\d\s]*(?:\.\d+)?)\s*(?:₽|руб|rub|\$|usd|€|eur)?'
        match = re.search(pattern, note_text.replace(',', '.'))
        
        if match:
            amount_str = match.group(1).replace(' ', '')
            try:
                return float(amount_str)
            except ValueError:
                return None
        
        return None
    
    def _parse_update_fields(self, args: list) -> dict:
        """Разобрать список аргументов вида поле=значение"""
        updates = {}
        allowed_fields = {'name', 'company', 'position', 'email', 'telegram', 'phone', 'tags', 'bio'}
        
        arg_string = ' '.join(args)
        try:
            tokens = shlex.split(arg_string)
        except ValueError:
            return {}
        
        for token in tokens:
            if '=' not in token:
                continue
            field, value = token.split('=', 1)
            field = field.strip().lower()
            value = value.strip()
            
            if field not in allowed_fields or not value:
                continue
            
            if field == 'tags':
                tags = [tag.strip() for tag in value.split(',') if tag.strip()]
                updates[field] = tags
            else:
                updates[field] = value
        
        return updates

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загрузки файлов с контактами"""
        document = update.message.document
        file_name = document.file_name
        
        # Проверка размера (например, до 5МБ)
        if document.file_size > 5 * 1024 * 1024:
            await update.message.reply_text("❌ Файл слишком большой. Максимальный размер 5 МБ.")
            return

        status_message = await update.message.reply_text("📥 Скачиваю и обрабатываю файл...")
        
        try:
            file = await context.bot.get_file(document.file_id)
            file_byte_array = await file.download_as_bytearray()
            
            # Импорт
            import io
            import importer
            
            contacts = []
            
            if file_name.lower().endswith('.vcf'):
                content = file_byte_array.decode('utf-8')
                contacts = importer.parse_vcard(content)
            elif file_name.lower().endswith('.csv'):
                content = io.BytesIO(file_byte_array)
                contacts = importer.parse_csv(content)
            elif file_name.lower().endswith('.json'):
                content = file_byte_array.decode('utf-8')
                contacts = importer.parse_json(content)
            else:
                await status_message.edit_text(
                    "❌ Неподдерживаемый формат файла.\n"
                    "Поддерживаются: .vcf, .csv, .json"
                )
                return
            
            if not contacts:
                await status_message.edit_text("⚠️ В файле не найдено контактов.")
                return
            
            # Вставка в базу
            result = importer.batch_insert_contacts(self.supabase, contacts)
            
            await status_message.edit_text(
                f"📊 **Результаты импорта:**\n\n"
                f"✅ Импортировано: {result['imported']}\n"
                f"⚠️ Пропущено (дубликаты): {result['duplicates']}\n"
                f"❌ Ошибок: {result['errors']}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await status_message.edit_text(f"❌ Ошибка при обработке файла: {str(e)}")
