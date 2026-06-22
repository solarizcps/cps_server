# -*- coding: utf-8 -*-
"""
SOLARIZ CPS — NexGen Hammadde Yönetimi
=======================================
FAZ-1A : Modül iskeleti, menü, yetki
FAZ-1B : Stok Kart Master + Hareket Motoru altyapısı
FAZ-2  : Satın Alma Merkezi — Tedarikçi CRUD + Sipariş akışı
FAZ-2.6: Haftalık Fiyat Geçmişi — Excel import, preview/onay akışı

Yetki kodları:
  nexgen.view                — modül geneli görüntüleme
  nexgen.stok.view           — stok kartları görüntüleme
  nexgen.stok.manage         — stok kartı ekleme/düzenleme
  nexgen.satinalma.view      — satın alma sipariş görüntüleme
  nexgen.satinalma.manage    — yeni sipariş oluşturma/düzenleme
  nexgen.satinalma.approve   — sipariş onaylama (sadece Yönetim)
  nexgen.satinalma.fiyat     — fiyat/kur/maliyet görüntüleme
  nexgen.tedarikci.view      — tedarikçi listesi görüntüleme
  nexgen.tedarikci.manage    — tedarikçi ekleme/düzenleme
  nexgen.fiyat.view          — fiyat geçmişini görüntüleme
  nexgen.fiyat.manage        — fiyat girişi (manuel + Excel)
  nexgen.fiyat.approve       — batch onaylama
  nexgen.fiyat.admin         — fiyat pasife alma (sadece Yönetim)

KURAL: Bu modül nexgen_stok_hareket tablosuna HİÇBİR ZAMAN INSERT yapmaz.
"""

import sqlite3
import os
import io
from datetime import datetime, date

from flask import (
    Blueprint, render_template, abort,
    request, jsonify, session, g,
    Response, redirect, url_for, flash
)
from modules.auth import yetki_gerekli, yetki_var

nexgen_bp = Blueprint('nexgen', __name__, url_prefix='/nexgen')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'mock_data.db')


# ─────────────────────────────────────────────────────────────
# Yardımcı: DB bağlantısı
# ─────────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _kullanici_id():
    u = session.get('kullanici')
    return u.get('Id') if u else None


def _kullanici_ad():
    u = session.get('kullanici')
    return u.get('KullaniciAdi', 'sistem') if u else 'sistem'


# ─────────────────────────────────────────────────────────────
# Stok miktarı hesapla (hareket toplamı)
# ─────────────────────────────────────────────────────────────
def _mevcut_stok(con, kart_id):
    row = con.execute(
        "SELECT COALESCE(SUM(miktar_kg), 0) AS toplam "
        "FROM nexgen_stok_hareket WHERE stok_kart_id=?",
        (kart_id,)
    ).fetchone()
    return round(row["toplam"], 3) if row else 0.0


# ─────────────────────────────────────────────────────────────
# Ana Sayfa
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/')
@yetki_gerekli('nexgen.view', 'can_view')
def index():
    return render_template('nexgen/index.html', active='nexgen')


# ─────────────────────────────────────────────────────────────
# Stok Kartları — Liste
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/stok-kartlari')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def stok_kartlari():
    con = _db()
    try:
        kartlar_raw = con.execute("""
            SELECT k.id, k.kod, k.ad, k.kategori, k.birim,
                   k.minimum_stok, k.kritik_stok, k.aktif,
                   COALESCE(SUM(h.miktar_kg), 0) AS mevcut_stok
            FROM nexgen_stok_kart k
            LEFT JOIN nexgen_stok_hareket h ON h.stok_kart_id = k.id
            GROUP BY k.id
            ORDER BY k.kategori, k.ad
        """).fetchall()
    finally:
        con.close()

    kartlar = []
    for r in kartlar_raw:
        ms = r["mevcut_stok"]
        mn = r["minimum_stok"]
        kr = r["kritik_stok"]
        if ms <= kr:
            durum = "kritik"
        elif ms <= mn:
            durum = "uyari"
        else:
            durum = "normal"
        kartlar.append({
            "id": r["id"], "kod": r["kod"], "ad": r["ad"],
            "kategori": r["kategori"], "birim": r["birim"],
            "minimum_stok": mn, "kritik_stok": kr,
            "mevcut_stok": ms, "durum": durum,
            "aktif": r["aktif"],
        })

    can_manage = yetki_var('nexgen.stok.manage', 'can_manage') or yetki_var('nexgen.stok.manage', 'can_create')
    return render_template(
        'nexgen/stok_kartlari.html',
        active='nexgen',
        kartlar=kartlar,
        can_manage=can_manage,
    )


# ─────────────────────────────────────────────────────────────
# Stok Kart Detay
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/stok-kartlari/<int:kart_id>')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def stok_detay(kart_id):
    con = _db()
    try:
        kart = con.execute(
            "SELECT * FROM nexgen_stok_kart WHERE id=?", (kart_id,)
        ).fetchone()
        if not kart:
            abort(404)

        mevcut = _mevcut_stok(con, kart_id)

        hareketler_raw = con.execute("""
            SELECT h.id, h.hareket_tipi, h.miktar_kg,
                   h.onceki_stok, h.sonraki_stok,
                   h.aciklama, h.referans_tip, h.referans_id,
                   h.olusturma_tarihi,
                   sk.KullaniciAdi AS olusturan_ad
            FROM nexgen_stok_hareket h
            LEFT JOIN sistem_kullanici sk ON sk.Id = h.olusturan_id
            WHERE h.stok_kart_id = ?
            ORDER BY h.id DESC
            LIMIT 50
        """, (kart_id,)).fetchall()

    finally:
        con.close()

    ms = mevcut
    mn = kart["minimum_stok"]
    kr = kart["kritik_stok"]
    if ms <= kr:
        durum = "kritik"
    elif ms <= mn:
        durum = "uyari"
    else:
        durum = "normal"

    hareketler = [dict(h) for h in hareketler_raw]
    can_manage = yetki_var('nexgen.stok.manage', 'can_manage') or yetki_var('nexgen.stok.manage', 'can_create')

    return render_template(
        'nexgen/stok_detay.html',
        active='nexgen',
        kart=dict(kart),
        mevcut_stok=ms,
        durum=durum,
        hareketler=hareketler,
        can_manage=can_manage,
    )


