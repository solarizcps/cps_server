# -*- coding: utf-8 -*-
"""
CANLI SAHA - LEGACY_5055 Read-Only Bridge
==========================================
5055 (solariz.db) uretim_kayit verisini 8080 icinde READ-ONLY gosterir.
5055'e ASLA yazma yapilmaz. SQLite URI mode=ro&nolock=1 kullanilir.
KPI/hedef/usta-onay akislarina dahil DEGILDIR. Sadece goruntuleme.
"""
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
from functools import wraps
import sqlite3
import os

canli_saha_bp = Blueprint('canli_saha', __name__, url_prefix='/canli-saha')

# 5055 DB yolu (local D:\Ortak kullaniliyor, network share alias)
LEGACY_5055_DB = r"D:\Ortak\Solariz-ARGE\solariz.db"

# Maksimum dondurulecek kayit
MAX_KAYIT = 2000


def _login_gerekli(f):
    """Login yeterli, rol kontrolu yok (Canli Saha herkes icin gorulebilir)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def _read_only_baglan():
    """5055 DB'ye READ-ONLY baglan. Hata atarsa None doner."""
    if not os.path.exists(LEGACY_5055_DB):
        return None, "5055 DB bulunamadi: " + LEGACY_5055_DB
    try:
        uri = "file:" + LEGACY_5055_DB.replace("\\", "/") + "?mode=ro&nolock=1"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn, None
    except Exception as e:
        return None, "5055 baglanti hatasi: " + str(e)[:120]


@canli_saha_bp.route('/', methods=['GET'])
@_login_gerekli
def canli_saha_anasayfa():
    """HTML sayfa. JS ile /data endpoint'i fetch edilir."""
    return render_template('canli_saha/index.html')


@canli_saha_bp.route('/data', methods=['GET'])
@_login_gerekli
def canli_saha_data():
    """
    JSON endpoint - 5055 uretim_kayit READ-ONLY veri.

    Query params:
      gun       : Kac gun geriye (default 30, max 365)
      personel  : personel_ad LIKE filtre (opsiyonel)
      emir_no   : emir_no exact match (opsiyonel)

    Response:
      {
        "ok": True,
        "kaynak": "LEGACY_5055",
        "gun": 30,
        "kayit_sayisi": 543,
        "kayitlar": [...],
        "hata": null
      }
    """
    # Param parse
    try:
        gun = int(request.args.get('gun', 30))
        if gun < 1: gun = 1
        if gun > 365: gun = 365
    except Exception:
        gun = 30

    personel_q = (request.args.get('personel') or '').strip()
    emir_q = (request.args.get('emir_no') or '').strip()

    # Baglan
    conn, hata = _read_only_baglan()
    if conn is None:
        return jsonify({
            "ok": False,
            "kaynak": "LEGACY_5055",
            "gun": gun,
            "kayit_sayisi": 0,
            "kayitlar": [],
            "hata": hata or "Bilinmeyen hata"
        })

    try:
        cur = conn.cursor()

        # Tarih filtresi - SQLite date arithmetic
        where_parcalar = ["date(tarih) >= date('now', '-' || ? || ' days')"]
        params = [gun]

        if personel_q:
            where_parcalar.append("personel_ad LIKE ?")
            params.append("%" + personel_q + "%")

        if emir_q and emir_q.isdigit():
            where_parcalar.append("emir_no = ?")
            params.append(int(emir_q))

        where_sql = " AND ".join(where_parcalar)

        sql = (
            "SELECT id, emir_no, model_kod, model_adi, miktar, "
            "personel_id, personel_ad, proses_adi, tarih, saat, "
            "onay_durum, usta_ad, usta_not, onay_tarihi "
            "FROM uretim_kayit "
            "WHERE " + where_sql + " "
            "ORDER BY tarih DESC, saat DESC, id DESC "
            "LIMIT ?"
        )
        params.append(MAX_KAYIT)

        rows = cur.execute(sql, params).fetchall()

        kayitlar = []
        for r in rows:
            kayitlar.append({
                "kaynak": "LEGACY_5055",
                "id_5055": r["id"],
                "emir_no": r["emir_no"],
                "model_kod": r["model_kod"] or "",
                "model_adi": r["model_adi"] or "",
                "miktar": r["miktar"] or 0,
                "personel_id": r["personel_id"],
                "personel_ad": r["personel_ad"] or "",
                "proses_adi": r["proses_adi"] or "",
                "tarih": r["tarih"] or "",
                "saat": r["saat"] or "",
                "onay_durum": r["onay_durum"] or "",
                "usta_ad": r["usta_ad"] or "",
                "usta_not": r["usta_not"] or "",
                "onay_tarihi": r["onay_tarihi"] or ""
            })

        # Ozet hesapla
        toplam_miktar = sum(k["miktar"] for k in kayitlar)
        onayli_say = sum(1 for k in kayitlar if k["onay_durum"] == "onaylandi")
        bekleyen_say = sum(1 for k in kayitlar if k["onay_durum"] == "bekliyor")
        reddedilen_say = sum(1 for k in kayitlar if k["onay_durum"] == "reddedildi")

        return jsonify({
            "ok": True,
            "kaynak": "LEGACY_5055",
            "gun": gun,
            "kayit_sayisi": len(kayitlar),
            "max_limit": MAX_KAYIT,
            "ozet": {
                "toplam_miktar": toplam_miktar,
                "onayli": onayli_say,
                "bekleyen": bekleyen_say,
                "reddedilen": reddedilen_say
            },
            "kayitlar": kayitlar,
            "hata": None
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "kaynak": "LEGACY_5055",
            "gun": gun,
            "kayit_sayisi": 0,
            "kayitlar": [],
            "hata": "Sorgu hatasi: " + str(e)[:200]
        })
    finally:
        try:
            conn.close()
        except Exception:
            pass