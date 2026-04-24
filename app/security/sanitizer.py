import bleach


def sanitize_message(raw_text: str) -> str:
    cleaned = bleach.clean(raw_text, tags=[], attributes={}, protocols=[], strip=True)
    return " ".join(cleaned.split()).strip()


def sanitize_metadata(payload: dict) -> dict:
    cleaned: dict = {}
    for key, value in payload.items():
        safe_key = bleach.clean(str(key), tags=[], attributes={}, protocols=[], strip=True).strip()
        if isinstance(value, str):
            cleaned[safe_key] = sanitize_message(value)
        else:
            cleaned[safe_key] = value
    return cleaned
