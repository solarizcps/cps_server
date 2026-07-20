# -*- coding: utf-8 -*-
"""
FAZ-ALI-KULLANICI-YETKI-VE-SERVER-HAZIRLIK-1

NexGen Üretim Operatörü rolü + kullanıcı (idempotent).

Örnek:
  python app/tools/nexgen_create_operator_user.py --username ali --password "<GEÇİCİ>"
  python app/tools/nexgen_create_operator_user.py --username ali --password "<GEÇİCİ>" --db app/mock_data.db

Kurallar:
  - Şifre CLI ile alınır; loglanmaz, dosyaya yazılmaz.
  - sistem_kullanici.Sifre mevcut login ile uyumlu saklanır (düz metin — auth.login_kullanici).
  - İkinci çalıştırmada duplicate kullanıcı oluşturmaz; rol/yetki doğrular.
  - Başka kullanıcılara dokunmaz.
  - Yalnız MOCK DB varsayılan; --db ile yol verilir. prod/live için ayrı onay gerekir.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

ROL_AD = "NexGen Üretim Operatörü"
ROL_AD_ASCII = "NexGen Uretim Operatoru"
ROL_ACIK = "NexGen tablet üretim operatörü. Sipariş/üretim görüntüleme, Başlat/Beklet/Devam/Bitir, formül görünümü, barkod/etiket. AR-GE ve yönetim yok."
ROL_RENK = "#0f766e"
ROL_ID_TERCIH = 43

# Minimal yetkiler — AR-GE (recete.*) ve yönetim VERİLMEZ
YETKI_ATAMALARI = (
    # kod, Gorebilir, Duzenleyebilir, can_view, can_create, can_update, can_delete, can_approve, can_report, can_manage
    ("nexgen.tablet.view", 1, 0, 1, 0, 0, 0, 0, 0, 0),
    ("nexgen.tablet.uretim", 1, 1, 1, 0, 1, 0, 0, 0, 0),
)


def _default_db():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "mock_data.db"))


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise SystemExit(f"[op-user] HATA: DB yok: {db_path}")
    # Güvenlik: dosya adında live/prod uyarısı
    low = db_path.replace("\\", "/").lower()
    if "live" in os.path.basename(low) or "prod" in os.path.basename(low):
        raise SystemExit(
            "[op-user] RED: live/prod DB yolu algılandı. Bu araç varsayılan olarak MOCK içindir."
        )
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_rol(cur, con, simdi: str) -> int:
    mevcut = cur.execute(
        "SELECT Id, Ad FROM sistem_rol WHERE Ad IN (?, ?) ORDER BY Id LIMIT 1",
        (ROL_AD, ROL_AD_ASCII),
    ).fetchone()
    if mevcut:
        _safe_print(f"[op-user] Rol mevcut Id={mevcut['Id']} Ad={mevcut['Ad']}")
        return int(mevcut["Id"])

    preferred_free = cur.execute(
        "SELECT Id FROM sistem_rol WHERE Id=?", (ROL_ID_TERCIH,)
    ).fetchone()
    if preferred_free is None:
        rol_id = ROL_ID_TERCIH
        cur.execute(
            """
            INSERT INTO sistem_rol
                (Id, Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici)
            VALUES (?, ?, ?, ?, 1, 0, ?, 'nexgen_create_operator_user')
            """,
            (rol_id, ROL_AD, ROL_ACIK, ROL_RENK, simdi),
        )
    else:
        cur.execute(
            """
            INSERT INTO sistem_rol
                (Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici)
            VALUES (?, ?, ?, 1, 0, ?, 'nexgen_create_operator_user')
            """,
            (ROL_AD, ROL_ACIK, ROL_RENK, simdi),
        )
        rol_id = int(cur.lastrowid)
    con.commit()
    _safe_print(f"[op-user] Rol olusturuldu Id={rol_id} Ad={ROL_AD}")
    return rol_id


def _ensure_yetkiler(cur, con, rol_id: int) -> int:
    atanan = 0
    for (
        kod,
        gor,
        duz,
        cv,
        cc,
        cu,
        cd,
        ca,
        cr,
        cm,
    ) in YETKI_ATAMALARI:
        y = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not y:
            _safe_print(f"[op-user] UYARI: yetki yok, atlandi: {kod}")
            continue
        yid = int(y["Id"])
        mev = cur.execute(
            "SELECT Id, can_view, can_update, Gorebilir, Duzenleyebilir "
            "FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (rol_id, yid),
        ).fetchone()
        if mev:
            # Minimal bayrakları güçlendir; fazla yetki açma (can_create vb. kapatma)
            cur.execute(
                """
                UPDATE sistem_rol_yetki SET
                    Gorebilir=?, Duzenleyebilir=?,
                    can_view=?, can_create=?, can_update=?, can_delete=?,
                    can_approve=?, can_report=?, can_manage=?
                WHERE Id=?
                """,
                (gor, duz, cv, cc, cu, cd, ca, cr, cm, mev["Id"]),
            )
            atanan += 1
            _safe_print(f"[op-user] Yetki guncellendi: {kod}")
        else:
            cur.execute(
                """
                INSERT INTO sistem_rol_yetki
                    (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                     can_view, can_create, can_update, can_delete,
                     can_approve, can_report, can_manage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rol_id, yid, gor, duz, cv, cc, cu, cd, ca, cr, cm),
            )
            atanan += 1
            _safe_print(f"[op-user] Yetki atandi: {kod}")
    if atanan:
        con.commit()
    return atanan


