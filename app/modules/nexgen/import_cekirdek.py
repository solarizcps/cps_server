# -*- coding: utf-8 -*-
"""
Çekirdek formül import motoru (1BA/2BA/3BA).
Standart import (575/627/810 parent) davranışından tamamen ayrıdır.
"""
from __future__ import annotations

import os
import sqlite3
import hashlib

from modules.nexgen.import_models import ImportPackage
from modules.nexgen.kod_uretici import cekirdek_rv_kodu, cekirdek_uv_ad

CEKIRDEK_GUVENLI_AKSIYONLARI = frozenset({
    "INSERT_FORMUL_CEKIRDEK",
    "INSERT_RV_CEKIRDEK",
    "INSERT_UV_CEKIRDEK",
    "INSERT_ANA_KALEM_CEKIRDEK",
    "IDEMPOTENT_SKIP_CEKIRDEK",
})

_KG_TOLERANS = 1e-9


def _miktar_esit(a: float, b: float, tol: float = _KG_TOLERANS) -> bool:
    return abs(float(a) - float(b)) <= tol


def _cekirdek_uv_id_bul(
    con: sqlite3.Connection, formul_id: int, varyant: str, boyut: str,
) -> int | None:
    from modules.nexgen.import_engine import normalize_ascii_import
    rv_nk = normalize_ascii_import(varyant)
    rows = con.execute(
        "SELECT id, renk FROM nexgen_renk_varyant WHERE formul_id=? AND aktif=1",
        (formul_id,),
    ).fetchall()
    rv_id = None
    for r in rows:
        if normalize_ascii_import(r[1] or "") == rv_nk:
            rv_id = r[0]
            break
    if rv_id is None:
        return None
    uv = con.execute(
        """SELECT id FROM nexgen_uretim_varyant
           WHERE renk_varyant_id=? AND boyut=? AND aktif=1
           ORDER BY id ASC LIMIT 1""",
        (rv_id, boyut),
    ).fetchone()
    return uv[0] if uv else None


def _cekirdek_icerik_set_excel(kol) -> list[tuple[str, float, str, str]]:
    """İçerik fingerprint — sıra hariç: stok + miktar + birim + rol."""
    out = []
    for k in kol.ana_kalemler:
        rol = k.rol.value if hasattr(k.rol, "value") else str(k.rol)
        out.append((
            (k.stok_kodu or "").strip().upper(),
            float(k.miktar_kg),
            (k.birim or "KG").strip().upper(),
            rol,
        ))
    return sorted(out, key=lambda x: (x[0], x[1]))


def _cekirdek_icerik_set_db(con: sqlite3.Connection, uv_id: int) -> list[tuple[str, float, str, str]]:
    rows = con.execute(
        """SELECT UPPER(sk.kod), rk.miktar_kg
           FROM nexgen_recete_kalem rk
           JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
           WHERE rk.uretim_varyant_id=? AND rk.aktif=1
             AND UPPER(COALESCE(sk.kategori,'')) != 'BOYA'
           ORDER BY sk.kod""",
        (uv_id,),
    ).fetchall()
    return [(r[0], float(r[1]), "KG", "ANA_FORMUL") for r in rows]


def _cekirdek_icerik_esit(
    excel_set: list[tuple[str, float, str, str]],
    db_set: list[tuple[str, float, str, str]],
) -> bool:
    if len(excel_set) != len(db_set):
        return False
    for ex, db in zip(
        sorted(excel_set, key=lambda x: (x[0], x[1])),
        sorted(db_set, key=lambda x: (x[0], x[1])),
    ):
        if ex[0] != db[0] or not _miktar_esit(ex[1], db[1]):
            return False
        if ex[2] != db[2]:
            return False
    return True


def _cekirdek_sunum_tuple_excel(kol) -> tuple[tuple[str, float, int], ...]:
    """Sunum fingerprint — sıra dahil (yalnız uyarı amaçlı)."""
    return tuple(sorted(
        (
            (k.stok_kodu or "").strip().upper(),
            float(k.miktar_kg),
            int(k.sira or 0),
        )
        for k in kol.ana_kalemler
    ))


