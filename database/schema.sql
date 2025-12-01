-- Contacts Manager Database Schema for Supabase
-- Создано: 2024-12-01

-- ============================================
-- Таблица: contacts (Контакты)
-- ============================================
CREATE TABLE contacts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT,
    position TEXT,
    tags JSONB DEFAULT '[]'::jsonb,
    bio TEXT,
    bio_source TEXT,
    
    -- Контактная информация
    telegram TEXT,
    email TEXT,
    phone TEXT,
    
    -- Метаданные
    source TEXT, -- откуда добавлен: telegram_bot, import_vcf, import_csv, manual
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- Таблица: interactions (Взаимодействия)
-- ============================================
CREATE TABLE interactions (
    id BIGSERIAL PRIMARY KEY,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    type TEXT, -- встреча, звонок, покупка, email, звонок, другое
    note TEXT NOT NULL,
    amount DECIMAL(10, 2), -- для покупок/продаж
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT fk_contact FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

-- ============================================
-- Индексы для оптимизации запросов
-- ============================================

-- Быстрый поиск по тегам
CREATE INDEX idx_contacts_tags ON contacts USING GIN (tags);

-- Поиск по контактным данным
CREATE INDEX idx_contacts_telegram ON contacts(telegram) WHERE telegram IS NOT NULL;
CREATE INDEX idx_contacts_email ON contacts(email) WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_phone ON contacts(phone) WHERE phone IS NOT NULL;

-- Полнотекстовый поиск по имени и компании
CREATE INDEX idx_contacts_name_search ON contacts USING GIN (to_tsvector('russian', name || ' ' || COALESCE(company, '')));

-- Индексы для взаимодействий
CREATE INDEX idx_interactions_contact_id ON interactions(contact_id);
CREATE INDEX idx_interactions_date ON interactions(date DESC);
CREATE INDEX idx_interactions_type ON interactions(type);

-- ============================================
-- Функция автоматического обновления updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггер для автообновления поля updated_at
CREATE TRIGGER update_contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Представление: contact_summary (Сводка по контакту)
-- ============================================
CREATE OR REPLACE VIEW contact_summary AS
SELECT 
    c.id,
    c.name,
    c.company,
    c.position,
    c.tags,
    c.bio,
    c.telegram,
    c.email,
    c.email2,
    c.phone,
    c.phone2,
    COUNT(i.id) as total_interactions,
    MAX(i.date) as last_interaction_date,
    c.created_at
FROM contacts c
LEFT JOIN interactions i ON c.id = i.contact_id
GROUP BY c.id;

-- ============================================
-- Базовые данные для типов взаимодействий
-- ============================================
COMMENT ON COLUMN interactions.type IS 'Типы: встреча, звонок, покупка, email, сообщение, другое';

-- ============================================
-- Row Level Security (Опционально)
-- ============================================
-- Раскомментируйте, если нужна многопользовательская система

-- ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY "Users can manage their own contacts"
--     ON contacts FOR ALL
--     USING (auth.uid() = user_id);
