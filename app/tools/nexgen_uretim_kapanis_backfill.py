# -*- coding: utf-8 -*-
"""FAZ-NEXGEN-URETIM-KAPANIS-BACKFILL-1

Tek seferlik, güvenli, idempotent backfill.
Varsayılan: --dry-run (DB write yok).

Kapanış SQL'i yazılmaz; mevcut domain helper kullanılır:
  modules.nexgen.routes._batch_auto_kapat_if_ready
  → _tua_plan_durum_sync → _pzm_siparis_tamamlandi_sync
  → _rf_kullanim_tablet_sync(..., tamamlandi=True)

Kullanım (app dizininden veya repo kökünden):
  python app/tools/nexgen_uretim_kapanis_backfill.py --dry-run
  python app/tools/nexgen_uretim_kapanis_backfill.py --apply --db app/mock_data.db

Server deploy/startup/migration'a bağlanmaz.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
DEFAULT_DB = APP / "mock_data.db"
DEFAULT_OUT = ROOT / "backup" / f"faz_uretim_kapanis_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _utf8() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _connect(db: str | Path, *, write: bool = False) -> sqlite3.Connection:
    db = str(db)
    if write:
        con = sqlite3.connect(db)
    else:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _import_routes():
    """Mevcut kapanış helper'larını yükle (Flask app context gerekmez)."""
    app_s = str(APP)
    if app_s not in sys.path:
        sys.path.insert(0, app_s)
    cwd = os.getcwd()
    try:
        os.chdir(app_s)
        from modules.nexgen import routes as R  # noqa: WPS433
        return R
    finally:
        os.chdir(cwd)


def _parca_sayac(con: sqlite3.Connection, batch_kodu: str) -> dict[str, int]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS toplam,
            SUM(CASE WHEN durum='BITTI' THEN 1 ELSE 0 END) AS bitti,
            SUM(CASE WHEN durum='IPTAL' THEN 1 ELSE 0 END) AS iptal,
            SUM(CASE WHEN durum IS NULL OR TRIM(COALESCE(durum,''))='' THEN 1 ELSE 0 END) AS bos,
            SUM(CASE WHEN durum NOT IN ('BITTI','IPTAL')
                      AND durum IS NOT NULL AND TRIM(durum)!='' THEN 1 ELSE 0 END) AS acik
        FROM nexgen_uretim_parca
        WHERE batch_kodu=?
        """,
        (batch_kodu,),
    ).fetchone()
    return {
        "toplam": int(row["toplam"] or 0),
        "bitti": int(row["bitti"] or 0),
        "iptal": int(row["iptal"] or 0),
        "bos": int(row["bos"] or 0),
        "acik": int(row["acik"] or 0),
    }


def _rf_bilgi(con: sqlite3.Connection, batch_kodu: str, plan_id: int | None) -> dict[str, Any] | None:
    if not _tablo_var(con, "nexgen_rf_kullanim"):
        return None
    row = con.execute(
        """
        SELECT id, durum, miktar_kg, tablet_session_id, aktif
        FROM nexgen_rf_kullanim
        WHERE aktif=1 AND tablet_session_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (batch_kodu,),
    ).fetchone()
    if not row and plan_id is not None:
        row = con.execute(
            """
            SELECT id, durum, miktar_kg, tablet_session_id, aktif
            FROM nexgen_rf_kullanim
            WHERE aktif=1 AND siparis_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
    return dict(row) if row else None


def _sevk_bilgi(con: sqlite3.Connection, siparis_id: int | None) -> list[dict[str, Any]]:
    if not siparis_id or not _tablo_var(con, "mo_musteri_sevkiyat"):
        return []
    rows = con.execute(
        """
        SELECT s.id, s.sevkiyat_no, s.durum,
               ROUND(COALESCE((
                   SELECT SUM(k.miktar_kg) FROM mo_musteri_sevkiyat_kalem k
                   WHERE k.sevkiyat_id=s.id
               ), 0), 3) AS miktar_kg
        FROM mo_musteri_sevkiyat s
        WHERE s.siparis_id=? AND COALESCE(s.aktif,1)=1
        ORDER BY s.id
        """,
        (siparis_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _plan_batch_ozet(con: sqlite3.Connection, plan_id: int) -> dict[str, int]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS toplam,
            SUM(CASE WHEN durum='BITTI' THEN 1 ELSE 0 END) AS bitti,
            SUM(CASE WHEN durum='IPTAL' THEN 1 ELSE 0 END) AS iptal,
            SUM(CASE WHEN durum NOT IN ('BITTI','IPTAL') THEN 1 ELSE 0 END) AS acik
        FROM nexgen_uretim_batch WHERE plan_id=?
        """,
        (plan_id,),
    ).fetchone()
    return {
        "toplam": int(row["toplam"] or 0),
        "bitti": int(row["bitti"] or 0),
        "iptal": int(row["iptal"] or 0),
        "acik": int(row["acik"] or 0),
    }


