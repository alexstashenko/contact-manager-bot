"""
Contact Importer Module
Shared logic for importing contacts from vCard, CSV, and JSON formats.
"""

import json
import csv
import vobject
import io
from typing import List, Dict, Any, Union, Tuple
from supabase import Client

def parse_vcard(content: str) -> List[Dict[str, Any]]:
    """Parse vCard content string"""
    contacts = []
    for vcard in vobject.readComponents(content):
        contact = {
            'name': str(vcard.fn.value) if hasattr(vcard, 'fn') else 'Без имени',
            'source': 'import_vcf'
        }
        
        # Email
        if hasattr(vcard, 'email'):
            contact['email'] = str(vcard.email.value)
        
        # Phone
        if hasattr(vcard, 'tel'):
            contact['phone'] = str(vcard.tel.value)
        
        # Organization
        if hasattr(vcard, 'org'):
            contact['company'] = str(vcard.org.value[0]) if vcard.org.value else None
        
        # Position
        if hasattr(vcard, 'title'):
            contact['position'] = str(vcard.title.value)
        
        contacts.append(contact)
    return contacts

def parse_csv(content: Union[str, bytes, io.StringIO, io.BytesIO]) -> List[Dict[str, Any]]:
    """Parse CSV content"""
    # Convert bytes to string if needed
    if isinstance(content, bytes):
        content = content.decode('utf-8')
    
    # If content is a string, wrap it in StringIO
    if isinstance(content, str):
        f = io.StringIO(content)
    else:
        f = content
        # Ensure we are at the beginning of the file
        if hasattr(f, 'seek'):
            f.seek(0)
            
    # If it's bytesIO, we need to wrap it in TextIOWrapper or decode it
    if isinstance(f, io.BytesIO):
        f = io.TextIOWrapper(f, encoding='utf-8')

    reader = csv.DictReader(f)
    
    contacts = []
    for row in reader:
        # Normalize keys to lowercase just in case
        row = {k.lower(): v for k, v in row.items() if k}
        
        contact = {
            'name': row.get('name', 'Без имени'),
            'company': row.get('company'),
            'position': row.get('position'),
            'email': row.get('email'),
            'telegram': row.get('telegram'),
            'phone': row.get('phone'),
            'source': 'import_csv'
        }
        
        # Tags
        if 'tags' in row and row['tags']:
            tags = [tag.strip() for tag in row['tags'].split(',')]
            contact['tags'] = tags
        
        contacts.append(contact)
    return contacts

def parse_json(content: str) -> List[Dict[str, Any]]:
    """Parse JSON content string"""
    data = json.loads(content)
    
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
    return contacts

def batch_insert_contacts(supabase: Client, contacts: List[Dict[str, Any]]) -> Dict[str, int]:
    """Batch insert contacts into Supabase"""
    if not contacts:
        return {'imported': 0, 'duplicates': 0, 'errors': 0}
    
    imported = 0
    errors = 0
    duplicates = 0
    
    for contact in contacts:
        try:
            # Check for duplicates by email or telegram
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
                continue
            
            # Insert
            supabase.table('contacts').insert(contact).execute()
            imported += 1
            
        except Exception as e:
            errors += 1
            print(f"Error importing {contact.get('name', 'Unknown')}: {e}")
    
    return {
        'imported': imported,
        'duplicates': duplicates,
        'errors': errors
    }
