# -*- coding: utf-8 -*-
"""CPS - Azper PDKS MySQL Connector (FAZ-1, Read-Only)

Bu modul sadece SELECT islemleri icin kullanilir.
INSERT / UPDATE / DELETE kesinlikle yapilmaz.

Baglanti bilgileri:
  Host     : 192.168.1.16
  Port     : 3306
  Database : sahintaban
  User     : root
  Charset  : latin5

Kullanim:
    from modules.common.pdks import get_connection, get_personel_liste

    con = get_connection()
    ...
    con.close()
"""

import pymysql
import pymysql.cursors
import datetime


# ── Baglanti ──────────────────────────────────────────────────────────────────

PDKS_HOST     = '192.168.1.16'
PDKS_PORT     = 3306
PDKS_DATABASE = 'sahintaban'
PDKS_USER     = 'root'
PDKS_PASSWORD = 'root'
PDKS_CHARSET  = 'latin5'
PDKS_TIMEOUT  = 8


def get_connection():
    """PDKS MySQL'e baglan, DictCursor doner.

    DIKKAT: Sadece SELECT. Baglantıyı is bittikten sonra kapat.
    """
    return pymysql.connect(
        host            = PDKS_HOST,
        port            = PDKS_PORT,
        database        = PDKS_DATABASE,
        user            = PDKS_USER,
        password        = PDKS_PASSWORD,
        charset         = PDKS_CHARSET,
        connect_timeout = PDKS_TIMEOUT,
        cursorclass     = pymysql.cursors.DictCursor,
    )


# ── Yardımcı: saat normalleştir ───────────────────────────────────────────────

def _saat_str(val):
    """timedelta veya str olan saat degerini HH:MM formatına cevirir."""
    if val is None:
        return None
    if isinstance(val, datetime.timedelta):
        total = int(val.total_seconds())
        h, rem = divmod(total, 3600)
        m = rem // 60
        return f'{h:02d}:{m:02d}'
    return str(val)


def _tarih_str(val):
    """date/datetime'i YYYY-MM-DD string'e cevirir."""
    if val is None:
        return None
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.strftime('%Y-%m-%d')
    return str(val)


# ── Sorgu fonksiyonları ────────────────────────────────────────────────────────

def get_personel_liste(con=None, limit=500):
    """personel tablosundan aktif personel listesini doner.

    Args:
        con   : Mevcut baglanti (None ise yeni acilir).
        limit : Max kayit sayisi.

    Returns:
        list[dict]: [{id, sicilno, ad, soyad}, ...]
    """
    kapat = con is None
    if con is None:
        con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, sicilno, ad, soyad FROM personel LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
        return list(rows)
    finally:
        if kapat:
            con.close()


# Alias — FAZ-1 talep edilen isimler
get_pdks_personeller = get_personel_liste


def get_son_giris_cikis(con=None, limit=20):
    """pts_giriscikis tablosundan son hareketleri doner.

    Saat alanlari (girissaati, cikissaati) HH:MM formatına cevirilir.
    Tarih alanlari YYYY-MM-DD string formatına cevirilir.

    Args:
        con   : Mevcut baglanti (None ise yeni acilir).
        limit : Max kayit sayisi.

    Returns:
        list[dict]: [{id, personelid, giristarihi, girissaati, cikistarihi, cikissaati}, ...]
    """
    kapat = con is None
    if con is None:
        con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, personelid,
                       giristarihi,  girissaati,
                       cikistarihi,  cikissaati
                FROM   pts_giriscikis
                ORDER  BY id DESC
                LIMIT  %s
                """,
                (limit,)
            )
            rows = cur.fetchall()

        # timedelta / date nesnelerini JSON-safe stringe cevir
        result = []
        for r in rows:
            result.append({
                'id'          : r['id'],
                'personelid'  : r['personelid'],
                'giristarihi' : _tarih_str(r.get('giristarihi')),
                'girissaati'  : _saat_str(r.get('girissaati')),
                'cikistarihi' : _tarih_str(r.get('cikistarihi')),
                'cikissaati'  : _saat_str(r.get('cikissaati')),
            })
        return result
    finally:
        if kapat:
            con.close()


def get_pdks_giris_cikis(personelid, con=None, limit=30):
    """Belirli bir personelin son giris/cikis hareketlerini doner.

    Args:
        personelid : PDKS personel id (pts_giriscikis.personelid)
        con        : Mevcut baglanti (None ise yeni acilir).
        limit      : Max kayit sayisi.

    Returns:
        list[dict]: [{id, personelid, giristarihi, girissaati, cikistarihi, cikissaati}, ...]
    """
    kapat = con is None
    if con is None:
        con = get_connection()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, personelid,
                       giristarihi,  girissaati,
                       cikistarihi,  cikissaati
                FROM   pts_giriscikis
                WHERE  personelid = %s
                ORDER  BY id DESC
                LIMIT  %s
                """,
                (personelid, limit)
            )
            rows = cur.fetchall()

        result = []
        for r in rows:
            result.append({
                'id'          : r['id'],
                'personelid'  : r['personelid'],
                'giristarihi' : _tarih_str(r.get('giristarihi')),
                'girissaati'  : _saat_str(r.get('girissaati')),
                'cikistarihi' : _tarih_str(r.get('cikistarihi')),
                'cikissaati'  : _saat_str(r.get('cikissaati')),
            })
        return result
    finally:
        if kapat:
            con.close()