def _siparis_plan_ozet(con: sqlite3.Connection, siparis_id: int) -> dict[str, int]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS toplam,
            SUM(CASE WHEN durum='BITTI' THEN 1 ELSE 0 END) AS bitti,
            SUM(CASE WHEN durum='IPTAL' THEN 1 ELSE 0 END) AS iptal,
            SUM(CASE WHEN durum NOT IN ('BITTI','IPTAL') THEN 1 ELSE 0 END) AS acik
        FROM nexgen_uretim_plan WHERE planlama_siparis_id=?
        """,
        (siparis_id,),
    ).fetchone()
    return {
        "toplam": int(row["toplam"] or 0),
        "bitti": int(row["bitti"] or 0),
        "iptal": int(row["iptal"] or 0),
        "acik": int(row["acik"] or 0),
    }


def classify_skip(con: sqlite3.Connection, batch_kodu: str) -> str | None:
    """Aday değilse neden; aday ise None."""
    b = con.execute(
        "SELECT id, batch_kodu, durum, plan_id FROM nexgen_uretim_batch WHERE batch_kodu=?",
        (batch_kodu,),
    ).fetchone()
    if not b:
        return "batch_yok"
    durum = (b["durum"] or "").upper()
    if durum in ("BITTI", "IPTAL"):
        return f"batch_{durum.lower()}"
    if not b["plan_id"]:
        return "orphan_plan_id_yok"
    plan = con.execute(
        "SELECT id, planlama_siparis_id, durum FROM nexgen_uretim_plan WHERE id=?",
        (b["plan_id"],),
    ).fetchone()
    if not plan:
        return "orphan_plan_kaydi_yok"
    if not plan["planlama_siparis_id"]:
        return "siparis_iliski_belirsiz"
    sip = con.execute(
        "SELECT id FROM nexgen_planlama_siparis WHERE id=?",
        (plan["planlama_siparis_id"],),
    ).fetchone()
    if not sip:
        return "siparis_kaydi_yok"
    sip_row = con.execute(
        "SELECT durum FROM nexgen_planlama_siparis WHERE id=?",
        (plan["planlama_siparis_id"],),
    ).fetchone()
    sip_durum = ((sip_row["durum"] if sip_row else "") or "").upper()
    # Stuck üretim senaryosu: sipariş URETIMDE (TALEP vb. otomatik kapanmaz)
    if sip_durum != "URETIMDE":
        return f"siparis_durum_{sip_durum or 'bos'}"
    sc = _parca_sayac(con, batch_kodu)
    if sc["toplam"] <= 0:
        return "parca_yok"
    if sc["bos"] > 0:
        return "parca_durum_bos_null"
    if sc["bitti"] <= 0:
        return "bitti_parca_yok"
    if sc["acik"] > 0:
        return "acik_parca_var"
    return None


def find_candidates(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aday batch'ler + atlanan örnekler."""
    if not _tablo_var(con, "nexgen_uretim_batch") or not _tablo_var(con, "nexgen_uretim_parca"):
        return [], [{"neden": "tablo_yok"}]

    rows = con.execute(
        """
        SELECT b.id AS batch_id, b.batch_kodu, b.durum AS batch_durum, b.plan_id,
               p.id AS plan_id, p.plan_kodu, p.durum AS plan_durum,
               p.planlama_siparis_id AS siparis_id,
               s.siparis_no, s.durum AS siparis_durum, s.cari_unvan, s.cari_id
        FROM nexgen_uretim_batch b
        JOIN nexgen_uretim_plan p ON p.id = b.plan_id
        JOIN nexgen_planlama_siparis s ON s.id = p.planlama_siparis_id
        WHERE UPPER(COALESCE(b.durum, '')) NOT IN ('BITTI', 'IPTAL')
          AND b.plan_id IS NOT NULL
          AND p.planlama_siparis_id IS NOT NULL
          AND UPPER(COALESCE(s.durum, '')) = 'URETIMDE'
          AND EXISTS (
              SELECT 1 FROM nexgen_uretim_parca x
              WHERE x.batch_kodu = b.batch_kodu AND x.durum = 'BITTI'
          )
          AND NOT EXISTS (
              SELECT 1 FROM nexgen_uretim_parca x
              WHERE x.batch_kodu = b.batch_kodu
                AND (
                    x.durum IS NULL OR TRIM(COALESCE(x.durum, '')) = ''
                    OR x.durum NOT IN ('BITTI', 'IPTAL')
                )
          )
        ORDER BY s.id, p.id, b.id
        """
    ).fetchall()

    adaylar: list[dict[str, Any]] = []
    for r in rows:
        sc = _parca_sayac(con, r["batch_kodu"])
        # çift kontrol: boş/açık
        if sc["bos"] > 0 or sc["acik"] > 0 or sc["bitti"] <= 0 or sc["toplam"] <= 0:
            continue
        rf = _rf_bilgi(con, r["batch_kodu"], r["plan_id"])
        sevk = _sevk_bilgi(con, r["siparis_id"])
        plan_oz = _plan_batch_ozet(con, r["plan_id"])
        sip_oz = _siparis_plan_ozet(con, r["siparis_id"])
        beklenen = _predict_close(con, dict(r), sc, plan_oz, sip_oz)
        adaylar.append(
            {
                "siparis_id": r["siparis_id"],
                "siparis_no": r["siparis_no"],
                "cari": r["cari_unvan"],
                "cari_id": r["cari_id"],
                "plan_id": r["plan_id"],
                "plan_kodu": r["plan_kodu"],
                "batch_id": r["batch_id"],
                "batch_kodu": r["batch_kodu"],
                "siparis_durum": r["siparis_durum"],
                "plan_durum": r["plan_durum"],
                "batch_durum": r["batch_durum"],
                "parca_toplam": sc["toplam"],
                "parca_bitti": sc["bitti"],
                "parca_iptal": sc["iptal"],
                "parca_acik": sc["acik"],
                "rf": rf,
                "sevkiyat": sevk,
                "plan_batch_ozet": plan_oz,
                "siparis_plan_ozet": sip_oz,
                "beklenen": beklenen,
                "not": (
                    "finans/sevkiyat kaydı kapanışı engellemez"
                    if sevk
                    else "sevkiyat kaydı yok"
                ),
            }
        )

    # Atlananlar: açık batch'ler arasından örnek sınıflandırma
    atlanan: list[dict[str, Any]] = []
    open_batches = con.execute(
        """
        SELECT batch_kodu, durum FROM nexgen_uretim_batch
        WHERE UPPER(COALESCE(durum,'')) NOT IN ('BITTI','IPTAL')
        ORDER BY id DESC LIMIT 500
        """
    ).fetchall()
    aday_set = {a["batch_kodu"] for a in adaylar}
    neden_say = Counter()
    for ob in open_batches:
        if ob["batch_kodu"] in aday_set:
            continue
        neden = classify_skip(con, ob["batch_kodu"]) or "bilinmeyen"
        neden_say[neden] += 1
        if len(atlanan) < 80:
            atlanan.append({"batch_kodu": ob["batch_kodu"], "batch_durum": ob["durum"], "neden": neden})
    return adaylar, [{"neden": k, "adet": v} for k, v in sorted(neden_say.items())] + [
        {"ornekler": atlanan}
    ]


