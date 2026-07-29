# -*- coding: utf-8 -*-
"""
Cari sorumluluk + pazarlamacı kapsam servisi.

FAZ-CARI-SORUMLU-VE-PAZARLAMACI-KAPSAMI-F1C
- Fiziksel silme yok (pasife al)
- Otomatik atama yok
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from modules.nexgen.cari360_yetki import (
    YETKI_CARI360_FINANS_VIEW,
    YETKI_CARI360_FINANS_WRITE,
    YETKI_CARI360_SORUMLU_MANAGE,
    YETKI_CARI360_VIEW,
    YETKI_CARI360_VIEW_OWN,
    _yk_has,
    can_cari360_crm_write,
    can_cari360_finans_view,
    can_cari360_finans_write,
    can_cari360_view_all,
    can_cari360_view_own,
    can_physical_delete,
    can_siparis_onaya_gonder,
)

SORUMLULUK_ROLLERI = ('ANA', 'YEDEK', 'YONETICI', 'DESTEK')

_AKTIF_WHERE = (
    "aktif=1 AND (bitis_tarihi IS NULL OR bitis_tarihi='' "
    "OR bitis_tarihi > datetime('now','localtime'))"
)


def _now() -> str:
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.date.today().isoformat()


def load_kullanici_yetkileri(con, kullanici_id: int) -> set[str]:
    """DB'den kullanıcı yetki seti (rol + override)."""
    row = con.execute(
        'SELECT Id, KullaniciAdi, RolId FROM sistem_kullanici WHERE Id=? AND Aktif=1',
        (kullanici_id,),
    ).fetchone()
    if not row:
        return set()
    if (row['KullaniciAdi'] or '').lower() == 'admin':
        return {'*'}
    yk: set[str] = set()
    rol_id = row['RolId']
    if rol_id:
        for r in con.execute(
            """
            SELECT y.Kod, ry.can_view, ry.can_create, ry.can_update, ry.can_delete,
                   ry.can_approve, ry.can_report, ry.can_manage
            FROM sistem_rol_yetki ry
            JOIN sistem_yetki y ON y.Id = ry.YetkiId
            WHERE ry.RolId=?
            """,
            (rol_id,),
        ):
            kod = r['Kod']
            for action in ('can_view', 'can_create', 'can_update', 'can_delete',
                           'can_approve', 'can_report', 'can_manage'):
                if int(r[action] or 0):
                    yk.add(f'{kod}:{action}')
    for r in con.execute(
        """
        SELECT y.Kod, upo.can_view, upo.can_create, upo.can_update, upo.can_delete,
               upo.can_approve, upo.can_report, upo.can_manage
        FROM user_permission_override upo
        JOIN sistem_yetki y ON y.Id = upo.YetkiId
        WHERE upo.KullaniciId=?
        """,
        (kullanici_id,),
    ):
        kod = r['Kod']
        for action in ('can_view', 'can_create', 'can_update', 'can_delete',
                       'can_approve', 'can_report', 'can_manage'):
            if int(r[action] or 0):
                yk.add(f'{kod}:{action}')
    return yk


def _all_cari_ids(con) -> list[int]:
    return [int(r[0]) for r in con.execute(
        'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id'
    ).fetchall()]


def get_kullanici_cari_kapsami(
    con,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)

    tumunu = (
        can_cari360_view_all(yk)
        or _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage')
        or _yk_has(yk, YETKI_CARI360_VIEW, 'can_manage')
    )

    ana: list[int] = []
    yedek: list[int] = []
    destek: list[int] = []
    yonetici: list[int] = []

    if not tumunu:
        rows = con.execute(
            f"""
            SELECT cs.cari_id, cs.sorumluluk_rolu
            FROM cari_sorumlu cs
            WHERE cs.kullanici_id=? AND {_AKTIF_WHERE}
            """,
            (kullanici_id,),
        ).fetchall()
        for r in rows:
            cid = int(r['cari_id'])
            rol = (r['sorumluluk_rolu'] or '').upper()
            if rol == 'ANA':
                ana.append(cid)
            elif rol == 'YEDEK':
                yedek.append(cid)
            elif rol == 'DESTEK':
                destek.append(cid)
            elif rol == 'YONETICI':
                yonetici.append(cid)

    if tumunu:
        cari_ids = _all_cari_ids(con)
    else:
        cari_ids = sorted(set(ana + yedek + destek + yonetici))

    return {
        'kullanici_id': kullanici_id,
        'ana_cariler': ana,
        'yedek_cariler': yedek,
        'destek_cariler': destek,
        'yonetici_olarak_gorebildikleri': yonetici,
        'tumunu_gorebilir_mi': tumunu,
        'cari_id_listesi': cari_ids,
    }


