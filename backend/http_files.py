"""Заголовок Content-Disposition для выгрузок.

HTTP-заголовки кодируются latin-1, поэтому подстановка русского имени
скважины напрямую роняла ответ в 500 ('latin-1' codec can't encode…).
Имя отдаётся дважды: ASCII-версия для старых клиентов и RFC 5987
(``filename*=UTF-8''…``) — её понимают все современные браузеры.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')

# Транслитерация кириллицы для ASCII-запасного имени
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def ascii_filename(name: str, fallback: str = "file") -> str:
    """ASCII-имя файла: кириллица транслитерируется, спецсимволы убираются."""
    src = _UNSAFE.sub("_", str(name or "")).strip()
    out = []
    for ch in src:
        low = ch.lower()
        if low in _TRANSLIT:
            t = _TRANSLIT[low]
            out.append(t.upper() if ch.isupper() and t else t)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            norm = unicodedata.normalize("NFKD", ch)
            out.append("".join(c for c in norm if ord(c) < 128))
    cleaned = "".join(out).strip().strip(".")
    return cleaned or fallback


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """Значение заголовка Content-Disposition, безопасное для любых имён."""
    safe = ascii_filename(filename)
    quoted = quote(str(filename or safe), safe="")
    return f"{disposition}; filename=\"{safe}\"; filename*=UTF-8''{quoted}"


def file_headers(filename: str) -> dict:
    """Готовые заголовки для StreamingResponse/Response с выгрузкой файла."""
    return {"Content-Disposition": content_disposition(filename)}
