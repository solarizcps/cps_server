"""Çoklu mağaza API bilgilerini kullanıcının ev dizininde saklar.

Her mağazanın kendi Seller ID / API Key / API Secret bilgisi vardır.
Bilgiler proje klasörüne değil, ~/.trendyol-kargo/config.json içinde tutulur;
böylece proje klasörünü paylaşsan bile API bilgilerin sızmaz.

config.json yapısı:
{
  "stores": {
    "Solariz": {"sellerId": "...", "apiKey": "...", "apiSecret": "..."},
    "Epona":   {"sellerId": "...", "apiKey": "...", "apiSecret": "..."}
  }
}
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".trendyol-kargo"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Sabit mağazalar. İleride yenisi gerekirse buraya eklenir.
STORE_NAMES = ["Solariz", "Epona"]

_FIELDS = ("sellerId", "apiKey", "apiSecret")


def _empty_store():
    return {field: "" for field in _FIELDS}


def _read_raw():
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _normalize(raw):
    """Ham veriyi {store_name: {fields}} biçimine getirir; eski tek-mağaza
    formatını ilk mağazaya (Solariz) taşır."""
    stores = {}

    # Eski format (tek mağaza, üst düzeyde sellerId/apiKey/apiSecret) -> Solariz
    if raw and "stores" not in raw and any(k in raw for k in _FIELDS):
        stores[STORE_NAMES[0]] = {f: str(raw.get(f, "")).strip() for f in _FIELDS}

    for name, data in (raw.get("stores") or {}).items():
        data = data or {}
        stores[name] = {f: str(data.get(f, "")).strip() for f in _FIELDS}

    # Tanımlı tüm mağazalar için en azından boş kayıt bulunsun
    for name in STORE_NAMES:
        stores.setdefault(name, _empty_store())

    return stores


def load_all_stores():
    """Tüm mağazaları {name: {sellerId, apiKey, apiSecret}} olarak döndürür."""
    return _normalize(_read_raw())


def get_store(name):
    """Tek bir mağazanın bilgilerini döndürür (yoksa boş)."""
    return load_all_stores().get(name, _empty_store())


def save_store(name, seller_id, api_key, api_secret):
    """Bir mağazanın API bilgilerini kaydeder, diğerlerini korur."""
    stores = load_all_stores()
    stores[name] = {
        "sellerId": str(seller_id).strip(),
        "apiKey": str(api_key).strip(),
        "apiSecret": str(api_secret).strip(),
    }
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"stores": stores}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stores[name]


def is_store_configured(name):
    """Mağazanın tüm zorunlu alanları dolu mu?"""
    store = get_store(name)
    return all(store.get(field) for field in _FIELDS)