def _cekirdek_sunum_tuple_db(con: sqlite3.Connection, uv_id: int) -> tuple[tuple[str, float, int], ...]:
    rows = con.execute(
        """SELECT UPPER(sk.kod), rk.miktar_kg, rk.sira
           FROM nexgen_recete_kalem rk
           JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
           WHERE rk.uretim_varyant_id=? AND rk.aktif=1
             AND UPPER(COALESCE(sk.kategori,'')) != 'BOYA'
           ORDER BY sk.kod""",
        (uv_id,),
    ).fetchall()
    return tuple(sorted((r[0], float(r[1]), int(r[2])) for r in rows))


def _cekirdek_icerik_fingerprint(excel_set: list[tuple[str, float, str, str]]) -> str:
    raw = "|".join(f"{k}:{m:.9f}:{b}:{r}" for k, m, b, r in sorted(excel_set, key=lambda x: x[0]))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cekirdek_kalem_karsilastir(
    con: sqlite3.Connection, formul_id: int, kol,
) -> tuple[str, str | None]:
    """
    ('IDEMPOTENT', None|'SIRA_FARKI') veya ('CAKISMA', neden)
    """
    uv_id = _cekirdek_uv_id_bul(con, formul_id, kol.varyant, kol.boyut)
    if uv_id is None:
        return "IDEMPOTENT", None

    excel_icerik = _cekirdek_icerik_set_excel(kol)
    db_icerik = _cekirdek_icerik_set_db(con, uv_id)

    if not _cekirdek_icerik_esit(excel_icerik, db_icerik):
        ex_fp = _cekirdek_icerik_fingerprint(excel_icerik)
        db_fp = _cekirdek_icerik_fingerprint(db_icerik)
        return "CAKISMA", f"icerik_farkli excel_fp={ex_fp} db_fp={db_fp}"

    sunum_ex = _cekirdek_sunum_tuple_excel(kol)
    sunum_db = _cekirdek_sunum_tuple_db(con, uv_id)
    if sunum_ex != sunum_db:
        return "IDEMPOTENT", "SIRA_FARKI"
    return "IDEMPOTENT", None


def _formul_kod_id_map(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT id, kod, ad FROM nexgen_formul WHERE aktif=1"
    ).fetchall()
    return {
        (r[1] or "").strip().upper(): {
            "f_id": r[0], "f_kod": r[1], "f_ad": r[2],
        }
        for r in rows if r[1]
    }


def _finalize_cekirdek(sonuc) -> None:
    yazilabilir = [
        k for k in sonuc.islemler
        if k.aksiyon in CEKIRDEK_GUVENLI_AKSIYONLARI
        and k.safe_to_apply and not k.blocked_dependency
    ]
    sonuc.guvenli_yazma_sayisi = len(yazilabilir)
    sonuc.uygulanabilir_yazma_sayisi = sonuc.guvenli_yazma_sayisi
    sonuc.kismi_import_hazir = (
        sonuc.guvenli_yazma_sayisi > 0
        and not sonuc.schema_identity_eksik
        and not sonuc.blokerler
    )


