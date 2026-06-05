# -*- coding: utf-8 -*-
"""
CPS DEV - Tasks Modulu - Notification Helper
=============================================

bildirim_log tablosuna kayit eklemek icin TEK helper.
Yeni tablo YOK, mevcut bildirim_log kullanilir.

bildirim_log SEMA:
    id                INTEGER PK
    kullanici_id      INTEGER NOT NULL    -- Kime gidecek
    rol               TEXT    NOT NULL    -- usta/admin/...
    tip               TEXT    NOT NULL    -- gorev_yeni/...
    mesaj             TEXT    NOT NULL
    veri_json         TEXT
    gonderim_zamani   TEXT    DEFAULT datetime('now')
    okundu_mu         INTEGER DEFAULT 0
    okundu_zamani     TEXT
    push_gonderildi_mi INTEGER DEFAULT 0

KULLANIM:
    from modules.tasks.notify import create_task_notification, NOTIFICATION_TYPES

    create_task_notification(
        kullanici_id=12,
        rol='usta',
        tip='gorev_yeni',
        mesaj='Sana yeni bir gorev atandi: B-2 onceligi',
        veri={"task_id": 5, "priority": "kritik"}
    )

NOT:
    kullanici_id  -> bildirim_log INTEGER bekliyor.
                     Bu, tasks_users.id veya sistem_kullanici.Id olabilir.
                     Service katmani hangisini kullanacagina karar verir.
"""

import json
from db import qexec


# ============================================================
# TANIMLI BILDIRIM TIPLERI
# ============================================================
NOTIFICATION_TYPES = {
    "gorev_yeni":              "Yeni gorev atandi",
    "gorev_basladi":           "Gorev baslatildi",
    "gorev_tamamlandi":        "Gorev tamamlandi",
    "gorev_onay_bekliyor":     "Gorev onayi bekliyor",
    "gorev_onaylandi":         "Gorev onaylandi",
    "gorev_reddedildi":        "Gorev reddedildi",
    "gorev_revize_istendi":    "Gorev revize istendi",
    "gorev_iptal":             "Gorev iptal edildi",
}


# ============================================================
# ANA HELPER
# ============================================================
def create_task_notification(kullanici_id, rol, tip, mesaj, veri=None):
    """
    bildirim_log'a kayit ekle.

    Args:
        kullanici_id (int): Kime gidecek (NOT NULL)
        rol (str):          Kullanicinin rolu (NOT NULL)
        tip (str):          Bildirim tipi (NOTIFICATION_TYPES anahtari)
        mesaj (str):        Kisa mesaj metni (NOT NULL)
        veri (dict|None):   JSON serialize edilecek ek veri

    Returns:
        None (qexec son insert id donmez)

    Raises:
        ValueError: gecersiz tip veya bos zorunlu alan
    """
    # Validation
    if kullanici_id is None:
        raise ValueError("kullanici_id zorunlu")
    if not rol:
        raise ValueError("rol zorunlu")
    if not tip:
        raise ValueError("tip zorunlu")
    if not mesaj:
        raise ValueError("mesaj zorunlu")
    if tip not in NOTIFICATION_TYPES:
        raise ValueError(f"Bilinmeyen tip: {tip} (gecerli: {list(NOTIFICATION_TYPES.keys())})")

    # JSON serialize
    veri_str = None
    if veri is not None:
        try:
            veri_str = json.dumps(veri, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as e:
            raise ValueError(f"veri JSON serialize edilemedi: {e}")

    # Insert
    qexec("""
        INSERT INTO bildirim_log (
            kullanici_id, rol, tip, mesaj, veri_json
        ) VALUES (?, ?, ?, ?, ?)
    """, (int(kullanici_id), rol, tip, mesaj, veri_str))


# ============================================================
# KISAYOLLAR (service.py'da daha okunabilir kullanim icin)
# ============================================================
def notify_yeni_gorev(kullanici_id, rol, task_id, title, priority="orta"):
    """Yeni gorev atandi bildirimi."""
    create_task_notification(
        kullanici_id=kullanici_id,
        rol=rol,
        tip="gorev_yeni",
        mesaj=f"Yeni gorev: {title}",
        veri={
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "status": "bekliyor",
        }
    )


def notify_status_degisti(kullanici_id, rol, task_id, title, eski, yeni):
    """Status degisikligi bildirimi (genel)."""
    # Tip eslestirme
    tip_map = {
        "devam_ediyor":   "gorev_basladi",
        "tamamlandi":     "gorev_tamamlandi",
        "onay_bekliyor":  "gorev_onay_bekliyor",
        "revize_istendi": "gorev_revize_istendi",
        "iptal":          "gorev_iptal",
    }
    tip = tip_map.get(yeni)
    if not tip:
        return  # Bilinmeyen status icin bildirim gonderme

    create_task_notification(
        kullanici_id=kullanici_id,
        rol=rol,
        tip=tip,
        mesaj=f"Gorev durumu: {title} -> {yeni}",
        veri={
            "task_id": task_id,
            "title": title,
            "old_status": eski,
            "new_status": yeni,
        }
    )
