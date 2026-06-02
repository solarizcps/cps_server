# -*- coding: utf-8 -*-
"""ENJ_SETUP_V1 — slot bazli setup CRUD (enj_ab_setup)."""

from datetime import datetime

_SETUP_COLS = (
    "id", "rapor_id", "makine_id", "slot",
    "kalip_id", "kalip_kod_snapshot", "model_kod_snapshot",
    "renk", "pisme_suresi_sn", "personel_sayisi",
    "aktif_goz_sayisi", "kalip_basi_cift",
    "durum", "baslangic_zamani", "bitis_zamani",
    "degisim_sebebi", "notlar",
    "created_by", "created_at", "updated_at",
)

_TASLAK_PATCH = frozenset({
    "kalip_id", "renk", "pisme_suresi_sn", "personel_sayisi",
    "aktif_goz_sayisi", "kalip_basi_cift", "notlar",
})


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row):
    if not row:
        return None
    return dict(zip(_SETUP_COLS, row))


def _fetch_setup(cur, setup_id, rapor_id=None):
    sql = "SELECT " + ", ".join(_SETUP_COLS) + " FROM enj_ab_setup WHERE id=?"
    params = [setup_id]
    if rapor_id is not None:
        sql += " AND rapor_id=?"
        params.append(rapor_id)
    cur.execute(sql, params)
    return _row_to_dict(cur.fetchone())


def _rapor_makine(cur, rapor_id):
    cur.execute(
        "SELECT makine_id, kullanici_id FROM enj_gunluk_rapor WHERE id=?",
        (rapor_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"makine_id": row[0], "kullanici_id": row[1]}


def _kalip_snapshot(cur, kalip_id):
    if not kalip_id:
        return None, None, None
    cur.execute(
        "SELECT kalip_kod, model_kod, kalip_basi_cift FROM enj_kalip WHERE id=?",
        (kalip_id,),
    )
    row = cur.fetchone()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]


def _aktif_goz_canli(cur, rapor_id, slot):
    cur.execute(
        "SELECT COUNT(*) FROM enj_istasyon_durumu "
        "WHERE rapor_id=? AND slot=? AND aktif=1",
        (rapor_id, slot),
    )
    return int(cur.fetchone()[0] or 0)


def validate_setup(data, for_approve=False):
    """for_approve=True ise zorunlu alanlar kontrol edilir."""
    err = []
    if not for_approve:
        slot = (data.get("slot") or "").upper()
        if slot not in ("A", "B"):
            err.append("slot A veya B olmali")
        return err

    if not data.get("kalip_id"):
        err.append("kalip_id zorunlu")
    renk = data.get("renk")
    if renk is None or str(renk).strip() == "":
        err.append("renk zorunlu")
    ps = data.get("pisme_suresi_sn")
    if ps is None or int(ps or 0) <= 0:
        err.append("pisme_suresi_sn zorunlu (>0)")
    pe = data.get("personel_sayisi")
    if pe is None or int(pe or 0) <= 0:
        err.append("personel_sayisi zorunlu (>0)")
    ag = data.get("aktif_goz_sayisi")
    if ag is None or int(ag or 0) <= 0:
        err.append("aktif_goz_sayisi zorunlu (>0)")
    kbc = data.get("kalip_basi_cift")
    if kbc is None or int(kbc or 0) <= 0:
        err.append("kalip_basi_cift zorunlu (>0)")
    return err


def get_active_setup(cur, rapor_id, slot):
    slot = (slot or "").upper()
    cur.execute(
        "SELECT " + ", ".join(_SETUP_COLS) + " "
        "FROM enj_ab_setup WHERE rapor_id=? AND slot=? AND durum='AKTIF'",
        (rapor_id, slot),
    )
    return _row_to_dict(cur.fetchone())