def simulate_cekirdek_import(
    pkg: ImportPackage,
    db_path: str | None = None,
):
    """Çekirdek dry-run — _formul_parent_coz kullanılmaz."""
    from modules.nexgen.import_engine import (
        DB_PATH,
        SimulasyonKalemi,
        SimulasyonSonucu,
        _stok_id_map_v2,
        db_readonly_connect,
    )

    if not pkg.cekirdek_import or not pkg.cekirdek_kolonlar:
        sonuc = SimulasyonSonucu()
        sonuc.ekle(SimulasyonKalemi(
            aksiyon="GERCEK_BLOCKER",
            tablo="nexgen_formul",
            identity="cekirdek_pkg",
            mesaj="Çekirdek import paketi boş veya cekirdek_import=False",
            bloker_mi=True,
            bloker_nedeni="CEKIRDEK_PAKET_GECERSIZ",
        ))
        return sonuc

    db_path = os.path.abspath(db_path or DB_PATH)
    sonuc = SimulasyonSonucu()
    sonuc.uyarilar.append("CEKIRDEK_IMPORT_MODU=1 (_formul_parent_coz devre dışı)")

    con = db_readonly_connect(db_path)
    try:
        stok_map = _stok_id_map_v2(con)
        formul_kod_map = _formul_kod_id_map(con)
        op_counter = 0

        def _next_op(prefix: str) -> str:
            nonlocal op_counter
            op_counter += 1
            return f"cek_{prefix}_{op_counter:04d}"

        for kol in pkg.cekirdek_kolonlar:
            kod = kol.formul_kod.strip().upper()
            identity = f"cekirdek:{kod}/{kol.sutun_harf}"

            eksik_stok = [
                k.stok_kodu for k in kol.ana_kalemler
                if k.stok_kodu.upper() not in stok_map
            ]
            if eksik_stok:
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="GERCEK_BLOCKER",
                    tablo="nexgen_stok_kart",
                    identity=identity,
                    mesaj=f"Eksik stok kartı: {', '.join(eksik_stok)}",
                    bloker_mi=True,
                    bloker_nedeni="STOK_KARTI_EKSIK",
                    bagli_formul_kod=kod,
                ))
                continue

            db_f = formul_kod_map.get(kod)
            if db_f:
                karar, ek = _cekirdek_kalem_karsilastir(con, db_f["f_id"], kol)
                if karar == "IDEMPOTENT":
                    mesaj = f"Kod {kod} mevcut, içerik aynı — SKIP"
                    if ek == "SIRA_FARKI":
                        sonuc.uyarilar.append(f"SIRA_FARKI_UYARISI: {kod}")
                        mesaj = f"Kod {kod} mevcut, içerik aynı (sıra farkı) — SKIP"
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon="IDEMPOTENT_SKIP_CEKIRDEK",
                        tablo="nexgen_formul",
                        identity=identity,
                        mesaj=mesaj,
                        bagli_formul_kod=kod,
                        safe_to_apply=False,
                    ))
                else:
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon="GERCEK_BLOCKER",
                        tablo="nexgen_formul",
                        identity=identity,
                        mesaj=f"Kod {kod} mevcut fakat içerik farklı ({ek})",
                        bloker_mi=True,
                        bloker_nedeni="CEKIRDEK_ICERIK_CAKISMA",
                        bagli_formul_kod=kod,
                    ))
                continue

            f_op = _next_op("formul")
            rv_op = _next_op("rv")
            uv_op = _next_op("uv")
            kalem_op = _next_op("kalem")
            rv_kod = cekirdek_rv_kodu(kod)

            sonuc.ekle(SimulasyonKalemi(
                aksiyon="INSERT_FORMUL_CEKIRDEK",
                tablo="nexgen_formul",
                identity=identity,
                yeni_deger={
                    "kod": kod,
                    "ad": kol.formul_ad,
                    "urun_ailesi": kol.urun_ailesi,
                    "durum": kol.durum or "TASLAK",
                },
                mesaj=f"Yeni çekirdek formül: nexgen_formul.kod={kod}",
                op_id=f_op,
                bagli_formul_kod=kod,
                kaynak_hucre=f"TUM_FORMULLER!{kol.sutun_harf}4",
            ))

            sonuc.ekle(SimulasyonKalemi(
                aksiyon="INSERT_RV_CEKIRDEK",
                tablo="nexgen_renk_varyant",
                identity=f"{kod}/rv",
                yeni_deger={
                    "formul_kod": kod,
                    "kod": rv_kod,
                    "ad": kol.varyant or kol.formul_ad,
                    "renk": kol.varyant or "",
                },
                mesaj=f"Yeni RV: {rv_kod}",
                op_id=rv_op,
                parent_op_id=f_op,
                bagli_formul_kod=kod,
            ))

            sonuc.ekle(SimulasyonKalemi(
                aksiyon="INSERT_UV_CEKIRDEK",
                tablo="nexgen_uretim_varyant",
                identity=f"{kod}/{kol.boyut}",
                yeni_deger={
                    "boyut": kol.boyut,
                    "ad": cekirdek_uv_ad(kod, kol.boyut),
                    "recete_durum": "URETIME_ACIK" if kol.durum == "URETIME_ACIK" else "AKTIF",
                },
                mesaj=f"Yeni UV: {kod} boyut={kol.boyut}",
                op_id=uv_op,
                parent_op_id=rv_op,
                bagli_formul_kod=kod,
            ))

            if kol.ana_kalemler:
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="INSERT_ANA_KALEM_CEKIRDEK",
                    tablo="nexgen_recete_kalem",
                    identity=f"{kod}/kalem",
                    yeni_deger=[
                        {"stok_kodu": k.stok_kodu, "miktar_kg": k.miktar_kg, "sira": k.sira}
                        for k in kol.ana_kalemler
                    ],
                    mesaj=f"Ana kalemler: {kod} — {len(kol.ana_kalemler)} KG kalem",
                    op_id=kalem_op,
                    parent_op_id=uv_op,
                    bagli_formul_kod=kod,
                ))
    finally:
        con.close()

    _finalize_cekirdek(sonuc)
    return sonuc