# ─────────────────────────────────────────────────────────────
# API — Hızlı Panel Özet (FAZ-1D)
# GET /nexgen/api/stok-kart/<id>/ozet
# Yetki: nexgen.stok.view can_view
# Fiyat/maliyet bilgisi dönmez.
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart/<int:kart_id>/ozet')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def api_stok_kart_ozet(kart_id):
    con = _db()
    try:
        # SELECT * — Migration 048 çalıştırılmamış olsa bile çalışır
        kart_row = con.execute(
            "SELECT * FROM nexgen_stok_kart WHERE id=?",
            (kart_id,)
        ).fetchone()
        if not kart_row:
            return jsonify({"ok": False, "hata": "Kart bulunamadı."}), 404

        kart = dict(kart_row)
        ms = _mevcut_stok(con, kart_id)

        hareketler_raw = con.execute("""
            SELECT h.hareket_tipi, h.miktar_kg, h.sonraki_stok,
                   h.aciklama, h.olusturma_tarihi,
                   sk.KullaniciAdi AS yapan
            FROM nexgen_stok_hareket h
            LEFT JOIN sistem_kullanici sk ON sk.Id = h.olusturan_id
            WHERE h.stok_kart_id = ?
            ORDER BY h.id DESC LIMIT 5
        """, (kart_id,)).fetchall()

    except Exception as e:
        return jsonify({"ok": False, "hata": f"Veritabanı hatası: {str(e)}"}), 500
    finally:
        con.close()

    mn = kart.get("minimum_stok", 0) or 0
    kr = kart.get("kritik_stok", 0) or 0
    if ms <= kr:
        durum = "kritik"
    elif ms <= mn:
        durum = "uyari"
    else:
        durum = "normal"

    hareketler = []
    for h in hareketler_raw:
        hareketler.append({
            "tip":      h["hareket_tipi"],
            "miktar":   h["miktar_kg"],
            "stok":     h["sonraki_stok"],
            "aciklama": h["aciklama"] or "",
            "tarih":    (h["olusturma_tarihi"] or "")[:16],
            "yapan":    h["yapan"] or "—",
        })

    return jsonify({
        "ok": True,
        "kart": {
            "id":            kart.get("id"),
            "kod":           kart.get("kod", ""),
            "ad":            kart.get("ad", ""),
            "kategori":      kart.get("kategori", ""),
            "birim":         kart.get("birim", "KG"),
            "minimum_stok":  mn,
            "kritik_stok":   kr,
            "aktif":         kart.get("aktif", 1),
            # FAZ-1C opsiyonel alanlar — Migration 048 yoksa None
            "renk":          kart.get("renk"),
            "alt_kategori":  kart.get("alt_kategori"),
            "kalite_sinifi": kart.get("kalite_sinifi"),
            "shore_degeri":  kart.get("shore_degeri"),
            "notlar":        kart.get("notlar"),
        },
        "mevcut_stok": ms,
        "durum":       durum,
        "hareketler":  hareketler,
    })


# ─────────────────────────────────────────────────────────────
# API — Yeni Stok Kartı Ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart-ekle', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_create')
def api_stok_kart_ekle():
    data = request.get_json(silent=True) or {}
    kod      = (data.get('kod') or '').strip().upper()
    ad       = (data.get('ad') or '').strip()
    kategori = (data.get('kategori') or 'HAMMADDE').strip().upper()
    birim    = (data.get('birim') or 'KG').strip().upper()
    # FAZ-1C opsiyonel alanlar — boşsa None kaydedilir
    renk          = (data.get('renk') or '').strip() or None
    alt_kategori  = (data.get('alt_kategori') or '').strip() or None
    kalite_sinifi = (data.get('kalite_sinifi') or '').strip() or None
    shore_degeri  = (data.get('shore_degeri') or '').strip() or None
    notlar        = (data.get('notlar') or '').strip() or None

    try:
        min_stok  = float(data.get('minimum_stok') or 0)
        krit_stok = float(data.get('kritik_stok') or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz sayısal değer."}), 400

    GECERLI_KATEGORILER = {
        'HAMMADDE', 'MAMUL_COMPOUND', 'RECYCLE', 'KATKI', 'BOYA', 'DIGER'
    }

    if not kod:
        return jsonify({"ok": False, "hata": "Kod zorunludur."}), 400
    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400
    if kategori not in GECERLI_KATEGORILER:
        return jsonify({"ok": False, "hata": f"Geçersiz kategori: {kategori}"}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)
        ).fetchone()
        if mevcut:
            return jsonify({"ok": False, "hata": f"'{kod}' kodu zaten mevcut."}), 409

        con.execute("""
            INSERT INTO nexgen_stok_kart
              (kod, ad, kategori, birim, minimum_stok, kritik_stok,
               renk, alt_kategori, kalite_sinifi, shore_degeri, notlar,
               aktif, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
        """, (kod, ad, kategori, birim, min_stok, krit_stok,
              renk, alt_kategori, kalite_sinifi, shore_degeri, notlar,
              _kullanici_id()))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "kod": kod, "ad": ad})