def _predict_close(
    con: sqlite3.Connection,
    row: dict[str, Any],
    sc: dict[str, int],
    plan_oz: dict[str, int],
    sip_oz: dict[str, int],
) -> dict[str, Any]:
    """Helper kurallarını okuma-only tahmin (write yok)."""
    batch_durum = (row.get("batch_durum") or "").upper()
    # Helper DEVAM ister. Stuck HAZIR/BEKLEME + açık parça=0 için apply köprüsü vardır.
    kosuk_bridge = batch_durum in ("HAZIR", "BEKLEME")
    if batch_durum not in ("DEVAM", "HAZIR", "BEKLEME"):
        return {
            "batch": batch_durum,
            "plan": row.get("plan_durum"),
            "siparis": row.get("siparis_durum"),
            "rf_durum": "degismez",
            "kapaniyor": False,
            "neden": f"desteklenmeyen_batch_durum_{batch_durum}",
        }

    # Bu batch kapanınca plan açık batch sayısı
    diger_acik = plan_oz["acik"] - 1  # bu batch şu an acik sayımında
    plan_kapanir = diger_acik <= 0 and (plan_oz["bitti"] + 1) >= 1
    plan_son = "BITTI" if plan_kapanir and (row.get("plan_durum") or "") in (
        "BASLADI",
        "URETIMDE",
    ) else row.get("plan_durum")

    sip_son = row.get("siparis_durum")
    if plan_kapanir and plan_son == "BITTI":
        sip_acik_sonra = sip_oz["acik"] - (
            1 if (row.get("plan_durum") or "") not in ("BITTI", "IPTAL") else 0
        )
        sip_bitti_sonra = sip_oz["bitti"] + (
            1 if (row.get("plan_durum") or "") != "BITTI" else 0
        )
        if sip_acik_sonra <= 0 and sip_bitti_sonra > 0:
            if (row.get("siparis_durum") or "") not in ("IPTAL", "TAMAMLANDI"):
                sip_son = "TAMAMLANDI"

    rf = _rf_bilgi(con, row["batch_kodu"], row.get("plan_id"))
    return {
        "batch": "BITTI",
        "plan": plan_son,
        "siparis": sip_son,
        "rf_durum": "TAMAMLANDI" if rf else "rf_yok_veya_olusturulabilir",
        "rf_miktar_degisir_mi": False,
        "kapaniyor": True,
        "hazir_bridge": kosuk_bridge,
        "plan_kapanir": plan_kapanir,
        "siparis_kapanir": sip_son == "TAMAMLANDI" and row.get("siparis_durum") != "TAMAMLANDI",
    }


