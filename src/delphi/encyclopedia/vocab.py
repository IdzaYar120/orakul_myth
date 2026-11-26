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


# English labels for the bilingual API (the website and the mobile app); same keys as above.
ENTITY_TYPES_EN: dict[str, str] = {
    "god": "God / deity",
    "titan": "Titan",
    "hero": "Hero",
    "mortal": "Mortal",
    "creature": "Creature",
    "place": "Place",
    "artifact": "Artifact",
}
PLACE_KINDS_EN: dict[str, str] = {
    "sanctuary": "Sanctuary",
    "city": "City",
    "mountain": "Mountain",
    "island": "Island",
    "river": "River / lake",
    "region": "Region",
}
CERTAINTY_EN: dict[str, str] = {
    "high": "reliable location",
    "medium": "approximate location",
    "low": "traditional identification",
    "none": "mythical place, off the map",
}
MYTH_CYCLES_EN: dict[str, str] = {
    "theogony": "Theogony",
    "olympians": "Olympian gods",
    "heracles": "Heracles",
    "perseus": "Perseus",
    "theseus": "Theseus",
    "argonauts": "Argonauts",
    "theban": "Theban cycle",
    "trojan": "Trojan cycle",
    "other": "Other myths",
}
MYTH_ROLES_EN: dict[str, str] = {
    "protagonist": "protagonist",
    "antagonist": "antagonist",
    "helper": "helper",
    "victim": "victim",
    "participant": "participant",
    "location": "setting",
    "object": "object",
}


def vocab_labels(lang: str = "uk") -> dict[str, dict[str, str]]:
    """All label dictionaries in one language, for UI filters and badges."""
    if lang == "en":
        return {
            "entity_types": ENTITY_TYPES_EN,
            "place_kinds": PLACE_KINDS_EN,
            "certainty": CERTAINTY_EN,
            "myth_cycles": MYTH_CYCLES_EN,
            "myth_roles": MYTH_ROLES_EN,
        }
    return {
        "entity_types": ENTITY_TYPES,
        "place_kinds": PLACE_KINDS,
        "certainty": CERTAINTY,
        "myth_cycles": MYTH_CYCLES,
        "myth_roles": MYTH_ROLES,
    }