# ─────────────────────────────────────────────────────────────
# API — Stok Hareketi Ekle (manuel giriş/çıkış/sayım)
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-hareket-ekle', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_create')
def api_stok_hareket_ekle():
    data = request.get_json(silent=True) or {}
    kart_id       = data.get('stok_kart_id')
    hareket_tipi  = (data.get('hareket_tipi') or '').strip().upper()
    aciklama      = (data.get('aciklama') or '').strip()
    try:
        miktar = float(data.get('miktar_kg') or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz miktar."}), 400

    GECERLI_TIPLER = {
        'GIRIS', 'CIKIS', 'URETIM_TUKETIM', 'URETIM_CIKTI',
        'SAYIM_DUZELTME', 'SEVK'
    }
    CIKIS_TIPLERI = {'CIKIS', 'URETIM_TUKETIM', 'SEVK'}

    if not kart_id:
        return jsonify({"ok": False, "hata": "stok_kart_id zorunludur."}), 400
    if hareket_tipi not in GECERLI_TIPLER:
        return jsonify({"ok": False, "hata": f"Geçersiz hareket tipi: {hareket_tipi}"}), 400
    if miktar <= 0:
        return jsonify({"ok": False, "hata": "Miktar sıfırdan büyük olmalıdır."}), 400

    # Çıkış hareketlerinde miktarı negatife çevir
    if hareket_tipi in CIKIS_TIPLERI:
        miktar_kayit = -abs(miktar)
    else:
        miktar_kayit = abs(miktar)

    con = _db()
    try:
        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=? AND aktif=1", (kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı veya pasif."}), 404

        onceki = _mevcut_stok(con, kart_id)
        sonraki = round(onceki + miktar_kayit, 3)

        con.execute("""
            INSERT INTO nexgen_stok_hareket
              (stok_kart_id, hareket_tipi, miktar_kg,
               onceki_stok, sonraki_stok,
               aciklama, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            kart_id, hareket_tipi, miktar_kayit,
            onceki, sonraki,
            aciklama, _kullanici_id()
        ))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({
        "ok": True,
        "onceki_stok": onceki,
        "sonraki_stok": sonraki,
        "hareket_tipi": hareket_tipi,
    })


# ─────────────────────────────────────────────────────────────
# API — Kart pasif/aktif yap (silme yok)
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart-durum', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_update')
def api_stok_kart_durum():
    data = request.get_json(silent=True) or {}
    kart_id = data.get('id')
    aktif   = 1 if data.get('aktif') else 0

    if not kart_id:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    con = _db()
    try:
        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=?", (kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Kart bulunamadı."}), 404

        con.execute("""
            UPDATE nexgen_stok_kart
            SET aktif=?, guncelleyen_id=?, guncelleme_tarihi=datetime('now')
            WHERE id=?
        """, (aktif, _kullanici_id(), kart_id))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "aktif": aktif})


# ─────────────────────────────────────────────────────────────
# Placeholder Alt Sayfalar (satinalma ve stok-kartlari hariç)
# ─────────────────────────────────────────────────────────────
_SAYFALAR = {
    'depo':      ('Depo & Stok',    'Hammadde depo ve stok takip ekranı.'),
    'formuller': ('Formüller',       'Ürün başına hammadde formül tanımları.'),
    'uretim':    ('Üretim Tablet',   'Üretim sürecinde kullanılan hammadde giriş/çıkış ekranı.'),
    'recycle':   ('Recycle',         'Geri dönüşüm ve fire takip ekranı.'),
    'deneme':    ('Deneme',          'Deneme/prototip üretim kayıt ekranı.'),
    'sevk':      ('Sevk & Barkod',   'Ürün sevkiyat ve barkod yönetim ekranı.'),
    'maliyet':   ('Maliyet & Rapor', 'Hammadde maliyet analizi ve raporlama ekranı.'),
    'raporlar':  ('Raporlar',        'NexGen genel raporlar merkezi.'),
}


@nexgen_bp.route('/<string:sayfa>')
@yetki_gerekli('nexgen.view', 'can_view')
def alt_sayfa(sayfa):
    if sayfa not in _SAYFALAR:
        abort(404)
    baslik, aciklama = _SAYFALAR[sayfa]
    return render_template(
        'nexgen/placeholder.html',
        active='nexgen',
        sayfa_baslik=baslik,
        sayfa_aciklama=aciklama,
        sayfa_slug=sayfa,
    )


# ═════════════════════════════════════════════════════════════
# FAZ-2: SATIN ALMA MERKEZİ
# ─────────────────────────────────────────────────────────────
# KURAL: Bu bölümde nexgen_stok_hareket INSERT YAPILMAZ.
# ═════════════════════════════════════════════════════════════

def _siparis_no_uret(con):
    """SP-YYYY-NNNN formatında benzersiz sipariş numarası üretir."""
    from datetime import datetime
    yil = datetime.now().strftime('%Y')
    row = con.execute("""
        SELECT MAX(CAST(SUBSTR(siparis_no, -4) AS INTEGER)) AS son
        FROM nexgen_satin_siparis
        WHERE siparis_no LIKE ?
    """, (f'SP-{yil}-%',)).fetchone()
    son = row['son'] if row and row['son'] else 0
    return f'SP-{yil}-{son + 1:04d}'


def _tedarikci_veya_404(con, tedarikci_id):
    t = con.execute(
        "SELECT * FROM nexgen_tedarikci WHERE id=? AND aktif=1", (tedarikci_id,)
    ).fetchone()
    if not t:
        abort(404)
    return t


# ─────────────────────────────────────────────────────────────
# Satın Alma Ana Sayfa
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma')
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def satinalma_index():
    con = _db()
    try:
        durum_filtre = request.args.get('durum', '')
        tedarikci_filtre = request.args.get('tedarikci_id', '')

        sorgu = """
            SELECT s.id, s.siparis_no, s.siparis_tarihi, s.beklenen_teslim,
                   s.siparis_miktari_kg, s.para_birimi, s.durum, s.onay_durumu,
                   s.birim_fiyat, s.birim_fiyat_try, s.toplam_tutar_try,
                   s.vade_tarihi, s.aciklama,
                   t.ad AS tedarikci_ad, t.id AS tedarikci_id,
                   k.kod AS stok_kod, k.ad AS stok_ad
            FROM nexgen_satin_siparis s
            JOIN nexgen_tedarikci t ON t.id = s.tedarikci_id
            JOIN nexgen_stok_kart k ON k.id = s.stok_kart_id
            WHERE 1=1
        """
        params = []
        if durum_filtre:
            sorgu += " AND s.durum = ?"
            params.append(durum_filtre)
        if tedarikci_filtre:
            sorgu += " AND s.tedarikci_id = ?"
            params.append(tedarikci_filtre)
        sorgu += " ORDER BY s.id DESC"

        siparisler_raw = con.execute(sorgu, params).fetchall()
        tedarikciler   = con.execute(
            "SELECT id, ad FROM nexgen_tedarikci WHERE aktif=1 ORDER BY ad"
        ).fetchall()

    finally:
        con.close()

    can_manage     = yetki_var('nexgen.satinalma.manage', 'can_create')
    can_approve    = yetki_var('nexgen.satinalma.approve', 'can_approve')
    can_fiyat      = yetki_var('nexgen.satinalma.fiyat', 'can_view')
    # Tedarikçi yönetimi: sadece Yönetim rolü — Satın Alma sadece görüntüler
    can_ted_manage = yetki_var('nexgen.tedarikci.manage', 'can_create')
    can_fiyat_view = yetki_var('nexgen.fiyat.view', 'can_view')

    siparisler = [dict(s) for s in siparisler_raw]

    return render_template(
        'nexgen/satinalma_index.html',
        active='nexgen',
        siparisler=siparisler,
        tedarikciler=[dict(t) for t in tedarikciler],
        durum_filtre=durum_filtre,
        tedarikci_filtre=tedarikci_filtre,
        can_manage=can_manage,
        can_approve=can_approve,
        can_fiyat=can_fiyat,
        can_ted_manage=can_ted_manage,
        can_fiyat_view=can_fiyat_view,
    )


# ─────────────────────────────────────────────────────────────
# Sipariş Detay
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/siparis/<int:siparis_id>')
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def satinalma_siparis_detay(siparis_id):
    con = _db()
    try:
        siparis = con.execute("""
            SELECT s.*,
                   t.ad AS tedarikci_ad, t.kod AS tedarikci_kod,
                   t.ulke, t.iletisim_email,
                   k.kod AS stok_kod, k.ad AS stok_ad, k.kategori AS stok_kategori,
                   oc.KullaniciAdi AS olusturan_ad,
                   ap.KullaniciAdi AS onaylayan_ad
            FROM nexgen_satin_siparis s
            JOIN nexgen_tedarikci t ON t.id = s.tedarikci_id
            JOIN nexgen_stok_kart k ON k.id = s.stok_kart_id
            LEFT JOIN sistem_kullanici oc ON oc.Id = s.olusturan_id
            LEFT JOIN sistem_kullanici ap ON ap.Id = s.onaylayan_id
            WHERE s.id = ?
        """, (siparis_id,)).fetchone()
        if not siparis:
            abort(404)
    finally:
        con.close()

    can_approve = yetki_var('nexgen.satinalma.approve', 'can_approve')
    can_manage  = yetki_var('nexgen.satinalma.manage', 'can_update')
    can_fiyat   = yetki_var('nexgen.satinalma.fiyat', 'can_view')

    return render_template(
        'nexgen/satinalma_siparis_detay.html',
        active='nexgen',
        siparis=dict(siparis),
        can_approve=can_approve,
        can_manage=can_manage,
        can_fiyat=can_fiyat,
    )


# ─────────────────────────────────────────────────────────────
# Tedarikçi Listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/tedarikci')
@yetki_gerekli('nexgen.tedarikci.view', 'can_view')
def satinalma_tedarikci():
    con = _db()
    try:
        tedarikciler = con.execute("""
            SELECT t.*,
                   COUNT(s.id) AS siparis_sayisi
            FROM nexgen_tedarikci t
            LEFT JOIN nexgen_satin_siparis s ON s.tedarikci_id = t.id
            GROUP BY t.id
            ORDER BY t.aktif DESC, t.ad
        """).fetchall()
    finally:
        con.close()

    can_manage = yetki_var('nexgen.tedarikci.manage', 'can_create')

    return render_template(
        'nexgen/satinalma_tedarikci.html',
        active='nexgen',
        tedarikciler=[dict(t) for t in tedarikciler],
        can_manage=can_manage,
    )


# ─────────────────────────────────────────────────────────────
# API — Yeni Sipariş Oluştur
# POST /nexgen/api/satinalma/siparis-ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/siparis-ekle', methods=['POST'])
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_siparis_ekle():
    data = request.get_json(silent=True) or {}

    tedarikci_id  = data.get('tedarikci_id')
    stok_kart_id  = data.get('stok_kart_id')
    siparis_tarihi = (data.get('siparis_tarihi') or '').strip()
    beklenen_teslim = (data.get('beklenen_teslim') or '').strip() or None
    aciklama = (data.get('aciklama') or '').strip() or None
    para_birimi = (data.get('para_birimi') or 'TRY').strip().upper()
    onay_durumu = 'TASLAK' if data.get('taslak') else 'ONAY_BEKLIYOR'

    try:
        miktar = float(data.get('siparis_miktari_kg') or 0)
        if miktar <= 0:
            return jsonify({"ok": False, "hata": "Sipariş miktarı sıfırdan büyük olmalı."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz sipariş miktarı."}), 400

    birim_fiyat = None
    kur = None
    birim_fiyat_try = None
    toplam_tutar_try = None
    vade_gun = None
    vade_tarihi = None

    try:
        if data.get('birim_fiyat') not in (None, ''):
            birim_fiyat = float(data['birim_fiyat'])
            if birim_fiyat < 0:
                return jsonify({"ok": False, "hata": "Birim fiyat negatif olamaz."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz birim fiyat."}), 400

    try:
        if data.get('kur') not in (None, ''):
            kur = float(data['kur'])
            if kur <= 0:
                return jsonify({"ok": False, "hata": "Kur sıfırdan büyük olmalı."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz kur değeri."}), 400

    if birim_fiyat is not None:
        k = kur if (kur and para_birimi != 'TRY') else 1.0
        birim_fiyat_try = round(birim_fiyat * k, 4)
        toplam_tutar_try = round(birim_fiyat_try * miktar, 2)

    try:
        if data.get('vade_gun') not in (None, ''):
            vade_gun = int(data['vade_gun'])
            if siparis_tarihi and vade_gun >= 0:
                from datetime import date, timedelta
                base = date.fromisoformat(siparis_tarihi)
                vade_tarihi = (base + timedelta(days=vade_gun)).isoformat()
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    GECERLI_PARA = {'TRY', 'USD', 'EUR', 'GBP', 'CNY'}
    if para_birimi not in GECERLI_PARA:
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {para_birimi}"}), 400

    if not tedarikci_id:
        return jsonify({"ok": False, "hata": "tedarikci_id zorunludur."}), 400
    if not stok_kart_id:
        return jsonify({"ok": False, "hata": "stok_kart_id zorunludur."}), 400
    if not siparis_tarihi:
        return jsonify({"ok": False, "hata": "siparis_tarihi zorunludur."}), 400

    con = _db()
    try:
        ted = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE id=? AND aktif=1", (tedarikci_id,)
        ).fetchone()
        if not ted:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı veya pasif."}), 404

        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=? AND aktif=1", (stok_kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı veya pasif."}), 404

        siparis_no = _siparis_no_uret(con)

        con.execute("""
            INSERT INTO nexgen_satin_siparis
              (siparis_no, tedarikci_id, stok_kart_id,
               siparis_tarihi, beklenen_teslim,
               siparis_miktari_kg, birim_fiyat, para_birimi, kur,
               birim_fiyat_try, toplam_tutar_try,
               vade_gun, vade_tarihi,
               durum, onay_durumu, aciklama,
               olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?, ?, ?, datetime('now'))
        """, (
            siparis_no, tedarikci_id, stok_kart_id,
            siparis_tarihi, beklenen_teslim,
            miktar, birim_fiyat, para_birimi, kur,
            birim_fiyat_try, toplam_tutar_try,
            vade_gun, vade_tarihi,
            onay_durumu, aciklama,
            _kullanici_id(),
        ))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "siparis_no": siparis_no})


# ─────────────────────────────────────────────────────────────
# API — Sipariş Onay/Red/İptal
# POST /nexgen/api/satinalma/siparis-durum
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/siparis-durum', methods=['POST'])
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def api_satinalma_siparis_durum():
    data = request.get_json(silent=True) or {}
    siparis_id = data.get('id')
    eylem = (data.get('eylem') or '').strip().upper()

    if not siparis_id:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    EYLEMLER = {'ONAYLA', 'REDDET', 'IPTAL', 'ONAYA_GONDER'}
    if eylem not in EYLEMLER:
        return jsonify({"ok": False, "hata": f"Geçersiz eylem: {eylem}"}), 400

    # Onay eylemi sadece approve yetkisiyle
    if eylem in ('ONAYLA', 'REDDET'):
        if not yetki_var('nexgen.satinalma.approve', 'can_approve'):
            return jsonify({"ok": False, "hata": "Onay/red yetkisi yok."}), 403

    # İptal: manage yetkisi yeterli
    if eylem == 'IPTAL':
        if not yetki_var('nexgen.satinalma.manage', 'can_update'):
            return jsonify({"ok": False, "hata": "İptal yetkisi yok."}), 403

    con = _db()
    try:
        siparis = con.execute(
            "SELECT id, onay_durumu, durum FROM nexgen_satin_siparis WHERE id=?",
            (siparis_id,)
        ).fetchone()
        if not siparis:
            return jsonify({"ok": False, "hata": "Sipariş bulunamadı."}), 404

        mevcut_onay = siparis['onay_durumu']
        mevcut_durum = siparis['durum']

        # Durum geçiş kuralları
        if eylem == 'ONAYA_GONDER':
            if mevcut_onay not in ('TASLAK', 'REDDEDILDI'):
                return jsonify({"ok": False, "hata": "Sadece Taslak veya Reddedilmiş sipariş onaya gönderilebilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='ONAY_BEKLIYOR',
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), siparis_id))

        elif eylem == 'ONAYLA':
            if mevcut_onay != 'ONAY_BEKLIYOR':
                return jsonify({"ok": False, "hata": "Sadece Onay Bekleyen sipariş onaylanabilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='ONAYLANDI',
                    onaylayan_id=?, onay_tarihi=datetime('now'),
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), _kullanici_id(), siparis_id))

        elif eylem == 'REDDET':
            if mevcut_onay != 'ONAY_BEKLIYOR':
                return jsonify({"ok": False, "hata": "Sadece Onay Bekleyen sipariş reddedilebilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='REDDEDILDI',
                    onaylayan_id=?, onay_tarihi=datetime('now'),
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), _kullanici_id(), siparis_id))

        elif eylem == 'IPTAL':
            if mevcut_durum == 'TAMAMLANDI':
                return jsonify({"ok": False, "hata": "Tamamlanmış sipariş iptal edilemez."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET durum='IPTAL',
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), siparis_id))

        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "eylem": eylem})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Ekle
# POST /nexgen/api/satinalma/tedarikci-ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-ekle', methods=['POST'])
@yetki_gerekli('nexgen.tedarikci.manage', 'can_create')
def api_tedarikci_ekle():
    data = request.get_json(silent=True) or {}
    kod   = (data.get('kod') or '').strip().upper()
    ad    = (data.get('ad') or '').strip()
    ulke  = (data.get('ulke') or 'TR').strip().upper()
    pb    = (data.get('para_birimi') or 'TRY').strip().upper()
    notlar = (data.get('notlar') or '').strip() or None
    iletisim_ad    = (data.get('iletisim_ad') or '').strip() or None
    iletisim_tel   = (data.get('iletisim_tel') or '').strip() or None
    iletisim_email = (data.get('iletisim_email') or '').strip() or None

    try:
        vade = int(data.get('varsayilan_vade') or 30)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    if not kod:
        return jsonify({"ok": False, "hata": "Kod zorunludur."}), 400
    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400

    GECERLI_PARA = {'TRY', 'USD', 'EUR', 'GBP', 'CNY'}
    if pb not in GECERLI_PARA:
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {pb}"}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE kod=?", (kod,)
        ).fetchone()
        if mevcut:
            return jsonify({"ok": False, "hata": f"'{kod}' kodu zaten mevcut."}), 409

        con.execute("""
            INSERT INTO nexgen_tedarikci
              (kod, ad, ulke, para_birimi, varsayilan_vade,
               iletisim_ad, iletisim_tel, iletisim_email, notlar,
               aktif, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
        """, (kod, ad, ulke, pb, vade,
              iletisim_ad, iletisim_tel, iletisim_email, notlar,
              _kullanici_id()))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "kod": kod, "ad": ad})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Düzenle
# POST /nexgen/api/satinalma/tedarikci-guncelle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-guncelle', methods=['POST'])
@yetki_gerekli('nexgen.tedarikci.manage', 'can_update')
def api_tedarikci_guncelle():
    data = request.get_json(silent=True) or {}
    tid  = data.get('id')
    if not tid:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    ad    = (data.get('ad') or '').strip()
    ulke  = (data.get('ulke') or 'TR').strip().upper()
    pb    = (data.get('para_birimi') or 'TRY').strip().upper()
    notlar = (data.get('notlar') or '').strip() or None
    iletisim_ad    = (data.get('iletisim_ad') or '').strip() or None
    iletisim_tel   = (data.get('iletisim_tel') or '').strip() or None
    iletisim_email = (data.get('iletisim_email') or '').strip() or None

    try:
        vade = int(data.get('varsayilan_vade') or 30)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE id=?", (tid,)
        ).fetchone()
        if not mevcut:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı."}), 404

        con.execute("""
            UPDATE nexgen_tedarikci
            SET ad=?, ulke=?, para_birimi=?, varsayilan_vade=?,
                iletisim_ad=?, iletisim_tel=?, iletisim_email=?, notlar=?,
                guncelleyen_id=?, guncelleme_tarihi=datetime('now')
            WHERE id=?
        """, (ad, ulke, pb, vade,
              iletisim_ad, iletisim_tel, iletisim_email, notlar,
              _kullanici_id(), tid))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Stok Kartları (satın alma formu için dropdown)
# GET /nexgen/api/satinalma/stok-listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/stok-listesi')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_stok_listesi():
    con = _db()
    try:
        kartlar = con.execute("""
            SELECT id, kod, ad, kategori, birim
            FROM nexgen_stok_kart
            WHERE aktif=1
            ORDER BY kategori, ad
        """).fetchall()
    finally:
        con.close()
    return jsonify({"ok": True, "kartlar": [dict(k) for k in kartlar]})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Listesi (satın alma formu için dropdown)
# GET /nexgen/api/satinalma/tedarikci-listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-listesi')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_tedarikci_listesi():
    con = _db()
    try:
        tedarikciler = con.execute("""
            SELECT id, kod, ad, para_birimi, varsayilan_vade
            FROM nexgen_tedarikci
            WHERE aktif=1
            ORDER BY ad
        """).fetchall()
    finally:
        con.close()
    return jsonify({"ok": True, "tedarikciler": [dict(t) for t in tedarikciler]})


# ═════════════════════════════════════════════════════════════
# FAZ-2.6 — HAFTALlK FİYAT YÖNETİMİ
# ═════════════════════════════════════════════════════════════
# KURAL: Bu bölümde nexgen_stok_hareket INSERT YAPILMAZ.
# Fiyat geçmişi ≠ stok hareketi.
# ─────────────────────────────────────────────────────────────


def _isoweek():
    """Geçerli ISO hafta kodu: '2026-W26'"""
    today = date.today()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _son_fiyat(con, tedarikci_id, stok_kart_id):
    """
    Son aktif fiyat kaydını döndür.
    Kural: aktif=1 AND ORDER BY fiyat_tarihi DESC, id DESC LIMIT 1
    """
    return con.execute("""
        SELECT nhf.*, t.ad AS tedarikci_ad, sk.ad AS stok_ad,
               sk.kod AS stok_kod
        FROM nexgen_hammadde_fiyat nhf
        JOIN nexgen_tedarikci t ON t.id = nhf.tedarikci_id
        JOIN nexgen_stok_kart sk ON sk.id = nhf.stok_kart_id
        WHERE nhf.tedarikci_id = ?
          AND nhf.stok_kart_id = ?
          AND nhf.aktif = 1
        ORDER BY nhf.fiyat_tarihi DESC, nhf.id DESC
        LIMIT 1
    """, (tedarikci_id, stok_kart_id)).fetchone()


def _fiyat_farki(eski_fiyat, eski_pb, yeni_fiyat, yeni_pb):
    """Aynı para birimi varsa fark ve yüzde hesapla."""
    if eski_fiyat is None or yeni_fiyat is None:
        return None, None
    if eski_pb != yeni_pb:
        return None, None
    fark = yeni_fiyat - eski_fiyat
    yuzde = (fark / eski_fiyat * 100) if eski_fiyat != 0 else None
    return round(fark, 4), round(yuzde, 2) if yuzde is not None else None


# ─────────────────────────────────────────────────────────────
# Fiyat Listesi — GET /nexgen/satinalma/fiyat
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat')
@yetki_gerekli('nexgen.fiyat.view', 'can_view')
def fiyat_listesi():
    con = _db()
    try:
        tedarikci_id = request.args.get('tedarikci_id', type=int)
        stok_kart_id = request.args.get('stok_kart_id', type=int)

        q = """
            SELECT nhf.id, nhf.fiyat, nhf.para_birimi, nhf.kur, nhf.fiyat_try,
                   nhf.vade_gun, nhf.fiyat_tarihi, nhf.kaynak, nhf.notlar,
                   nhf.aktif, nhf.batch_id,
                   t.kod AS tedarikci_kodu, t.ad AS tedarikci_ad,
                   sk.kod AS stok_kodu, sk.ad AS stok_ad
            FROM nexgen_hammadde_fiyat nhf
            JOIN nexgen_tedarikci t ON t.id = nhf.tedarikci_id
            JOIN nexgen_stok_kart sk ON sk.id = nhf.stok_kart_id
            WHERE 1=1
        """
        params = []
        if tedarikci_id:
            q += " AND nhf.tedarikci_id = ?"
            params.append(tedarikci_id)
        if stok_kart_id:
            q += " AND nhf.stok_kart_id = ?"
            params.append(stok_kart_id)
        q += " ORDER BY nhf.fiyat_tarihi DESC, nhf.id DESC LIMIT 200"

        fiyatlar = con.execute(q, params).fetchall()
        tedarikciler = con.execute(
            "SELECT id, kod, ad FROM nexgen_tedarikci WHERE aktif=1 ORDER BY ad"
        ).fetchall()
        stok_kartlari = con.execute(
            "SELECT id, kod, ad FROM nexgen_stok_kart WHERE aktif=1 ORDER BY kod"
        ).fetchall()
        son_batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch ORDER BY id DESC LIMIT 5"
        ).fetchall()

        can_manage = yetki_var('nexgen.fiyat.manage', 'can_create')
        can_admin  = yetki_var('nexgen.fiyat.admin', 'can_manage')
    finally:
        con.close()

    return render_template(
        'nexgen/fiyat_listesi.html',
        fiyatlar=fiyatlar,
        tedarikciler=tedarikciler,
        stok_kartlari=stok_kartlari,
        son_batch=son_batch,
        filtre_tedarikci=tedarikci_id,
        filtre_stok=stok_kart_id,
        can_manage=can_manage,
        can_admin=can_admin,
        active='nexgen'
    )


# ─────────────────────────────────────────────────────────────
# Excel Şablon İndir — GET /nexgen/satinalma/fiyat-sablonu-indir
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-sablonu-indir')
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_sablonu_indir():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return jsonify({"ok": False, "hata": "openpyxl yüklü değil"}), 500

    con = _db()
    try:
        eslesmeler = con.execute("""
            SELECT ts.id, t.kod AS t_kod, t.ad AS t_ad, t.varsayilan_vade,
                   sk.kod AS s_kod, sk.ad AS s_ad,
                   t.id AS tedarikci_id, sk.id AS stok_kart_id
            FROM nexgen_tedarikci_stok ts
            JOIN nexgen_tedarikci t ON t.id = ts.tedarikci_id
            JOIN nexgen_stok_kart sk ON sk.id = ts.stok_kart_id
            WHERE ts.aktif = 1 AND t.aktif = 1 AND sk.aktif = 1
            ORDER BY t.kod, sk.kod
        """).fetchall()

        son_fiyatlar = {}
        for e in eslesmeler:
            sf = _son_fiyat(con, e['tedarikci_id'], e['stok_kart_id'])
            son_fiyatlar[(e['tedarikci_id'], e['stok_kart_id'])] = sf
    finally:
        con.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fiyat Girişi"

    bugun = date.today().isoformat()
    hafta = _isoweek()

    baslik_font = Font(bold=True, color="FFFFFF")
    baslik_dolu = PatternFill("solid", fgColor="2C3E50")
    kilitli_dolu = PatternFill("solid", fgColor="ECF0F1")
    orta = Alignment(horizontal="center")

    basliklar = [
        "tedarikci_kodu", "tedarikci_adi", "stok_kodu", "stok_adi",
        "fiyat", "para_birimi", "kur", "vade_gun",
        "fiyat_tarihi", "gecerlilik_bas", "gecerlilik_bitis", "not",
        "son_fiyat_bilgi"
    ]
    ws.append(basliklar)
    for col, hdr in enumerate(basliklar, 1):
        cell = ws.cell(row=1, column=col)
        cell.font = baslik_font
        cell.fill = baslik_dolu
        cell.alignment = orta

    for e in eslesmeler:
        sf = son_fiyatlar.get((e['tedarikci_id'], e['stok_kart_id']))
        son_fiyat_bilgi = ""
        if sf:
            son_fiyat_bilgi = f"{sf['fiyat']} {sf['para_birimi']} ({sf['fiyat_tarihi']})"

        row = [
            e['t_kod'], e['t_ad'], e['s_kod'], e['s_ad'],
            None, "USD", None, e['varsayilan_vade'],
            bugun, bugun, None, None,
            son_fiyat_bilgi
        ]
        ws.append(row)

        r_idx = ws.max_row
        for col in [1, 2, 3, 4, 13]:
            ws.cell(row=r_idx, column=col).fill = kilitli_dolu

    for col_idx, width in zip(range(1, 14), [14, 22, 14, 28, 10, 12, 10, 10, 13, 13, 14, 20, 25]):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    ws.freeze_panes = "E2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    dosya_adi = f"NexGen_Fiyat_Sablonu_{hafta}.xlsx"
    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={dosya_adi}"}
    )


# ─────────────────────────────────────────────────────────────
# Excel Yükle + Preview — POST /nexgen/satinalma/fiyat-yukle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-yukle', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_yukle():
    try:
        import openpyxl
    except ImportError:
        return jsonify({"ok": False, "hata": "openpyxl yüklü değil"}), 500

    f = request.files.get('dosya')
    if not f or not f.filename.endswith('.xlsx'):
        return jsonify({"ok": False, "hata": "Geçerli bir .xlsx dosyası seçin"}), 400

    kullanici_id = _kullanici_id()
    hafta = _isoweek()

    con = _db()
    try:
        # Batch kaydı oluştur
        con.execute("""
            INSERT INTO nexgen_fiyat_batch
              (hafta_kodu, dosya_adi, durum, yukleyen_id)
            VALUES (?, ?, 'ONAY_BEKLIYOR', ?)
        """, (hafta, f.filename, kullanici_id))
        con.commit()
        batch_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Excel parse
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active

        tedarikci_map = {r[0]: r[1] for r in con.execute(
            "SELECT kod, id FROM nexgen_tedarikci"
        ).fetchall()}
        stok_map = {r[0]: r[1] for r in con.execute(
            "SELECT kod, id FROM nexgen_stok_kart"
        ).fetchall()}

        toplam = gecerli = hatali = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            t_kod = str(row[0]).strip() if row[0] else None
            s_kod = str(row[2]).strip() if row[2] else None
            fiyat_raw = row[4]
            pb = str(row[5]).strip().upper() if row[5] else 'USD'
            kur = row[6]
            vade = row[7]
            f_tarih = str(row[8]).strip() if row[8] else date.today().isoformat()
            g_bas = str(row[9]).strip() if row[9] else None
            g_bit = str(row[10]).strip() if row[10] else None
            notlar = str(row[11]).strip() if row[11] else None

            toplam += 1

            if fiyat_raw is None or str(fiyat_raw).strip() == '':
                continue

            hata = None
            t_id = s_id = None
            try:
                fiyat = float(fiyat_raw)
                if fiyat <= 0:
                    hata = "Fiyat sıfır veya negatif olamaz"
            except (ValueError, TypeError):
                hata = f"Geçersiz fiyat: {fiyat_raw}"
                fiyat = None

            if t_kod not in tedarikci_map:
                hata = f"Tedarikçi kodu bulunamadı: {t_kod}"
            else:
                t_id = tedarikci_map[t_kod]

            if s_kod not in stok_map:
                hata = (hata + " | " if hata else "") + f"Stok kodu bulunamadı: {s_kod}"
            else:
                s_id = stok_map[s_kod]

            onceki = None
            fark = yuzde = None
            if t_id and s_id:
                onceki = _son_fiyat(con, t_id, s_id)
            if onceki and fiyat and not hata:
                fark, yuzde = _fiyat_farki(
                    onceki['fiyat'], onceki['para_birimi'], fiyat, pb
                )

            fiyat_try = None
            if fiyat and kur:
                try:
                    fiyat_try = round(float(fiyat) * float(kur), 4)
                except Exception:
                    pass

            gecerli_mi = 0 if hata else 1
            if gecerli_mi:
                gecerli += 1
            else:
                hatali += 1

            con.execute("""
                INSERT INTO nexgen_fiyat_batch_detay
                  (batch_id, tedarikci_kodu, stok_kodu, tedarikci_id, stok_kart_id,
                   fiyat, para_birimi, kur, fiyat_try, vade_gun,
                   fiyat_tarihi, gecerlilik_bas, gecerlilik_bitis, notlar,
                   onceki_fiyat, onceki_pb, onceki_tarih, fark, yuzde_degisim,
                   gecerli_mi, hata_sebebi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                batch_id, t_kod, s_kod, t_id, s_id,
                fiyat, pb, kur, fiyat_try, vade,
                f_tarih, g_bas, g_bit, notlar,
                onceki['fiyat'] if onceki else None,
                onceki['para_birimi'] if onceki else None,
                onceki['fiyat_tarihi'] if onceki else None,
                fark, yuzde,
                gecerli_mi, hata
            ))

        con.execute("""
            UPDATE nexgen_fiyat_batch
            SET toplam_satir=?, gecerli_satir=?, hatali_satir=?
            WHERE id=?
        """, (toplam, gecerli, hatali, batch_id))
        con.commit()
    finally:
        con.close()

    return redirect(url_for('nexgen.fiyat_preview', batch_id=batch_id))


# ─────────────────────────────────────────────────────────────
# Preview — GET /nexgen/satinalma/fiyat-preview/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-preview/<int:batch_id>')
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_preview(batch_id):
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            abort(404)

        if batch['durum'] != 'ONAY_BEKLIYOR':
            flash(f"Bu batch artık işlenemez: durum={batch['durum']}", "warning")
            return redirect(url_for('nexgen.fiyat_listesi'))

        detaylar = con.execute("""
            SELECT * FROM nexgen_fiyat_batch_detay
            WHERE batch_id=?
            ORDER BY tedarikci_kodu, stok_kodu
        """, (batch_id,)).fetchall()

        can_approve = yetki_var('nexgen.fiyat.approve', 'can_approve')
    finally:
        con.close()

    return render_template(
        'nexgen/fiyat_preview.html',
        batch=batch,
        detaylar=detaylar,
        can_approve=can_approve,
        active='nexgen'
    )


# ─────────────────────────────────────────────────────────────
# Onayla — POST /nexgen/satinalma/fiyat-onayla/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-onayla/<int:batch_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.approve', 'can_approve')
def fiyat_onayla(batch_id):
    kullanici_id = _kullanici_id()
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch or batch['durum'] != 'ONAY_BEKLIYOR':
            return jsonify({"ok": False, "hata": "Geçersiz veya işlenmiş batch"}), 400

        detaylar = con.execute("""
            SELECT * FROM nexgen_fiyat_batch_detay
            WHERE batch_id=? AND gecerli_mi=1
              AND tedarikci_id IS NOT NULL AND stok_kart_id IS NOT NULL
              AND fiyat IS NOT NULL
        """, (batch_id,)).fetchall()

        eklendi = 0
        for d in detaylar:
            con.execute("""
                INSERT INTO nexgen_hammadde_fiyat
                  (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
                   vade_gun, fiyat_tarihi, gecerlilik_bas, gecerlilik_bitis,
                   kaynak, batch_id, notlar, aktif, olusturan_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,'EXCEL_IMPORT',?,?,1,?)
            """, (
                d['tedarikci_id'], d['stok_kart_id'],
                d['fiyat'], d['para_birimi'], d['kur'], d['fiyat_try'],
                d['vade_gun'], d['fiyat_tarihi'], d['gecerlilik_bas'], d['gecerlilik_bitis'],
                batch_id, d['notlar'], kullanici_id
            ))
            eklendi += 1

        con.execute("""
            UPDATE nexgen_fiyat_batch
            SET durum='ONAYLANDI', onaylayan_id=?, onay_tarihi=datetime('now')
            WHERE id=?
        """, (kullanici_id, batch_id))
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True, "eklendi": eklendi})


