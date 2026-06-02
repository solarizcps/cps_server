# -*- coding: utf-8 -*-
"""CPS DEV - Belge Servisi

Upload guvenligi 3 katmanlidir:
  1) Uzanti kontrolu (ALLOWED_EXT)
  2) MIME type kontrolu (ALLOWED_MIME) - tarayicinin gonderdigi
  3) Boyut kontrolu (MAX_UPLOAD_MB)

Bu katman bilerek *reddetmez* ama uyusmazligi logs'a yazar. Asil denetim
uzanti seviyesinde yapilir - cunku MIME tarayiciya gore degisebilir
(ozellikle Excel 'application/octet-stream' olarak gelebilir).
"""
import os
import mimetypes
import logging
from datetime import datetime
from werkzeug.utils import secure_filename
from config import Config
from db import q, qone, qexec
from modules import audit

log = logging.getLogger("cps.belge")


BELGE_TIPLERI = [
    ('PROFORMA',           'Proforma Fatura'),
    ('COMMERCIAL_INVOICE', 'Commercial Invoice'),
    ('ANLASMA_EXCEL',      'Anlaşma Excel'),
    ('BEYANNAME',          'Gümrük Beyannamesi'),
    ('FATURA',             'Fatura'),
    ('TEKNIK_CIZIM',       'Teknik Çizim'),
    ('GORSEL',             'Görsel'),
    ('SERTIFIKA',          'Sertifika'),
    ('DIGER',              'Diğer'),
]


# =====================================================================
# VALIDATION
# =====================================================================
def _dosya_uzantisi(dosya_ad):
    """'rapor.xlsx' -> 'xlsx'. Yoksa ''. Kucuk harfle."""
    if not dosya_ad or '.' not in dosya_ad:
        return ''
    return dosya_ad.rsplit('.', 1)[-1].lower().strip()


def _ext_ok(dosya_ad):
    ext = _dosya_uzantisi(dosya_ad)
    return ext in Config.ALLOWED_EXT


def _mime_ok(mime_type):
    """MIME beyaz listesi. Bilinmiyorsa True doner (uzanti zaten kontrol edildi)."""
    if not mime_type:
        return True  # tarayici gondermediyse, uzantiyla yetin
    return mime_type in Config.ALLOWED_MIME


def _belge_tipi_uzanti_uyumlu(belge_tipi, dosya_ad):
    """
    Belge tipi ile dosya uzantisi mantikli mi?
    Orn: ANLASMA_EXCEL icin .pdf yanlis olur.
    Uyumsuzsa False, ama bu sert bir hata degil - cagiran uyari gosterebilir.
    """
    if not belge_tipi:
        return True
    ipucu = Config.BELGE_TIPI_UZANTI_IPUCU.get(belge_tipi)
    if ipucu is None:
        return True  # hepsi serbest
    ext = _dosya_uzantisi(dosya_ad)
    return ext in ipucu


# =====================================================================
# DISK YOL
# =====================================================================
def _disk_yol_olustur(modul, alt_modul, kayit_id, orijinal_ad):
    today = datetime.now()
    rel_klasor = os.path.join(modul, alt_modul or '',
                              f"{today.year}", f"{today.month:02d}")
    klasor = os.path.join(Config.UPLOAD_ROOT, rel_klasor)
    os.makedirs(klasor, exist_ok=True)
    guvenli = secure_filename(orijinal_ad) or f"dosya_{int(datetime.now().timestamp())}.bin"
    dosya_ad = f"{kayit_id:06d}_{guvenli}"
    tam = os.path.join(klasor, dosya_ad)
    if os.path.exists(tam):
        ts = int(datetime.now().timestamp())
        dosya_ad = f"{kayit_id:06d}_{ts}_{guvenli}"
        tam = os.path.join(klasor, dosya_ad)
    rel = os.path.join(rel_klasor, dosya_ad).replace('\\', '/')
    return tam, rel


# =====================================================================
# MIME INFERENCE
# =====================================================================
def _mime_tespit(dosya_storage, orijinal_ad):
    """
    MIME'i sira ile belirle:
      1) FileStorage.mimetype (tarayicinin verdigi)
      2) mimetypes.guess_type (uzantiya gore)
      3) application/octet-stream
    """
    m = None
    try:
        m = getattr(dosya_storage, 'mimetype', None) or getattr(dosya_storage, 'content_type', None)
    except Exception:
        m = None
    if not m or m == 'application/octet-stream':
        g, _ = mimetypes.guess_type(orijinal_ad)
        if g:
            m = g
    return m or 'application/octet-stream'