def _ensure_user(cur, con, username: str, password: str, ad_soyad: str, rol_id: int, simdi: str):
    username = username.strip().lower()
    mev = cur.execute(
        "SELECT Id, RolId, Aktif, Tip FROM sistem_kullanici WHERE lower(KullaniciAdi)=?",
        (username,),
    ).fetchone()
    if mev:
        # Mevcut kullanıcı: rol/aktif doğrula; şifreyi yalnız --reset-password ile değiştir
        updates = []
        params = []
        if int(mev["RolId"] or 0) != int(rol_id):
            updates.append("RolId=?")
            params.append(rol_id)
            updates.append("Rol=?")
            params.append(ROL_AD)
            _safe_print(f"[op-user] Kullanici mevcut Id={mev['Id']} — RolId {mev['RolId']} -> {rol_id}")
        if int(mev["Aktif"] or 0) != 1:
            updates.append("Aktif=1")
            _safe_print(f"[op-user] Kullanici aktiflestirildi Id={mev['Id']}")
        tip = (mev["Tip"] or "sistem").strip()
        if tip != "sistem":
            updates.append("Tip=?")
            params.append("sistem")
        if updates:
            params.append(mev["Id"])
            cur.execute(
                f"UPDATE sistem_kullanici SET {', '.join(updates)} WHERE Id=?",
                params,
            )
            con.commit()
        else:
            _safe_print(f"[op-user] Kullanici zaten uygun Id={mev['Id']} — degisiklik yok")
        return int(mev["Id"]), False

    cur.execute(
        """
        INSERT INTO sistem_kullanici
            (KullaniciAdi, AdSoyad, Email, Sifre, RolId, Rol,
             Aktif, ZorunluSifreDegistir, OlusturmaTarih, OlusturanKullanici, Tip)
        VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, 'nexgen_create_operator_user', 'sistem')
        """,
        (
            username,
            ad_soyad,
            f"{username}@solariz.local",
            password,
            rol_id,
            ROL_AD,
            simdi,
        ),
    )
    con.commit()
    uid = int(cur.lastrowid)
    _safe_print(f"[op-user] Kullanici olusturuldu Id={uid} username={username}")
    return uid, True


def _reset_password(cur, con, username: str, password: str):
    username = username.strip().lower()
    mev = cur.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi)=?",
        (username,),
    ).fetchone()
    if not mev:
        raise SystemExit(f"[op-user] HATA: kullanici yok: {username}")
    cur.execute(
        "UPDATE sistem_kullanici SET Sifre=?, ZorunluSifreDegistir=1 WHERE Id=?",
        (password, mev["Id"]),
    )
    con.commit()
    _safe_print(f"[op-user] Sifre guncellendi (deger loglanmaz) Id={mev['Id']}")


def _rapor_yetkiler(cur, rol_id: int):
    rows = cur.execute(
        """
        SELECT y.Kod, ry.can_view, ry.can_update, ry.can_manage, ry.Gorebilir, ry.Duzenleyebilir
        FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE ry.RolId=?
        ORDER BY y.Kod
        """,
        (rol_id,),
    ).fetchall()
    _safe_print(f"[op-user] Rol {rol_id} yetki sayisi={len(rows)}")
    for r in rows:
        _safe_print(
            f"  - {r['Kod']} view={r['can_view']} update={r['can_update']} "
            f"manage={r['can_manage']} gor={r['Gorebilir']} duz={r['Duzenleyebilir']}"
        )


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NexGen uretim operatoru kullanici/rol")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True, help="Geçici şifre (loglanmaz)")
    ap.add_argument("--ad-soyad", default="Ali (Üretim Operatörü)")
    ap.add_argument("--db", default=_default_db())
    ap.add_argument(
        "--reset-password",
        action="store_true",
        help="Kullanıcı varsa şifreyi de güncelle",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.password or len(args.password) < 4:
        print("[op-user] HATA: şifre en az 4 karakter olmalı")
        return 2

    db_path = os.path.abspath(args.db)
    _safe_print(f"[op-user] DB={db_path}")
    _safe_print(f"[op-user] username={args.username.strip().lower()}")

    if args.dry_run:
        _safe_print("[op-user] DRY-RUN — yazma yok")
        return 0

    con = _connect(db_path)
    cur = con.cursor()
    simdi = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        rol_id = _ensure_rol(cur, con, simdi)
        _ensure_yetkiler(cur, con, rol_id)
        uid, created = _ensure_user(
            cur, con, args.username, args.password, args.ad_soyad, rol_id, simdi
        )
        if args.reset_password and not created:
            _reset_password(cur, con, args.username, args.password)
        _rapor_yetkiler(cur, rol_id)
        _safe_print(f"[op-user] OK user_id={uid} rol_id={rol_id} created={created}")
        _safe_print("[op-user] Sifre loglanmadi.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
