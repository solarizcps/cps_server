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


# ── FAZ-5B: Aylık/Yıllık Devam Geçmişi ───────────────────────────────────────

# TODO: Geç kalma eşiği ileriki fazda vardiya/çalışma parametresine bağlanacak.
_GEC_KALMA_ESIGI_SAAT = 7
_GEC_KALMA_ESIGI_DK   = 0


def _timedelta_to_saat_str(td):
    """timedelta → 'HH:MM', None → None."""
    if td is None:
        return None
    if isinstance(td, __import__("datetime").timedelta):
        toplam_sn = int(td.total_seconds())
        return f'{toplam_sn // 3600:02d}:{(toplam_sn % 3600) // 60:02d}'
    return str(td)[:5] if td else None


def _gun_durum(giris_td, cikis_td, izin_tipi):
    """Gün durumunu hesapla. Dönüş: (durum_str, gec_mi)"""
    import datetime as _dt
    if izin_tipi and str(izin_tipi).strip():
        return 'izin', False
    if giris_td is None:
        return 'gelmedi', False
    giris_sn = int(giris_td.total_seconds()) if isinstance(giris_td, _dt.timedelta) else 0
    giris_s  = giris_sn // 3600
    giris_dk = (giris_sn % 3600) // 60
    gec_mi   = (giris_s > _GEC_KALMA_ESIGI_SAAT) or \
               (giris_s == _GEC_KALMA_ESIGI_SAAT and giris_dk > _GEC_KALMA_ESIGI_DK)
    if cikis_td is None:
        return 'cikis_yok', gec_mi
    return ('gec' if gec_mi else 'geldi'), gec_mi


def get_profil_devam_gecmisi(pdks_personel_id, ay=None, yil=None, con=None):
    """PDKS'ten aylık gün-gün devam geçmişi + aylık/yıllık özet döner.

    Parametreler:
        pdks_personel_id : int  — PDKS personel.id
        ay               : str  — 'YYYY-MM' formatı (None → bugünün ayı)
        yil              : int  — özet yılı (None → ay'ın yılı)
        con              : mevcut bağlantı (None → yeni açılır, kapatılır)

    PDKS DB'ye yazma yapılmaz — sadece SELECT.
    """
    import datetime as _dt
    kapat = con is None
    if con is None:
        con = get_connection()
    try:
        bugun     = _dt.date.today()
        hedef_ay  = ay if ay else bugun.strftime('%Y-%m')
        try:
            ay_yil = int(hedef_ay.split('-')[0])
            ay_ay  = int(hedef_ay.split('-')[1])
        except Exception:
            ay_yil = bugun.year
            ay_ay  = bugun.month
        hedef_yil = int(yil) if yil else ay_yil

        ay_bas = _dt.date(ay_yil, ay_ay, 1)
        if ay_ay == 12:
            ay_bit = _dt.date(ay_yil + 1, 1, 1) - _dt.timedelta(days=1)
        else:
            ay_bit = _dt.date(ay_yil, ay_ay + 1, 1) - _dt.timedelta(days=1)
        yil_bas = _dt.date(hedef_yil, 1, 1)
        yil_bit = _dt.date(hedef_yil, 12, 31)

        with con.cursor() as cur:
            cur.execute("""
                SELECT giristarihi, girissaati, cikistarihi, cikissaati,
                       izintipi, aciklama
                FROM pts_giriscikis
                WHERE personelid=%s AND giristarihi BETWEEN %s AND %s
                ORDER BY giristarihi ASC
            """, (pdks_personel_id, ay_bas, ay_bit))
            gc_rows = cur.fetchall()

            cur.execute("""
                SELECT giristarihi, cikistarihi, izintipi, izinsure, aciklama
                FROM pts_izin
                WHERE personelid=%s AND giristarihi BETWEEN %s AND %s
                ORDER BY giristarihi ASC
            """, (pdks_personel_id, ay_bas, ay_bit))
            izin_rows = cur.fetchall()

            cur.execute("""
                SELECT tarih, saat, isaat, aciklama
                FROM pts_mesai
                WHERE personelid=%s AND tarih BETWEEN %s AND %s
                ORDER BY tarih ASC
            """, (pdks_personel_id, ay_bas, ay_bit))
            mesai_rows = cur.fetchall()

            cur.execute("""
                SELECT girissaati, cikissaati, izintipi
                FROM pts_giriscikis
                WHERE personelid=%s AND giristarihi BETWEEN %s AND %s
            """, (pdks_personel_id, yil_bas, yil_bit))
            yil_gc_rows = cur.fetchall()

        gunler = []
        for r in gc_rows:
            durum, gec_mi = _gun_durum(r.get('girissaati'), r.get('cikissaati'), r.get('izintipi'))
            gunler.append({
                'tarih'    : str(r.get('giristarihi')),
                'giris'    : _timedelta_to_saat_str(r.get('girissaati')),
                'cikis'    : _timedelta_to_saat_str(r.get('cikissaati')),
                'durum'    : durum,
                'gec_mi'   : gec_mi,
                'izin_tipi': r.get('izintipi'),
                'not'      : r.get('aciklama') or None,
            })

        def _ozet(glist):
            o = {'calistigi_gun': 0, 'gec_kalma_gun': 0, 'gelmedi_gun': 0,
                 'izin_gun': 0, 'cikis_yok_gun': 0, 'toplam_kayit': len(glist)}
            for g in glist:
                d = g['durum']
                if d in ('geldi', 'gec', 'cikis_yok'):
                    o['calistigi_gun'] += 1
                if g['gec_mi']:
                    o['gec_kalma_gun'] += 1
                if d == 'gelmedi':
                    o['gelmedi_gun'] += 1
                if d == 'izin':
                    o['izin_gun'] += 1
                if d == 'cikis_yok':
                    o['cikis_yok_gun'] += 1
            return o

        ozet = _ozet(gunler)

        yil_gunler = []
        for r in yil_gc_rows:
            durum, gec_mi = _gun_durum(r.get('girissaati'), r.get('cikissaati'), r.get('izintipi'))
            yil_gunler.append({'durum': durum, 'gec_mi': gec_mi})

        yil_ozet = {
            'calistigi_gun': sum(1 for g in yil_gunler if g['durum'] in ('geldi','gec','cikis_yok')),
            'gec_kalma_gun': sum(1 for g in yil_gunler if g['gec_mi']),
            'gelmedi_gun'  : sum(1 for g in yil_gunler if g['durum'] == 'gelmedi'),
            'izin_gun'     : sum(1 for g in yil_gunler if g['durum'] == 'izin'),
            'cikis_yok_gun': sum(1 for g in yil_gunler if g['durum'] == 'cikis_yok'),
        }

        izinler = [{
            'tarih'    : str(r.get('giristarihi')),
            'bitis'    : str(r.get('cikistarihi')),
            'izin_tipi': r.get('izintipi'),
            'sure'     : r.get('izinsure'),
            'not'      : r.get('aciklama') or None,
        } for r in izin_rows]

        mesailer = [{
            'tarih': str(r.get('tarih')),
            'saat' : _timedelta_to_saat_str(r.get('saat')),
            'sure' : r.get('isaat'),
            'not'  : r.get('aciklama') or None,
        } for r in mesai_rows]

        return {
            'ay'      : hedef_ay,
            'yil'     : hedef_yil,
            'gunler'  : gunler,
            'ozet'    : ozet,
            'yil_ozet': yil_ozet,
            'izinler' : izinler,
            'mesailer': mesailer,
        }

    finally:
        if kapat:
            con.close()