def _kullanici_cari_atanmis(con, kullanici_id: int, cari_id: int) -> bool:
    row = con.execute(
        f"""
        SELECT 1 FROM cari_sorumlu
        WHERE kullanici_id=? AND cari_id=? AND sorumluluk_rolu IN ('ANA','YEDEK','DESTEK')
          AND {_AKTIF_WHERE}
        """,
        (kullanici_id, cari_id),
    ).fetchone()
    return bool(row)


def can_view_cari(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if can_cari360_view_all(yk):
        return True
    kapsam = get_kullanici_cari_kapsami(con, kullanici_id, yk)
    if kapsam['tumunu_gorebilir_mi']:
        return True
    return cari_id in kapsam['cari_id_listesi']


def can_view_cari_ticari(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    """
    T4 — fiyat / iskonto / vade / tutar görünümü.
    Yeni DB yetkisi yok; mevcut helper birleşimi:
    A) admin / view_all / *
    B) view_own + cari kapsamında (atanmış)
    C) finans.view + cari görüntüleyebilir
    D) sorumlu_manage (yönetim kapsamı)
    """
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        return False
    if '*' in yk or can_cari360_view_all(yk):
        return True
    if _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage'):
        return True
    if can_cari360_finans_view(yk):
        return True
    if can_cari360_view_own(yk):
        kapsam = get_kullanici_cari_kapsami(con, kullanici_id, yk)
        if int(cari_id) in set(kapsam.get('cari_id_listesi') or []):
            return True
    if can_siparis_onaya_gonder(yk) and _kullanici_cari_atanmis(con, kullanici_id, cari_id):
        return True
    return False


def can_write_crm(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_cari360_crm_write(yk):
        return False
    if can_cari360_view_all(yk):
        return True
    return _kullanici_cari_atanmis(con, kullanici_id, cari_id)


def can_create_order(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_siparis_onaya_gonder(yk) and not _yk_has(yk, 'nexgen.plan.manage', 'can_manage'):
        if not can_cari360_view_all(yk):
            if not _yk_has(yk, 'nexgen.plan.manage', 'can_create'):
                return False
    if can_cari360_view_all(yk):
        return True
    return _kullanici_cari_atanmis(con, kullanici_id, cari_id)


def can_view_finans_summary(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if can_cari360_view_all(yk) and _yk_has(yk, YETKI_CARI360_FINANS_VIEW, 'can_view'):
        return True
    if not _yk_has(yk, YETKI_CARI360_FINANS_VIEW, 'can_view'):
        return False
    return _kullanici_cari_atanmis(con, kullanici_id, cari_id) or can_cari360_view_all(yk)


def can_write_finans(
    con,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_cari360_finans_write(yk):
        return False
    if can_physical_delete(yk):
        pass
    if can_cari360_view_all(yk):
        return True
    return False


def can_manage_sorumlu(yk: set[str]) -> bool:
    return (
        _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage')
        or _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_create')
        or _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_update')
    )


def list_cari_sorumlulari(con, cari_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        SELECT cs.*, sk.KullaniciAdi AS kullanici_adi,
               sk2.KullaniciAdi AS atayan_adi
        FROM cari_sorumlu cs
        LEFT JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        LEFT JOIN sistem_kullanici sk2 ON sk2.Id = cs.atayan_kullanici_id
        WHERE cs.cari_id=?
        ORDER BY cs.aktif DESC, cs.sorumluluk_rolu, cs.baslangic_tarihi DESC
        """,
        (cari_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_aktif_cari_sorumlulari(con, cari_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT cs.*, sk.KullaniciAdi AS kullanici_adi
        FROM cari_sorumlu cs
        LEFT JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        WHERE cs.cari_id=? AND cs.aktif=1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi=''
               OR cs.bitis_tarihi > datetime('now','localtime'))
        ORDER BY cs.sorumluluk_rolu, cs.baslangic_tarihi
        """,
        (cari_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def atama_ekle(
    con,
    cari_id: int,
    kullanici_id: int,
    sorumluluk_rolu: str,
    atayan_kullanici_id: int | None = None,
    atama_notu: str | None = None,
    baslangic_tarihi: str | None = None,
) -> dict[str, Any]:
    rol = (sorumluluk_rolu or '').upper().strip()
    if rol not in SORUMLULUK_ROLLERI:
        return {'ok': False, 'hata': f'Geçersiz rol: {rol}'}

    nc = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
    if not nc:
        return {'ok': False, 'hata': 'Cari bulunamadı'}
    ku = con.execute(
        'SELECT Id FROM sistem_kullanici WHERE Id=? AND Aktif=1', (kullanici_id,)
    ).fetchone()
    if not ku:
        return {'ok': False, 'hata': 'Kullanıcı bulunamadı'}

    dup = con.execute(
        f"""
        SELECT id FROM cari_sorumlu
        WHERE cari_id=? AND kullanici_id=? AND sorumluluk_rolu=? AND {_AKTIF_WHERE}
        """,
        (cari_id, kullanici_id, rol),
    ).fetchone()
    if dup:
        return {'ok': False, 'hata': 'Aynı aktif atama zaten var'}

    if rol == 'ANA':
        mevcut_ana = con.execute(
            f"""
            SELECT id FROM cari_sorumlu
            WHERE cari_id=? AND sorumluluk_rolu='ANA' AND {_AKTIF_WHERE}
            """,
            (cari_id,),
        ).fetchone()
        if mevcut_ana:
            return {'ok': False, 'hata': 'Bu cari için zaten aktif ANA sorumlu var. Önce pasife alın.'}

    ts = _now()
    bas = baslangic_tarihi or _today()
    con.execute(
        """
        INSERT INTO cari_sorumlu
            (cari_id, kullanici_id, sorumluluk_rolu, baslangic_tarihi,
             aktif, atayan_kullanici_id, atama_notu, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (cari_id, kullanici_id, rol, bas, atayan_kullanici_id, atama_notu, ts, ts),
    )
    new_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    return {'ok': True, 'id': new_id}


def rol_degistir(con, atama_id: int, yeni_rol: str) -> dict[str, Any]:
    rol = (yeni_rol or '').upper().strip()
    if rol not in SORUMLULUK_ROLLERI:
        return {'ok': False, 'hata': f'Geçersiz rol: {rol}'}

    row = con.execute(
        f'SELECT * FROM cari_sorumlu WHERE id=? AND {_AKTIF_WHERE}',
        (atama_id,),
    ).fetchone()
    if not row:
        return {'ok': False, 'hata': 'Aktif atama bulunamadı'}

    if rol == 'ANA' and (row['sorumluluk_rolu'] or '') != 'ANA':
        mevcut = con.execute(
            f"""
            SELECT id FROM cari_sorumlu
            WHERE cari_id=? AND sorumluluk_rolu='ANA' AND {_AKTIF_WHERE} AND id<>?
            """,
            (row['cari_id'], atama_id),
        ).fetchone()
        if mevcut:
            return {'ok': False, 'hata': 'Zaten aktif ANA sorumlu var'}

    con.execute(
        "UPDATE cari_sorumlu SET sorumluluk_rolu=?, updated_at=? WHERE id=?",
        (rol, _now(), atama_id),
    )
    return {'ok': True}


def pasife_al(con, atama_id: int) -> dict[str, Any]:
    row = con.execute(
        f'SELECT id FROM cari_sorumlu WHERE id=? AND {_AKTIF_WHERE}',
        (atama_id,),
    ).fetchone()
    if not row:
        return {'ok': False, 'hata': 'Aktif atama bulunamadı'}
    ts = _now()
    con.execute(
        """
        UPDATE cari_sorumlu
        SET aktif=0, bitis_tarihi=date('now','localtime'), updated_at=?
        WHERE id=?
        """,
        (ts, atama_id),
    )
    return {'ok': True}


def list_pazarlamaci_adaylari(con) -> list[dict[str, Any]]:
    """Yönetim UI kullanıcı dropdown için aktif kullanıcılar."""
    rows = con.execute(
        """
        SELECT sk.Id, sk.KullaniciAdi, sr.Ad AS rol_adi
        FROM sistem_kullanici sk
        LEFT JOIN sistem_rol sr ON sr.Id = sk.RolId
        WHERE sk.Aktif=1
        ORDER BY sk.KullaniciAdi
        """
    ).fetchall()
    return [dict(r) for r in rows]