def snapshot_chain(con: sqlite3.Connection, batch_kodu: str) -> dict[str, Any]:
    b = con.execute(
        "SELECT id, batch_kodu, durum, plan_id FROM nexgen_uretim_batch WHERE batch_kodu=?",
        (batch_kodu,),
    ).fetchone()
    if not b:
        return {}
    p = con.execute(
        "SELECT id, plan_kodu, durum, planlama_siparis_id FROM nexgen_uretim_plan WHERE id=?",
        (b["plan_id"],),
    ).fetchone()
    s = None
    if p and p["planlama_siparis_id"]:
        s = con.execute(
            "SELECT id, siparis_no, durum, cari_unvan FROM nexgen_planlama_siparis WHERE id=?",
            (p["planlama_siparis_id"],),
        ).fetchone()
    rf = _rf_bilgi(con, batch_kodu, b["plan_id"])
    sevk = _sevk_bilgi(con, p["planlama_siparis_id"] if p else None)
    return {
        "batch": dict(b),
        "plan": dict(p) if p else None,
        "siparis": dict(s) if s else None,
        "parca": _parca_sayac(con, batch_kodu),
        "rf": rf,
        "sevkiyat": sevk,
        "rf_count": int(
            con.execute(
                "SELECT COUNT(*) c FROM nexgen_rf_kullanim WHERE tablet_session_id=? AND aktif=1",
                (batch_kodu,),
            ).fetchone()["c"]
        )
        if _tablo_var(con, "nexgen_rf_kullanim")
        else 0,
    }


