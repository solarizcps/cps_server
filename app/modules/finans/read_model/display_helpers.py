"""
display_helpers.py — Finans modülü sunum yardımcıları (display-only)

KURAL: Bu modül hiçbir zaman DB'ye yazmaz.
       Yalnız Jinja template render'da kullanılır.
"""
from __future__ import annotations
import re as _re

# Kısaltmalar: büyük harf korunur (büyük/küçük kaşımı önler)
_KNOWN_ABBREVS = frozenset([
    'A.Ş.', 'LTD.', 'ŞTİ.', 'O.S.B', 'OSB', 'PVC', 'EVA',
    'A.G.', 'VE', 'İTH.', 'SAN.', 'TİC.', 'DIŞ', 'İÇ',
    'LİMİTED', 'ANONİM', 'ORTAKLIĞI', 'İTH', 'A.Ş', 'LTD', 'ŞTİ',
])
_ABBREV_UPPER = frozenset(s.upper() for s in _KNOWN_ABBREVS)

# Türkçe büyük harf çevirme tablosu (lower → upper)
_TR_UPPER = str.maketrans(
    'abcçdefgğhıijklmnoöprsştuüvyz',
    'ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ',
)

# Türkçe küçük harf çevirme tablosu (upper → lower, İ→i, I→ı önemli)
_TR_LOWER = str.maketrans(
    'ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ',
    'abcçdefgğhıijklmnoöprsştuüvyz',
)


def _is_abbrev(word: str) -> bool:
    """Kelime kısaltma veya korunan token mu?"""
    wu = word.upper()
    if wu in _ABBREV_UPPER:
        return True
    # Noktalı kısaltma: yalnız büyük harf + nokta (ör. A.Ş.)
    if _re.fullmatch(r'[A-ZÇĞİÖŞÜ\.]+', wu) and '.' in wu:
        return True
    # Kısa all-caps token (≤3 harf, hepsi büyük): OSB, PVC vb.
    if len(wu) <= 3 and wu.isalpha() and wu == word:
        return True
    return False


def tr_title_case(s: str) -> str:
    """
    Türkçe bilinçli title-case dönüşümü.

    Kurallar:
    - Her kelimenin ilk harfi büyük, geri kalan küçük.
    - Türkçe büyük harf: i→İ, ı→I, ş→Ş, ç→Ç vb.
    - Türkçe küçük harf: İ→i, I→ı, Ş→ş, Ç→ç vb.
    - Kısaltmalar (A.Ş., LTD., OSB, PVC) tamamen büyük kalır.
    - Kaynak DB string'i değiştirilmez — yalnız return değeri etkilenir.
    """
    if not s:
        return s
    words = s.split()
    result = []
    for w in words:
        if not w:
            continue
        if _is_abbrev(w):
            result.append(w.upper())
        else:
            first = w[0].translate(_TR_UPPER)
            rest = w[1:].translate(_TR_LOWER) if len(w) > 1 else ''
            result.append(first + rest)
    return ' '.join(result)


def cari_adi_display(s: object) -> str:
    """
    Jinja filter entry-point: firma adını title-case ile döner.
    DB'ye yazmaz. Sunum katmanında kullanılır.
    """
    return tr_title_case(str(s or ''))
