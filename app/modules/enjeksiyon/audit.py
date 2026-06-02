# -*- coding: utf-8 -*-
"""F9.0.5 — Generic Event Log Motor

KRITIK MIMARI KURALI:
========================
enj_event_log = OLAY KAYDI (audit/tarihce)
enj_gunluk_rapor = SNAPSHOT (sistem mevcut durumu)
enj_istasyon_durumu = CANLI VERI (gercek)

enj_event_log ASLA SOURCE OF TRUTH degildir.
Sadece "ne oldu?" sorusunun cevabini verir.
Hesap motoru (F9.5) buradan veri OKUMAZ.
========================
"""

import json
from .constants import EVENT_GROUP, EVENT_TYPE_MAP, SPAM_WINDOWS, EVENT_VERSION


def log_event(con, rapor_id, event_group, event_type,
              onceki_deger, yeni_deger,
              meta_extra=None,
              istasyon_id=None,
              saatlik_kayit_id=None,
              system_generated=False,
              zaman_kayit=None):
    """Generic event motoru — TEK GIRIS NOKTASI."""

    if event_group not in EVENT_GROUP:
        raise ValueError(f"Gecersiz event_group: {event_group}")
    if event_type not in EVENT_TYPE_MAP.get(event_group, []):
        raise ValueError(f"Gecersiz event_type '{event_type}' for group '{event_group}'")

    cur = con.cursor()

    spam_window = SPAM_WINDOWS.get((event_group, event_type), 0)
    if spam_window > 0:
        cur.execute("""
            SELECT id FROM enj_event_log
            WHERE rapor_id = ?
              AND event_type = ?
              AND yeni_deger = ?
              AND zaman > datetime('now', '-' || ? || ' seconds')
            LIMIT 1
        """, (rapor_id, event_type,
              str(yeni_deger) if yeni_deger is not None else None,
              spam_window))
        if cur.fetchone():
            return

    cur.execute("""
        SELECT tarih, makine_id, vardiya, kullanici_id, kullanici_adi,
               bagli_kalip_adet, kalip_basi_cift, kalip_id, kalip_no,
               renk, emir_no
        FROM enj_gunluk_rapor WHERE id = ?
    """, (rapor_id,))
    r = cur.fetchone()
    if not r:
        return

    cur.execute("""
        SELECT istasyon_no, slot, aktif
        FROM enj_istasyon_durumu
        WHERE rapor_id = ?
        ORDER BY istasyon_no, slot
    """, (rapor_id,))

    slot_snapshot = {}
    aktif_a = 0
    aktif_b = 0
    for row in cur.fetchall():
        key = f"{row[0]}{row[1]}"
        slot_snapshot[key] = row[2] or 0
        if row[2]:
            if row[1] == 'A':
                aktif_a += 1
            elif row[1] == 'B':
                aktif_b += 1
    aktif_toplam = aktif_a + aktif_b

    hesap_snapshot = {
        "kbc": r[6],
        "aktif_slot": aktif_toplam,
        "teorik_cift_tur": None,
        "slot_kapasite_toplam": None
    }

    rapor_snapshot = {
        "emir_no": r[10],
        "kalip_id": r[7],
        "kalip_kod": r[8],
        "renk": r[9],
        "kbc": r[6]
    }

    meta = {
        "onceki_bagli": onceki_deger,
        "yeni_bagli": yeni_deger,
        "slot_snapshot": slot_snapshot,
        "aktif_a_sayisi": aktif_a,
        "aktif_b_sayisi": aktif_b,
        "aktif_toplam": aktif_toplam,
        "hesap_snapshot": hesap_snapshot,
        "rapor_snapshot": rapor_snapshot,
        "system_generated": system_generated
    }
    if meta_extra:
        meta["tetik_detay"] = meta_extra

    # F9.2: Zaman kaydi (her durum gecisinde onceki durum suresi)
    if zaman_kayit:
        meta["_zaman_kayit"] = zaman_kayit

    cur.execute("""
        INSERT INTO enj_event_log
        (rapor_id, saatlik_kayit_id, istasyon_id,
         tarih, makine_id, vardiya,
         kullanici_id, kullanici_adi,
         event_group, event_type, event_version,
         onceki_deger, yeni_deger,
         meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rapor_id, saatlik_kayit_id, istasyon_id,
        r[0], r[1], r[2],
        r[3], r[4],
        event_group, event_type, EVENT_VERSION,
        str(onceki_deger) if onceki_deger is not None else None,
        str(yeni_deger) if yeni_deger is not None else None,
        json.dumps(meta, ensure_ascii=False)
    ))


# =========================================================
# F9.2 HELPER FONKSIYONLAR
# =========================================================
# 5 helper, hepsi log_event() uzerinden gider.
# Endpoint'ler (Patch 2'de eklenecek) bu helper'lari cagiracak.

def log_setup_start(con, rapor_id, istasyon_id,
                    yeni_kalip_id, sebep,
                    kullanici_id=None, meta_extra=None):
    """SETUP basladi. Yeni kalip planlandi.

    Args:
        rapor_id: enj_gunluk_rapor.id
        istasyon_id: enj_istasyon_durumu.id
        yeni_kalip_id: setup sonrasi planlanan kalip (NULL gecerli)
        sebep: SETUP_SEBEPLER ENUM (PLANLI_DEGISIM/ARIZA_SONRASI/ACIL)
    """
    extra = {"yeni_kalip_id": yeni_kalip_id, "setup_sebep": sebep}
    if meta_extra:
        extra.update(meta_extra)
    return log_event(
        con, rapor_id, "SETUP", "SETUP_START",
        onceki_deger=None, yeni_deger=None,
        meta_extra=extra,
        istasyon_id=istasyon_id
    )


def log_setup_end(con, rapor_id, istasyon_id,
                  success, sure_dakika=None, sebep_iptal=None,
                  kullanici_id=None, meta_extra=None):
    """SETUP bitti.

    KRITIK: success bool degeri kritiktir.
    success=True  -> yeni kalip sahiplenildi
    success=False -> setup iptal, kalip_id eski hali korur
    """
    extra = {"success": bool(success)}
    if sure_dakika is not None:
        extra["sure_dakika"] = sure_dakika
    if sebep_iptal:
        extra["sebep_iptal"] = sebep_iptal
    if meta_extra:
        extra.update(meta_extra)
    return log_event(
        con, rapor_id, "SETUP", "SETUP_END",
        onceki_deger=None, yeni_deger=None,
        meta_extra=extra,
        istasyon_id=istasyon_id
    )


def log_ariza_start(con, rapor_id, istasyon_id,
                    sebep, sebep_detay=None,
                    kullanici_id=None, meta_extra=None):
    """ARIZA basladi.

    Args:
        sebep: ARIZA_SEBEPLER ENUM
        sebep_detay: opsiyonel serbest text
    """
    extra = {"ariza_sebep": sebep}
    if sebep_detay:
        extra["ariza_sebep_detay"] = sebep_detay
    if meta_extra:
        extra.update(meta_extra)
    return log_event(
        con, rapor_id, "ARIZA", "ARIZA_START",
        onceki_deger=None, yeni_deger=None,
        meta_extra=extra,
        istasyon_id=istasyon_id
    )


def log_ariza_end(con, rapor_id, istasyon_id,
                  yeni_durum="AKTIF", sure_dakika=None,
                  kullanici_id=None, meta_extra=None):
    """ARIZA bitti."""
    extra = {"yeni_durum": yeni_durum}
    if sure_dakika is not None:
        extra["sure_dakika"] = sure_dakika
    if meta_extra:
        extra.update(meta_extra)
    return log_event(
        con, rapor_id, "ARIZA", "ARIZA_END",
        onceki_deger=None, yeni_deger=None,
        meta_extra=extra,
        istasyon_id=istasyon_id
    )


def log_slot_mismatch_warning(con, rapor_id, istasyon_no,
                              a_kalip_id, b_kalip_id,
                              kullanici_id=None, meta_extra=None):
    """A/B slot farkli kalip uyarisi. Hard block degil."""
    extra = {
        "istasyon_no": istasyon_no,
        "a_kalip_id": a_kalip_id,
        "b_kalip_id": b_kalip_id
    }
    if meta_extra:
        extra.update(meta_extra)
    return log_event(
        con, rapor_id, "VALIDATION", "SLOT_MISMATCH_WARNING",
        onceki_deger=None, yeni_deger=None,
        meta_extra=extra
    )