def _cekirdek_apply_ops(sim) -> list:
    return [
        k for k in sim.islemler
        if k.aksiyon in CEKIRDEK_GUVENLI_AKSIYONLARI
        and k.aksiyon != "IDEMPOTENT_SKIP_CEKIRDEK"
        and k.safe_to_apply
        and not k.blocked_dependency
    ]


def partial_apply_cekirdek_import(
    pkg: ImportPackage,
    db_path: str | None = None,
    yedek_dizin: str | None = None,
    sim=None,
):
    """
    Çekirdek kısmi apply — tek transaction, standart parent import yoluna girmez.
    Yalnız simulate_cekirdek_import INSERT_* operasyonlarını yazar.
    """
    from datetime import datetime
    from modules.nexgen.import_engine import (
        DB_PATH,
        ImportSonucu,
        _insert_ana_kalemler,
        _sha256,
        _stok_id_map_v2,
        db_yedek_al,
        normalize_ascii_import,
    )

    db_path = os.path.abspath(db_path or DB_PATH)
    sonuc = ImportSonucu(partial_mode=True)

    if sim is None:
        sim = simulate_cekirdek_import(pkg, db_path=db_path)

    if sim.blokerler:
        sonuc.hatalar.append(f"Blokerler mevcut: {sim.blokerler}")
        return sonuc
    if not sim.kismi_import_hazir:
        sonuc.hatalar.append("Çekirdek import hazır değil (guvenli_yazma=0)")
        return sonuc

    ops = _cekirdek_apply_ops(sim)
    if not ops:
        sonuc.hatalar.append("Uygulanacak çekirdek operasyon yok")
        return sonuc

    yedek_dizin = yedek_dizin or os.path.abspath(
        os.path.join(os.path.dirname(db_path), "..", "backup")
    )
    try:
        os.makedirs(yedek_dizin, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sha_once = _sha256(db_path)
        yedek_hedef = os.path.join(
            yedek_dizin, f"mock_data_pre_cekirdek_apply1_{ts}.db"
        )
        import shutil
        shutil.copy2(db_path, yedek_hedef)
        if _sha256(yedek_hedef) != sha_once:
            raise RuntimeError("Yedek bütünlük hatası")
        sonuc.yedek_yolu = yedek_hedef
        sonuc.sha_once = sha_once
    except Exception as e:
        sonuc.hatalar.append(f"Yedek alınamadı: {e}")
        return sonuc

    formul_id_by_op: dict[str, int] = {}
    rv_id_by_op: dict[str, int] = {}
    uv_id_by_op: dict[str, int] = {}
    formul_id_by_kod: dict[str, int] = {}

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    t0 = datetime.now()
    try:
        con.execute("BEGIN IMMEDIATE")
        stok_map = _stok_id_map_v2(con)

        for op in ops:
            if op.aksiyon == "INSERT_FORMUL_CEKIRDEK":
                vd = op.yeni_deger or {}
                kod = (vd.get("kod") or "").strip().upper()
                if not kod:
                    raise ValueError("INSERT_FORMUL_CEKIRDEK: kod boş")
                mevcut = con.execute(
                    "SELECT id FROM nexgen_formul WHERE UPPER(kod)=? AND aktif=1",
                    (kod,),
                ).fetchone()
                if mevcut:
                    raise ValueError(
                        f"Formül kodu zaten mevcut (UPDATE yasak): {kod} id={mevcut[0]}"
                    )
                con.execute(
                    """INSERT INTO nexgen_formul
                       (kod, ad, urun_ailesi, durum, onay_durumu, aktif, olusturan_id)
                       VALUES (?, ?, ?, ?, 'BEKLIYOR', 1, 1)""",
                    (
                        kod,
                        vd.get("ad") or kod,
                        vd.get("urun_ailesi") or "",
                        vd.get("durum") or "TASLAK",
                    ),
                )
                fid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                formul_id_by_op[op.op_id] = fid
                formul_id_by_kod[kod] = fid
                sonuc.ozet["INSERT_FORMUL_CEKIRDEK"] = (
                    sonuc.ozet.get("INSERT_FORMUL_CEKIRDEK", 0) + 1
                )

            elif op.aksiyon == "INSERT_RV_CEKIRDEK":
                vd = op.yeni_deger or {}
                kod = (vd.get("formul_kod") or op.bagli_formul_kod or "").strip().upper()
                fid = formul_id_by_op.get(op.parent_op_id) or formul_id_by_kod.get(kod)
                if not fid:
                    raise ValueError(f"INSERT_RV_CEKIRDEK: formül çözülemedi ({kod})")
                rv_kod = (vd.get("kod") or cekirdek_rv_kodu(kod)).strip().upper()
                rv_ad = vd.get("ad") or vd.get("renk") or kod
                rv_renk = vd.get("renk") or ""
                dup = con.execute(
                    "SELECT id FROM nexgen_renk_varyant WHERE formul_id=? AND UPPER(kod)=? AND aktif=1",
                    (fid, rv_kod),
                ).fetchone()
                if dup:
                    raise ValueError(f"RV zaten mevcut: {rv_kod}")
                con.execute(
                    """INSERT INTO nexgen_renk_varyant
                       (formul_id, kod, ad, renk, aktif)
                       VALUES (?, ?, ?, ?, 1)""",
                    (fid, rv_kod, rv_ad, rv_renk),
                )
                rv_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                rv_id_by_op[op.op_id] = rv_id
                sonuc.ozet["INSERT_RV_CEKIRDEK"] = (
                    sonuc.ozet.get("INSERT_RV_CEKIRDEK", 0) + 1
                )

            elif op.aksiyon == "INSERT_UV_CEKIRDEK":
                vd = op.yeni_deger or {}
                rv_id = rv_id_by_op.get(op.parent_op_id)
                if not rv_id:
                    raise ValueError(f"INSERT_UV_CEKIRDEK: RV çözülemedi ({op.identity})")
                boyut = (vd.get("boyut") or "STANDART").strip().upper()
                uv_ad = vd.get("ad") or cekirdek_uv_ad(
                    op.bagli_formul_kod or "", boyut
                )
                recete_durum = vd.get("recete_durum") or "AKTIF"
                dup = con.execute(
                    """SELECT id FROM nexgen_uretim_varyant
                       WHERE renk_varyant_id=? AND boyut=? AND aktif=1""",
                    (rv_id, boyut),
                ).fetchone()
                if dup:
                    raise ValueError(f"UV zaten mevcut: rv={rv_id} boyut={boyut}")
                con.execute(
                    """INSERT INTO nexgen_uretim_varyant
                       (renk_varyant_id, boyut, ad, recete_durum, aktif)
                       VALUES (?, ?, ?, ?, 1)""",
                    (rv_id, boyut, uv_ad, recete_durum),
                )
                uv_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                uv_id_by_op[op.op_id] = uv_id
                sonuc.ozet["INSERT_UV_CEKIRDEK"] = (
                    sonuc.ozet.get("INSERT_UV_CEKIRDEK", 0) + 1
                )

            elif op.aksiyon == "INSERT_ANA_KALEM_CEKIRDEK":
                uv_id = uv_id_by_op.get(op.parent_op_id)
                if not uv_id:
                    raise ValueError(
                        f"INSERT_ANA_KALEM_CEKIRDEK: UV çözülemedi ({op.identity})"
                    )
                mevcut = con.execute(
                    """SELECT COUNT(*) FROM nexgen_recete_kalem
                       WHERE uretim_varyant_id=? AND aktif=1
                         AND stok_kart_id IN (
                           SELECT id FROM nexgen_stok_kart
                           WHERE UPPER(COALESCE(kategori,'')) != 'BOYA'
                         )""",
                    (uv_id,),
                ).fetchone()[0]
                if mevcut > 0:
                    raise ValueError(
                        f"UV {uv_id} zaten ana kalem içeriyor — partial apply yasak"
                    )
                kalemler = op.yeni_deger or []
                n = _insert_ana_kalemler(con, uv_id, kalemler, stok_map)
                sonuc.ozet["INSERT_ANA_KALEM_CEKIRDEK"] = (
                    sonuc.ozet.get("INSERT_ANA_KALEM_CEKIRDEK", 0) + n
                )

        con.execute("COMMIT")
        sonuc.basarili = True
        sonuc.sha_sonra = _sha256(db_path)
    except Exception as e:
        con.execute("ROLLBACK")
        sonuc.rollback_yapildi = True
        sonuc.hatalar.append(str(e))
        sonuc.sha_sonra = _sha256(db_path)
    finally:
        con.close()
        sonuc.elapsed_ms = (datetime.now() - t0).total_seconds() * 1000

    return sonuc
