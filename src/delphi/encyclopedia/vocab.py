"""Controlled vocabularies of the knowledge base with Ukrainian labels.

Single source for the seed validation tests, the services and the UI.
"""

ENTITY_TYPES: dict[str, str] = {
    "god": "Бог / божество",
    "titan": "Титан",
    "hero": "Герой",
    "mortal": "Смертний",
    "creature": "Істота",
    "place": "Місце",
    "artifact": "Артефакт",
}

PLACE_KINDS: dict[str, str] = {
    "sanctuary": "Святилище",
    "city": "Місто",
    "mountain": "Гора",
    "island": "Острів",
    "river": "Ріка / озеро",
    "region": "Край",
}

CERTAINTY: dict[str, str] = {
    "high": "достовірна локалізація",
    "medium": "приблизна локалізація",
    "low": "традиційне ототожнення",
    "none": "міфічне місце, поза картою",
}

MYTH_CYCLES: dict[str, str] = {
    "theogony": "Теогонія",
    "olympians": "Олімпійські боги",
    "heracles": "Геракл",
    "perseus": "Персей",
    "theseus": "Тесей",
    "argonauts": "Аргонавти",
    "theban": "Фіванський цикл",
    "trojan": "Троянський цикл",
    "other": "Інші міфи",
}

MYTH_ROLES: dict[str, str] = {
    "protagonist": "головний герой",
    "antagonist": "супротивник",
    "helper": "помічник",
    "victim": "жертва",
    "participant": "учасник",
    "location": "місце дії",
    "object": "предмет",
}

RELATION_TYPES: set[str] = {
    "parent_of",
    "spouse_of",
    "sibling_of",
    "worshipped_at",
    "born_at",
    "ruled",
    "killed",
}

# Labels from the point of view of the entity on the card:
# (outgoing: card entity is src, incoming: card entity is dst)
RELATION_LABELS: dict[str, tuple[str, str]] = {
    "parent_of": ("Діти", "Батьки"),
    "spouse_of": ("Подружжя", "Подружжя"),
    "sibling_of": ("Брати й сестри", "Брати й сестри"),
    "worshipped_at": ("Місця культу", "Тут шанували"),
    "born_at": ("Місце народження", "Тут народилися"),
    "ruled": ("Правив(-ла) у", "Правителі"),
    "killed": ("Убив(-ла) / переміг(-ла)", "Загинув(-ла) від"),
}

# source_ref values that are not references to an ancient text
UNVERIFIED_REFS: set[str] = {"Wikidata", "manual"}


def is_verified(source_ref: str) -> bool:
    return source_ref not in UNVERIFIED_REFS
