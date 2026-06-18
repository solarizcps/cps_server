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


def get_profil_bugun_devam(pdks_personel_id, tarih=None, con=None):
    """Belirli bir PDKS personelinin belirtilen güne ait devam durumunu döner.

    PDKS DB'ye sadece SELECT yapılır. INSERT/UPDATE/DELETE yapılmaz.

    Args:
        pdks_personel_id : PDKS personel.id
        tarih            : 'YYYY-MM-DD' string (None ise bugün)
        con              : Mevcut bağlantı (None ise yeni açılır)

    Returns:
        dict: {
            "geldi": bool,
            "giris": "HH:MM" | None,
            "cikis": "HH:MM" | None,
            "durum": "geldi" | "gelmedi" | "gec" | "cikis_yok",
            "kayitlar": [...]
        }

    Durum mantığı:
        gelmedi   : Hiç kayıt yok
        geldi     : Giriş var, mesai saati içinde (06:00-08:30)
        gec       : Giriş var ama 08:30'dan sonra
        cikis_yok : Giriş var, çıkış kaydı yok
    """
    import datetime as _dt
    if tarih is None:
        tarih = _dt.date.today().strftime('%Y-%m-%d')

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
                  AND  giristarihi = %s
                ORDER  BY id ASC
                """,
                (pdks_personel_id, tarih)
            )
            rows = cur.fetchall()

        kayitlar = []
        for r in rows:
            kayitlar.append({
                'id'          : r['id'],
                'personelid'  : r['personelid'],
                'giristarihi' : _tarih_str(r.get('giristarihi')),
                'girissaati'  : _saat_str(r.get('girissaati')),
                'cikistarihi' : _tarih_str(r.get('cikistarihi')),
                'cikissaati'  : _saat_str(r.get('cikissaati')),
            })

        if not kayitlar:
            return {
                'geldi'    : False,
                'giris'    : None,
                'cikis'    : None,
                'durum'    : 'gelmedi',
                'kayitlar' : [],
            }

        # İlk giriş / son çıkış
        ilk_giris = kayitlar[0]['girissaati']
        son_cikis = kayitlar[-1]['cikissaati']

        # Durum hesapla
        if ilk_giris is None:
            durum = 'gelmedi'
            geldi = False
        elif son_cikis is None:
            durum = 'cikis_yok'
            geldi = True
        else:
            # 08:30 eşiği
            try:
                h, m = map(int, ilk_giris.split(':'))
                gec_sinir = 8 * 60 + 30
                durum = 'gec' if (h * 60 + m) > gec_sinir else 'geldi'
            except Exception:
                durum = 'geldi'
            geldi = True

        return {
            'geldi'    : geldi,
            'giris'    : ilk_giris,
            'cikis'    : son_cikis,
            'durum'    : durum,
            'kayitlar' : kayitlar,
        }
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