def list_setups(cur, rapor_id, slot=None, durum=None):
    sql = "SELECT " + ", ".join(_SETUP_COLS) + " FROM enj_ab_setup WHERE rapor_id=?"
    params = [rapor_id]
    if slot:
        sql += " AND slot=?"
        params.append(slot.upper())
    if durum:
        sql += " AND durum=?"
        params.append(durum.upper())
    sql += " ORDER BY id DESC"
    cur.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def create_setup(con, rapor_id, data, user=None):
    cur = con.cursor()
    err = validate_setup(data, for_approve=False)
    if err:
        return {"ok": False, "hata": "; ".join(err)}

    rp = _rapor_makine(cur, rapor_id)
    if not rp:
        return {"ok": False, "hata": "rapor bulunamadi"}

    slot = data["slot"].upper()
    kalip_id = data.get("kalip_id")
    kk, mk, kbc_m = _kalip_snapshot(cur, kalip_id) if kalip_id else (None, None, None)
    kbc = data.get("kalip_basi_cift")
    if kbc is None and kbc_m is not None:
        kbc = kbc_m
    aktif = data.get("aktif_goz_sayisi")
    if aktif is None:
        aktif = _aktif_goz_canli(cur, rapor_id, slot)

    uid = (user or {}).get("id")
    now = _now()
    cur.execute(
        """
        INSERT INTO enj_ab_setup (
            rapor_id, makine_id, slot,
            kalip_id, kalip_kod_snapshot, model_kod_snapshot,
            renk, pisme_suresi_sn, personel_sayisi,
            aktif_goz_sayisi, kalip_basi_cift,
            durum, notlar, created_by, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            rapor_id, rp["makine_id"], slot,
            kalip_id, kk, mk,
            data.get("renk"), data.get("pisme_suresi_sn"),
            data.get("personel_sayisi"), int(aktif or 0), kbc,
            "TASLAK", data.get("notlar"), uid, now, now,
        ),
    )
    setup_id = cur.lastrowid
    row = _fetch_setup(cur, setup_id)

    try:
        from modules.enjeksiyon.audit import log_ab_setup_event
        log_ab_setup_event(
            con, rapor_id, "SETUP_CREATED", setup_id=setup_id,
            meta_extra={"slot": slot, "setup": row},
        )
    except Exception:
        pass

    return {"ok": True, "setup": row}


def update_setup(con, setup_id, rapor_id, data):
    cur = con.cursor()
    row = _fetch_setup(cur, setup_id, rapor_id)
    if not row:
        return {"ok": False, "hata": "setup bulunamadi"}
    if row["durum"] != "TASLAK":
        return {"ok": False, "hata": "sadece TASLAK setup guncellenebilir"}

    guncel = {k: data[k] for k in _TASLAK_PATCH if k in data}
    if not guncel:
        return {"ok": False, "hata": "guncellenecek alan yok"}

    if "kalip_id" in guncel and guncel["kalip_id"]:
        kk, mk, kbc_m = _kalip_snapshot(cur, guncel["kalip_id"])
        guncel["kalip_kod_snapshot"] = kk
        guncel["model_kod_snapshot"] = mk
        if "kalip_basi_cift" not in guncel and kbc_m is not None:
            guncel["kalip_basi_cift"] = kbc_m

    parts = [k + "=?" for k in guncel.keys()]
    parts.append("updated_at=?")
    params = list(guncel.values()) + [_now(), setup_id, rapor_id]
    cur.execute(
        "UPDATE enj_ab_setup SET " + ", ".join(parts) + " WHERE id=? AND rapor_id=?",
        params,
    )
    return {"ok": True, "setup": _fetch_setup(cur, setup_id, rapor_id)}


def approve_setup(con, setup_id, rapor_id, user=None):
    cur = con.cursor()
    row = _fetch_setup(cur, setup_id, rapor_id)
    if not row:
        return {"ok": False, "hata": "setup bulunamadi"}
    if row["durum"] != "TASLAK":
        return {"ok": False, "hata": "sadece TASLAK onaylanabilir"}

    merged = dict(row)
    if merged.get("aktif_goz_sayisi", 0) <= 0:
        merged["aktif_goz_sayisi"] = _aktif_goz_canli(
            cur, rapor_id, merged["slot"]
        )
    if merged.get("kalip_id") and not merged.get("kalip_basi_cift"):
        _, _, kbc_m = _kalip_snapshot(cur, merged["kalip_id"])
        if kbc_m is not None:
            merged["kalip_basi_cift"] = kbc_m
    if merged.get("personel_sayisi") is None:
        cur.execute(
            "SELECT personel_sayisi FROM enj_gunluk_rapor WHERE id=?",
            (rapor_id,),
        )
        pr = cur.fetchone()
        if pr and pr[0] is not None:
            merged["personel_sayisi"] = pr[0]

    err = validate_setup(merged, for_approve=True)
    if err:
        return {"ok": False, "hata": "; ".join(err)}

    existing = get_active_setup(cur, rapor_id, merged["slot"])
    if existing and existing["id"] != setup_id:
        return {
            "ok": False,
            "hata": "Bu slotta zaten AKTIF setup var (id=%s)" % existing["id"],
        }

    now = _now()
    cur.execute(
        """
        UPDATE enj_ab_setup SET
            durum='AKTIF',
            baslangic_zamani=?,
            aktif_goz_sayisi=?,
            kalip_basi_cift=?,
            personel_sayisi=?,
            updated_at=?
        WHERE id=? AND rapor_id=?
        """,
        (
            now,
            merged["aktif_goz_sayisi"],
            merged["kalip_basi_cift"],
            merged["personel_sayisi"],
            now,
            setup_id,
            rapor_id,
        ),
    )
    row = _fetch_setup(cur, setup_id, rapor_id)

    try:
        from modules.enjeksiyon.audit import log_ab_setup_event
        log_ab_setup_event(
            con, rapor_id, "SETUP_APPROVED", setup_id=setup_id,
            meta_extra={"slot": row["slot"], "setup": row},
        )
    except Exception:
        pass

    return {"ok": True, "setup": row}


def close_setup(con, setup_id, rapor_id, degisim_sebebi, user=None, notlar=None):
    cur = con.cursor()
    row = _fetch_setup(cur, setup_id, rapor_id)
    if not row:
        return {"ok": False, "hata": "setup bulunamadi"}
    if row["durum"] != "AKTIF":
        return {"ok": False, "hata": "sadece AKTIF setup kapatilabilir"}
    if not degisim_sebebi or not str(degisim_sebebi).strip():
        return {"ok": False, "hata": "degisim_sebebi zorunlu"}

    now = _now()
    cur.execute(
        """
        UPDATE enj_ab_setup SET
            durum='KAPANDI',
            bitis_zamani=?,
            degisim_sebebi=?,
            notlar=COALESCE(?, notlar),
            updated_at=?
        WHERE id=? AND rapor_id=?
        """,
        (now, str(degisim_sebebi).strip(), notlar, now, setup_id, rapor_id),
    )
    row = _fetch_setup(cur, setup_id, rapor_id)

    try:
        from modules.enjeksiyon.audit import log_ab_setup_event
        log_ab_setup_event(
            con, rapor_id, "SETUP_CLOSED", setup_id=setup_id,
            meta_extra={
                "slot": row["slot"],
                "degisim_sebebi": degisim_sebebi,
                "setup": row,
            },
        )
    except Exception:
        pass

    return {"ok": True, "setup": row}


def cancel_setup(con, setup_id, rapor_id, user=None):
    cur = con.cursor()
    row = _fetch_setup(cur, setup_id, rapor_id)
    if not row:
        return {"ok": False, "hata": "setup bulunamadi"}
    if row["durum"] != "TASLAK":
        return {"ok": False, "hata": "sadece TASLAK iptal edilebilir"}

    now = _now()
    cur.execute(
        """
        UPDATE enj_ab_setup SET durum='IPTAL', bitis_zamani=?, updated_at=?
        WHERE id=? AND rapor_id=?
        """,
        (now, now, setup_id, rapor_id),
    )
    return {"ok": True, "setup": _fetch_setup(cur, setup_id, rapor_id)}