# =====================================================================
# UPLOAD
# =====================================================================
def belge_yukle(modul, alt_modul, kayit_id, dosya_storage,
                belge_tipi='DIGER', aciklama=None, kullanici='sistem'):
    """
    Dosyayi diske kaydeder ve sistem_belge tablosuna loglar.
    Hata durumunda ValueError firlatir (cagiran yakalar).
    Donus: belge_id
    """
    # ---- Temel kontroller ----
    if not dosya_storage or not dosya_storage.filename:
        raise ValueError('Dosya seçilmedi.')

    orijinal = dosya_storage.filename
    ext = _dosya_uzantisi(orijinal)

    if not ext:
        raise ValueError('Dosya uzantısı tespit edilemedi.')

    if not _ext_ok(orijinal):
        izinli = ', '.join(sorted(Config.ALLOWED_EXT))
        raise ValueError(
            f"'.{ext}' uzantısı desteklenmiyor. "
            f"İzinli: {izinli}"
        )

    # ---- Boyut kontrolu ----
    try:
        dosya_storage.stream.seek(0, 2)  # son
        boyut = dosya_storage.stream.tell()
        dosya_storage.stream.seek(0)     # basa don
    except Exception:
        boyut = 0

    if boyut <= 0:
        raise ValueError('Dosya boş veya okunamadı.')

    if boyut > Config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Dosya çok büyük (max {Config.MAX_UPLOAD_MB} MB)")

    # ---- MIME (sert degil, log icin) ----
    mime = _mime_tespit(dosya_storage, orijinal)
    if not _mime_ok(mime):
        log.warning(
            "Uyari: MIME beyaz listede yok. uzanti=%s mime=%s dosya=%s",
            ext, mime, orijinal,
        )
        # Uzanti ok ise devam et (tarayici yanilmis olabilir)

    # ---- Belge tipi uyumu (yumusak uyari) ----
    if not _belge_tipi_uzanti_uyumlu(belge_tipi, orijinal):
        log.info(
            "Bilgi: Belge tipi %s icin .%s uzantisi alisilmadik",
            belge_tipi, ext,
        )
        # Yine de izin ver - sistem katiyen reddetmeyecek, kullaniciyi sadece uyarir

    # ---- Disk kaydi ----
    tam_yol, rel_yol = _disk_yol_olustur(modul, alt_modul, kayit_id, orijinal)
    try:
        dosya_storage.save(tam_yol)
    except Exception as e:
        log.exception("Dosya diske yazilamadi: %s", e)
        raise ValueError('Dosya diske kaydedilemedi.')

    # ---- DB kaydi ----
    try:
        belge_id = qexec("""
            INSERT INTO sistem_belge
              (Modul, AltModul, KayitId, BelgeTipi, OrijinalAd, DiskYol,
               DosyaBoyut, MimeType, Yukleyen, YuklemeTarih, Aktif, Aciklama)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (modul, alt_modul, kayit_id, belge_tipi, orijinal, rel_yol,
              boyut, mime, kullanici,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S'), aciklama))
    except Exception as e:
        log.exception("Belge DB kaydi basarisiz: %s", e)
        # Disk'ten de kaldir
        try: os.remove(tam_yol)
        except Exception: pass
        raise ValueError('Veritabanı kaydı başarısız.')

    audit.log_ekle(
        kullanici, 'sistem_belge', belge_id,
        aciklama=f"Belge yüklendi: {orijinal} ({belge_tipi}) — "
                 f"{boyut // 1024} KB, {mime}",
        modul=modul, alt_modul=alt_modul,
    )
    return belge_id


# =====================================================================
# OKUMA
# =====================================================================
def belge_liste(modul, alt_modul, kayit_id, belge_tipi=None):
    params = [modul, alt_modul, kayit_id]
    ek = ""
    if belge_tipi:
        ek = "AND BelgeTipi = ?"
        params.append(belge_tipi)
    return q(f"""
        SELECT * FROM sistem_belge
        WHERE Modul = ? AND AltModul = ? AND KayitId = ?
          AND Aktif = 1 {ek}
        ORDER BY YuklemeTarih DESC, Id DESC
    """, tuple(params))


def belge_tek(belge_id):
    return qone("SELECT * FROM sistem_belge WHERE Id = ? AND Aktif = 1", (belge_id,))


def belge_tam_yol(belge_row):
    return os.path.join(Config.UPLOAD_ROOT, belge_row['DiskYol'])


def belge_sil(belge_id, kullanici='sistem', kalici=False):
    b = belge_tek(belge_id)
    if not b:
        return False
    qexec("UPDATE sistem_belge SET Aktif = 0 WHERE Id = ?", (belge_id,))
    if kalici:
        try:
            os.remove(belge_tam_yol(b))
        except Exception:
            pass
    audit.log_sil(
        kullanici, 'sistem_belge', belge_id,
        aciklama=f"Belge silindi: {b['OrijinalAd']}",
        modul=b['Modul'], alt_modul=b['AltModul'],
    )
    return True


def belge_tipi_adi(kod):
    for k, a in BELGE_TIPLERI:
        if k == kod:
            return a
    return kod