# ─────────────────────────────────────────────────────────────
# İptal — POST /nexgen/satinalma/fiyat-iptal/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-iptal/<int:batch_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_iptal(batch_id):
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch or batch['durum'] != 'ONAY_BEKLIYOR':
            return jsonify({"ok": False, "hata": "Geçersiz veya işlenmiş batch"}), 400

        con.execute("DELETE FROM nexgen_fiyat_batch_detay WHERE batch_id=?", (batch_id,))
        con.execute(
            "UPDATE nexgen_fiyat_batch SET durum='IPTAL' WHERE id=?", (batch_id,)
        )
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Manuel Tekil Fiyat Girişi
# POST /nexgen/api/satinalma/fiyat-manuel
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/fiyat-manuel', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def api_fiyat_manuel():
    if not request.is_json:
        return jsonify({"ok": False, "hata": "JSON bekleniyor"}), 400
    d = request.json
    tedarikci_id = d.get('tedarikci_id')
    stok_kart_id = d.get('stok_kart_id')
    fiyat        = d.get('fiyat')
    para_birimi  = d.get('para_birimi', 'USD')
    kur          = d.get('kur')
    vade_gun     = d.get('vade_gun')
    fiyat_tarihi = d.get('fiyat_tarihi')
    notlar       = d.get('notlar')

    if not all([tedarikci_id, stok_kart_id, fiyat, fiyat_tarihi]):
        return jsonify({"ok": False, "hata": "Zorunlu alanlar eksik"}), 400
    if para_birimi not in ('USD', 'EUR', 'TRY', 'GBP', 'CNY'):
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {para_birimi}"}), 400

    fiyat_try = None
    if kur:
        try:
            fiyat_try = round(float(fiyat) * float(kur), 4)
        except Exception:
            pass

    kullanici_id = _kullanici_id()
    con = _db()
    try:
        ted  = con.execute("SELECT id FROM nexgen_tedarikci WHERE id=?", (tedarikci_id,)).fetchone()
        stok = con.execute("SELECT id FROM nexgen_stok_kart WHERE id=?", (stok_kart_id,)).fetchone()
        if not ted:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı"}), 400
        if not stok:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı"}), 400

        con.execute("""
            INSERT INTO nexgen_hammadde_fiyat
              (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
               vade_gun, fiyat_tarihi, kaynak, aktif, olusturan_id)
            VALUES (?,?,?,?,?,?,?,?,'MANUEL',1,?)
        """, (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
              vade_gun, fiyat_tarihi, kullanici_id))
        con.commit()
        fiyat_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        con.close()

    return jsonify({"ok": True, "id": fiyat_id})


