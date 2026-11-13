"""Conservative ordering of explicitly zoned observation timestamps."""
import re
from datetime import datetime, timezone


def _key(value):
    text = str(value or '')
    try:
        if re.fullmatch(r'\d{10}|\d{13}', text):
            return datetime.fromtimestamp(int(text)/(1000 if len(text) == 13 else 1), timezone.utc)
        if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', text):
            return None
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def observation_first(current, incoming):
    return _bound(current, incoming, first=True)


def observation_last(current, incoming):
    return _bound(current, incoming, first=False)


def _bound(current, incoming, *, first):
    if current in (None, ''):
        return incoming
    before, after = _key(current), _key(incoming)
    if before is None or after is None:
        return current
    return incoming if (after < before if first else after > before) else current