def _with_rf_miktar_koruma(R: Any):
    """Backfill: RF durum sync gerçek helper'dan; miktar_kg tarihsel değeri korunur.

    Manuel tablet sync miktarı yeniden hesaplar; geçmiş stuck kayıtlarda
    (ör. SEHA 5030.2) operasyonel RF miktarının değişmemesi gerekir.
    """
    orig = R._rf_kullanim_tablet_sync

    def _wrapped(con, batch_kodu, uretim_emir_id=None, tamamlandi=False):
        once = None
        if _tablo_var(con, "nexgen_rf_kullanim"):
            once = con.execute(
                "SELECT id, miktar_kg FROM nexgen_rf_kullanim "
                "WHERE tablet_session_id=? AND aktif=1 ORDER BY id DESC LIMIT 1",
                (batch_kodu,),
            ).fetchone()
        rid = orig(con, batch_kodu, uretim_emir_id=uretim_emir_id, tamamlandi=tamamlandi)
        if once is not None and tamamlandi:
            con.execute(
                "UPDATE nexgen_rf_kullanim SET miktar_kg=? WHERE id=? AND aktif=1",
                (once["miktar_kg"], once["id"]),
            )
        return rid

    return orig, _wrapped


def apply_candidates(
    con: sqlite3.Connection,
    adaylar: list[dict[str, Any]],
    R: Any,
) -> dict[str, Any]:
    """Kayıt bazlı transaction; mevcut _batch_auto_kapat_if_ready çağırır."""
    results = []
    changed = 0
    orig_rf, wrapped_rf = _with_rf_miktar_koruma(R)
    R._rf_kullanim_tablet_sync = wrapped_rf
    try:
        for a in adaylar:
            bk = a["batch_kodu"]
            before = snapshot_chain(con, bk)
            rf_count_before = before.get("rf_count", 0)
            try:
                con.execute("BEGIN")
                # Stuck HAZIR/BEKLEME: helper DEVAM ister — kapanış SQL'i yazılmaz,
                # yalnız köprü sonra mevcut _batch_auto_kapat_if_ready.
                cur = con.execute(
                    "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu=?",
                    (bk,),
                ).fetchone()
                mevcut = ((cur["durum"] if cur else "") or "").upper()
                if mevcut in ("HAZIR", "BEKLEME"):
                    sc = _parca_sayac(con, bk)
                    if sc["acik"] == 0 and sc["bitti"] > 0 and sc["bos"] == 0:
                        con.execute(
                            "UPDATE nexgen_uretim_batch SET durum='DEVAM' "
                            "WHERE batch_kodu=? AND durum=?",
                            (bk, mevcut),
                        )
                out = R._batch_auto_kapat_if_ready(con, bk)
                after_try = snapshot_chain(con, bk)
                # duplicate RF / miktar regresyon koruması
                if after_try.get("rf_count", 0) > rf_count_before:
                    con.rollback()
                    results.append(
                        {
                            "batch_kodu": bk,
                            "hata": "rf_duplicate_engellendi",
                            "before": before,
                            "after": after_try,
                        }
                    )
                    raise RuntimeError(f"RF duplicate: {bk}")
                if before.get("rf") and after_try.get("rf"):
                    if abs(
                        float(before["rf"].get("miktar_kg") or 0)
                        - float(after_try["rf"].get("miktar_kg") or 0)
                    ) > 0.001:
                        con.rollback()
                        raise RuntimeError(f"RF miktar değişti: {bk}")
                durum_degisti = (
                    (before.get("batch") or {}).get("durum")
                    != (after_try.get("batch") or {}).get("durum")
                    or (before.get("plan") or {}).get("durum")
                    != (after_try.get("plan") or {}).get("durum")
                    or (before.get("siparis") or {}).get("durum")
                    != (after_try.get("siparis") or {}).get("durum")
                    or (before.get("rf") or {}).get("durum")
                    != (after_try.get("rf") or {}).get("durum")
                )
                con.commit()
                if out.get("kapandi") or durum_degisti:
                    changed += 1
                results.append(
                    {
                        "batch_kodu": bk,
                        "helper": out,
                        "before": before,
                        "after": after_try,
                        "kapandi": bool(out.get("kapandi")),
                        "durum_degisti": durum_degisti,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                try:
                    con.rollback()
                except Exception:
                    pass
                results.append({"batch_kodu": bk, "hata": str(exc), "before": before})
                raise
    finally:
        R._rf_kullanim_tablet_sync = orig_rf
    return {"changed": changed, "results": results}


def _render_txt(report: dict[str, Any]) -> str:
    lines = [
        "FAZ-NEXGEN-URETIM-KAPANIS-BACKFILL-1",
        f"mod={report.get('mode')} ts={report.get('ts')}",
        f"db={report.get('db')}",
        "",
        f"aday_batch={report['ozet']['aday_batch']}",
        f"etkilenecek_plan={report['ozet']['etkilenecek_plan']}",
        f"etkilenecek_siparis={report['ozet']['etkilenecek_siparis']}",
        f"apply_changed={report['ozet'].get('apply_changed')}",
        "",
        "--- ADAYLAR ---",
    ]
    for a in report.get("adaylar", []):
        bek = a.get("beklenen") or {}
        lines.append(
            f"{a['siparis_no']}({a['siparis_id']}) | {a['plan_kodu']}({a['plan_id']}) | "
            f"{a['batch_kodu']}({a['batch_id']}) | "
            f"sip={a['siparis_durum']} plan={a['plan_durum']} batch={a['batch_durum']} | "
            f"parca={a['parca_bitti']}/{a['parca_toplam']} acik={a['parca_acik']} | "
            f"rf={a.get('rf')} | sevk={a.get('sevkiyat')} | "
            f"beklenen={bek}"
        )
    lines.append("")
    lines.append("--- ATLANAN NEDEN ÖZET ---")
    for x in report.get("atlanan_ozet", []):
        if "neden" in x and "adet" in x:
            lines.append(f"{x['neden']}: {x['adet']}")
    if report.get("backup"):
        lines.append("")
        lines.append(f"backup={report['backup'].get('path')}")
        lines.append(f"sha256={report['backup'].get('sha256')}")
    lines.append("")
    lines.append("--- SERVER KOMUT PLANI ---")
    lines.extend(SERVER_COMMANDS.splitlines())
    return "\n".join(lines) + "\n"


SERVER_COMMANDS = """
# Canlıda sırayla (bu fazda ÇALIŞTIRMA — sadece plan):
# 1) Server repo + DB yedeği
#    cd C:\\Solariz_CPS_SERVER
#    $ts = Get-Date -Format yyyyMMdd_HHmmss
#    Copy-Item app\\mock_data.db "backup\\pre_kapanis_backfill_$ts\\mock_data.db"
# 2) Git pull
#    git pull origin main
# 3) Test
#    python _test_faz_uretim_kapanis_zinciri_fix1.py
#    python _test_faz_uretim_kapanis_backfill1.py
# 4) Servis restart (ortamınıza göre)
# 5) HTTP /giris 200 doğrula
# 6) Backfill dry-run
#    python app/tools/nexgen_uretim_kapanis_backfill.py --dry-run --db app/mock_data.db
# 7) Dry-run aday raporunu kontrol et (özellikle PZM-2026-0009)
# 8) Apply
#    python app/tools/nexgen_uretim_kapanis_backfill.py --apply --db app/mock_data.db
# 9) İkinci dry-run / ikinci apply → changed=0 beklenir
# 10) Browser: PZM-2026-0009 → TAMAMLANDI
# ASLA: startup / her request / migration içine bağlama
""".strip()


def build_report(
    mode: str,
    db: Path,
    adaylar: list[dict[str, Any]],
    atlanan: list[dict[str, Any]],
    apply_out: dict[str, Any] | None = None,
    backup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_ids = {a["plan_id"] for a in adaylar if (a.get("beklenen") or {}).get("kapaniyor")}
    sip_ids = {
        a["siparis_id"]
        for a in adaylar
        if (a.get("beklenen") or {}).get("siparis_kapanir")
    }
    # dry-run'da etkilenecek = kapanması beklenenler
    if mode == "dry-run":
        et_plan = len(
            {
                a["plan_id"]
                for a in adaylar
                if (a.get("beklenen") or {}).get("plan_kapanir")
            }
        )
        et_sip = len(
            {
                a["siparis_id"]
                for a in adaylar
                if (a.get("beklenen") or {}).get("siparis_kapanir")
            }
        )
    else:
        et_plan = len(plan_ids)
        et_sip = len(sip_ids)
        if apply_out:
            et_plan = len(
                {
                    r["after"]["plan"]["id"]
                    for r in apply_out.get("results", [])
                    if r.get("after", {}).get("plan")
                    and r.get("before", {}).get("plan")
                    and r["before"]["plan"]["durum"] != r["after"]["plan"]["durum"]
                }
            )
            et_sip = len(
                {
                    r["after"]["siparis"]["id"]
                    for r in apply_out.get("results", [])
                    if r.get("after", {}).get("siparis")
                    and r.get("before", {}).get("siparis")
                    and r["before"]["siparis"]["durum"] != r["after"]["siparis"]["durum"]
                }
            )

    return {
        "faz": "FAZ-NEXGEN-URETIM-KAPANIS-BACKFILL-1",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "db": str(db),
        "helpers": [
            "_batch_auto_kapat_if_ready",
            "_tua_plan_durum_sync",
            "_pzm_siparis_tamamlandi_sync",
            "_rf_kullanim_tablet_sync",
        ],
        "ozet": {
            "aday_batch": len(adaylar),
            "etkilenecek_plan": et_plan,
            "etkilenecek_siparis": et_sip,
            "apply_changed": None if apply_out is None else apply_out.get("changed"),
        },
        "adaylar": adaylar,
        "atlanan_ozet": atlanan,
        "apply": apply_out,
        "backup": backup,
        "server_commands": SERVER_COMMANDS,
    }


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="NexGen üretim kapanış backfill (dry-run varsayılan)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Write yok (varsayılan)")
    mode.add_argument("--apply", action="store_true", help="DB write + yedek")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB yolu")
    ap.add_argument("--out", default="", help="Rapor çıktı klasörü")
    args = ap.parse_args(argv)

    # Varsayılan dry-run: --apply yoksa write yok
    do_apply = bool(args.apply)
    mode_name = "apply" if do_apply else "dry-run"

    db = Path(args.db)
    if not db.is_file():
        print(f"FAIL db yok: {db}")
        return 2

    out = Path(args.out) if args.out else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    backup_info = None
    apply_out = None

    if do_apply:
        # 1) timestamp yedek + sha256
        bdir = out / "db_backup"
        bdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bpath = bdir / f"mock_data_pre_backfill_{ts}.db"
        shutil.copy2(db, bpath)
        backup_info = {"path": str(bpath), "sha256": _sha256(bpath)}
        print(f"BACKUP {bpath}")
        print(f"SHA256 {backup_info['sha256']}")

        R = _import_routes()
        # Flask session dışında _kullanici_id / RF sync güvenli çalışsın
        orig_uid = R._kullanici_id
        R._kullanici_id = lambda: 0  # backfill operatör işaretçisi
        con = _connect(db, write=True)
        try:
            adaylar, atlanan = find_candidates(con)
            apply_out = apply_candidates(con, adaylar, R)
            adaylar_after, _ = find_candidates(con)
            report = build_report(mode_name, db, adaylar, atlanan, apply_out, backup_info)
            report["adaylar_after_apply"] = adaylar_after
            report["ozet"]["aday_batch_after"] = len(adaylar_after)
        finally:
            R._kullanici_id = orig_uid
            con.close()
    else:
        con = _connect(db, write=False)
        try:
            adaylar, atlanan = find_candidates(con)
            report = build_report(mode_name, db, adaylar, atlanan, None, None)
        finally:
            con.close()

    jpath = out / f"backfill_{mode_name}.json"
    tpath = out / f"backfill_{mode_name}.txt"
    jpath.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tpath.write_text(_render_txt(report), encoding="utf-8")
    # kısa md
    mpath = out / f"backfill_{mode_name}.md"
    mpath.write_text(
        "# Backfill rapor\n\n```\n" + _render_txt(report) + "```\n",
        encoding="utf-8",
    )

    print(f"MODE {mode_name}")
    print(f"ADAY {report['ozet']['aday_batch']}")
    print(f"PLAN {report['ozet']['etkilenecek_plan']} SIPARIS {report['ozet']['etkilenecek_siparis']}")
    if apply_out is not None:
        print(f"CHANGED {apply_out.get('changed')}")
    print(f"OUT {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