# ─────────────────────────────────────────────────────────────
# API — Son Fiyat Öner (sipariş formu pre-fill)
# GET /nexgen/api/satinalma/son-fiyat?tedarikci_id=X&stok_kart_id=Y
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/son-fiyat')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_son_fiyat():
    tedarikci_id = request.args.get('tedarikci_id', type=int)
    stok_kart_id = request.args.get('stok_kart_id', type=int)
    if not tedarikci_id or not stok_kart_id:
        return jsonify({"ok": False, "hata": "tedarikci_id ve stok_kart_id gerekli"}), 400

    con = _db()
    try:
        sf = _son_fiyat(con, tedarikci_id, stok_kart_id)
    finally:
        con.close()

    if not sf:
        return jsonify({"ok": True, "fiyat": None})

    return jsonify({
        "ok": True,
        "fiyat": {
            "id": sf['id'],
            "fiyat": sf['fiyat'],
            "para_birimi": sf['para_birimi'],
            "kur": sf['kur'],
            "vade_gun": sf['vade_gun'],
            "fiyat_tarihi": sf['fiyat_tarihi'],
        }
    })


# ─────────────────────────────────────────────────────────────
# API — Fiyat Pasife Al (sadece Yönetim)
# POST /nexgen/api/satinalma/fiyat-pasife-al/<fiyat_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/fiyat-pasife-al/<int:fiyat_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.admin', 'can_manage')
def api_fiyat_pasife_al(fiyat_id):
    sebep = request.json.get('sebep', '') if request.is_json else ''
    kullanici_id = _kullanici_id()
    con = _db()
    try:
        kayit = con.execute(
            "SELECT id, aktif FROM nexgen_hammadde_fiyat WHERE id=?", (fiyat_id,)
        ).fetchone()
        if not kayit:
            return jsonify({"ok": False, "hata": "Kayıt bulunamadı"}), 404
        if not kayit['aktif']:
            return jsonify({"ok": False, "hata": "Zaten pasif"}), 400

        con.execute("""
            UPDATE nexgen_hammadde_fiyat
            SET aktif=0, iptal_sebebi=?, iptal_eden_id=?, iptal_tarihi=datetime('now')
            WHERE id=?
        """, (sebep, kullanici_id, fiyat_id))
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})
