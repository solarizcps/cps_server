# -*- coding: utf-8 -*-
"""
SOLARIZ CPS — NexGen Hammadde Yönetimi
=======================================
FAZ-1A : Modül iskeleti, menü, yetki
FAZ-1B : Stok Kart Master + Hareket Motoru altyapısı

Yetki kodları:
  nexgen.view         — modül geneli görüntüleme
  nexgen.stok.view    — stok kartları görüntüleme
  nexgen.stok.manage  — stok kartı ekleme/düzenleme
"""

import sqlite3
import os
from datetime import datetime

from flask import (
    Blueprint, render_template, abort,
    request, jsonify, session, g
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
# Placeholder Alt Sayfalar (stok-kartlari hariç)
# ─────────────────────────────────────────────────────────────
_SAYFALAR = {
    'depo':          ('Depo & Stok',        'Hammadde depo ve stok takip ekranı.'),
    'satinalma':     ('Satın Alma',          'Hammadde satın alma siparişleri ve tedarikçi yönetimi.'),
    'formuller':     ('Formüller',           'Ürün başına hammadde formül tanımları.'),
    'uretim':        ('Üretim Tablet',       'Üretim sürecinde kullanılan hammadde giriş/çıkış ekranı.'),
    'recycle':       ('Recycle',             'Geri dönüşüm ve fire takip ekranı.'),
    'deneme':        ('Deneme',              'Deneme/prototip üretim kayıt ekranı.'),
    'sevk':          ('Sevk & Barkod',       'Ürün sevkiyat ve barkod yönetim ekranı.'),
    'maliyet':       ('Maliyet & Rapor',     'Hammadde maliyet analizi ve raporlama ekranı.'),
    'raporlar':      ('Raporlar',            'NexGen genel raporlar merkezi.'),
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
