-- Функция для безопасного слияния дубликатов контактов
-- Выполняется в транзакции для предотвращения race conditions

CREATE OR REPLACE FUNCTION merge_contacts_by_name(contact_name TEXT)
RETURNS JSON AS $$
DECLARE
    master_contact RECORD;
    duplicate_contact RECORD;
    all_phones TEXT[];
    all_emails TEXT[];
    all_tags JSONB;
    result JSON;
    deleted_count INT := 0;
BEGIN
    -- Блокируем все найденные контакты для предотвращения race condition
    SELECT * INTO master_contact
    FROM contacts
    WHERE name ILIKE contact_name
    ORDER BY 
        CASE WHEN telegram IS NOT NULL THEN 2 ELSE 0 END +
        CASE WHEN email IS NOT NULL THEN 2 ELSE 0 END +
        CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN company IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN bio IS NOT NULL THEN 1 ELSE 0 END DESC
    LIMIT 1
    FOR UPDATE;
    
    -- Если контакт не найден
    IF master_contact IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'error', 'Contact not found'
        );
    END IF;
    
    -- Собираем все уникальные телефоны и email'ы
    all_phones := ARRAY[]::TEXT[];
    all_emails := ARRAY[]::TEXT[];
    all_tags := '[]'::JSONB;
    
    IF master_contact.phone IS NOT NULL THEN
        all_phones := array_append(all_phones, master_contact.phone);
    END IF;
    IF master_contact.phone2 IS NOT NULL THEN
        all_phones := array_append(all_phones, master_contact.phone2);
    END IF;
    IF master_contact.email IS NOT NULL THEN
        all_emails := array_append(all_emails, master_contact.email);
    END IF;
    IF master_contact.email2 IS NOT NULL THEN
        all_emails := array_append(all_emails, master_contact.email2);
    END IF;
    IF master_contact.tags IS NOT NULL THEN
        all_tags := master_contact.tags;
    END IF;
    
    -- Проходим по всем дубликатам
    FOR duplicate_contact IN
        SELECT * FROM contacts
        WHERE name ILIKE contact_name
        AND id != master_contact.id
        FOR UPDATE
    LOOP
        deleted_count := deleted_count + 1;
        
        -- Собираем данные из дубликата
        IF duplicate_contact.phone IS NOT NULL AND NOT (duplicate_contact.phone = ANY(all_phones)) THEN
            all_phones := array_append(all_phones, duplicate_contact.phone);
        END IF;
        IF duplicate_contact.phone2 IS NOT NULL AND NOT (duplicate_contact.phone2 = ANY(all_phones)) THEN
            all_phones := array_append(all_phones, duplicate_contact.phone2);
        END IF;
        IF duplicate_contact.email IS NOT NULL AND NOT (duplicate_contact.email = ANY(all_emails)) THEN
            all_emails := array_append(all_emails, duplicate_contact.email);
        END IF;
        IF duplicate_contact.email2 IS NOT NULL AND NOT (duplicate_contact.email2 = ANY(all_emails)) THEN
            all_emails := array_append(all_emails, duplicate_contact.email2);
        END IF;
        
        -- Объединяем теги
        IF duplicate_contact.tags IS NOT NULL THEN
            all_tags := all_tags || duplicate_contact.tags;
        END IF;
        
        -- Заполняем пустые поля master из дубликата
        IF master_contact.company IS NULL AND duplicate_contact.company IS NOT NULL THEN
            master_contact.company := duplicate_contact.company;
        END IF;
        IF master_contact.position IS NULL AND duplicate_contact.position IS NOT NULL THEN
            master_contact.position := duplicate_contact.position;
        END IF;
        IF master_contact.telegram IS NULL AND duplicate_contact.telegram IS NOT NULL THEN
            master_contact.telegram := duplicate_contact.telegram;
        END IF;
        IF master_contact.bio IS NULL AND duplicate_contact.bio IS NOT NULL THEN
            master_contact.bio := duplicate_contact.bio;
        END IF;
        
        -- Переносим все взаимодействия на master контакт
        UPDATE interactions
        SET contact_id = master_contact.id
        WHERE contact_id = duplicate_contact.id;
        
        -- Удаляем дубликат
        DELETE FROM contacts WHERE id = duplicate_contact.id;
    END LOOP;
    
    -- Обновляем master контакт со всеми собранными данными
    UPDATE contacts SET
        phone = CASE WHEN array_length(all_phones, 1) >= 1 THEN all_phones[1] ELSE phone END,
        phone2 = CASE WHEN array_length(all_phones, 1) >= 2 THEN all_phones[2] ELSE NULL END,
        email = CASE WHEN array_length(all_emails, 1) >= 1 THEN all_emails[1] ELSE email END,
        email2 = CASE WHEN array_length(all_emails, 1) >= 2 THEN all_emails[2] ELSE NULL END,
        tags = all_tags,
        company = master_contact.company,
        position = master_contact.position,
        telegram = master_contact.telegram,
        bio = master_contact.bio,
        updated_at = NOW()
    WHERE id = master_contact.id;
    
    -- Возвращаем результат
    result := json_build_object(
        'success', true,
        'master_id', master_contact.id,
        'master_name', master_contact.name,
        'deleted_count', deleted_count
    );
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;
