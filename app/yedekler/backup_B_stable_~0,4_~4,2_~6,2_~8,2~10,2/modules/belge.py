# -*- coding: utf-8 -*-
"""CPS DEV - Belge Servisi (service functions, no blueprint)"""
import os
import mimetypes
from datetime import datetime
from werkzeug.utils import secure_filename
from config import Config
from db import q, qone, qexec
from modules import audit


BELGE_TIPLERI = [
    ('PROFORMA',     'Proforma Fatura'),
    ('TEKNIK_CIZIM', 'Teknik Çizim'),
    ('GORSEL',       'Görsel'),
    ('BEYANNAME',    'Gümrük Beyannamesi'),
    ('FATURA',       'Fatura'),
    ('SERTIFIKA',    'Sertifika'),
    ('DIGER',        'Diğer'),
]


def _ext_ok(ad):
    if '.' not in ad:
        return False
    return ad.rsplit('.', 1)[-1].lower() in Config.ALLOWED_EXT


def _disk_yol_olustur(modul, alt_modul, kayit_id, orijinal_ad):
    today = datetime.now()
    rel_klasor = os.path.join(modul, alt_modul or '', f"{today.year}", f"{today.month:02d}")
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


def belge_yukle(modul, alt_modul, kayit_id, dosya_storage, belge_tipi='DIGER',
                aciklama=None, kullanici='sistem'):
    if not dosya_storage or not dosya_storage.filename:
        raise ValueError('Dosya seçilmedi.')
    if not _ext_ok(dosya_storage.filename):
        raise ValueError(f"İzin verilmeyen dosya türü. İzinli: {', '.join(Config.ALLOWED_EXT)}")

    dosya_storage.stream.seek(0, 2)
    boyut = dosya_storage.stream.tell()
    dosya_storage.stream.seek(0)
    if boyut > Config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Dosya çok büyük (max {Config.MAX_UPLOAD_MB}MB)")

    orijinal = dosya_storage.filename
    tam_yol, rel_yol = _disk_yol_olustur(modul, alt_modul, kayit_id, orijinal)
    dosya_storage.save(tam_yol)
    mime, _ = mimetypes.guess_type(orijinal)
    mime = mime or 'application/octet-stream'

    belge_id = qexec("""
        INSERT INTO sistem_belge
          (Modul, AltModul, KayitId, BelgeTipi, OrijinalAd, DiskYol,
           DosyaBoyut, MimeType, Yukleyen, YuklemeTarih, Aktif, Aciklama)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (modul, alt_modul, kayit_id, belge_tipi, orijinal, rel_yol,
          boyut, mime, kullanici,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'), aciklama))

    audit.log_ekle(kullanici, 'sistem_belge', belge_id,
                   aciklama=f"Belge yüklendi: {orijinal} ({belge_tipi}) — {boyut//1024} KB",
                   modul=modul, alt_modul=alt_modul)
    return belge_id


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
    audit.log_sil(kullanici, 'sistem_belge', belge_id,
                  aciklama=f"Belge silindi: {b['OrijinalAd']}",
                  modul=b['Modul'], alt_modul=b['AltModul'])
    return True


def belge_tipi_adi(kod):
    for k, a in BELGE_TIPLERI:
        if k == kod:
            return a
    return kod
