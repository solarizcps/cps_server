# -*- coding: utf-8 -*-
"""Operasyonel cari + finans kartı + teknik bağlantı otomatik provisioning — FAZ-GECIS."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.finans_audit_service import (
    FinansAuditError,
    audit_yaz,
    new_transaction_id,
)
from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import (
    FinansCariIdentityError,
    resolve_by_operasyonel,
)
from modules.nexgen.finans_cari_kart_service import (
    FinansCariKartError,
    create as kart_create,
    get_by_ckod_raw,
    row_to_dict,
)
from modules.nexgen.finans_core_config import (
    AUDIT_ENTITY_CARI_GECIS,
    AUDIT_GECIS_BAGLANTI_OLUSTUR,
    AUDIT_GECIS_KART_OTOMATIK,
    AUDIT_GECIS_KART_OLUSTUR,
    AUDIT_GECIS_NOOP,
    CARI_TIP_MUSTERI,
    CARI_TIP_TEDARIKCI,
    idempotency_gecis,
)

TEST_KOD_PATTERNS = (
    re.compile(r'^F2TEST-', re.I),
    re.compile(r'^FINTEST-', re.I),
    re.compile(r'P09004$', re.I),
    re.compile(r'ANINDA\s*TEST', re.I),
    re.compile(r'\bTEST\b', re.I),
)


class FinansCariProvisionError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'PROVISION_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def is_test_kayit(kod: str | None, unvan: str | None) -> bool:
    k = (kod or '').strip()
    u = (unvan or '').strip()
    for pat in TEST_KOD_PATTERNS:
        if pat.search(k) or pat.search(u):
            return True
    return False


def _ctip_for_tip(tip: str) -> str:
    return '1' if tip == CARI_TIP_MUSTERI else '2'


def _ensure_legacy_cari_kart(
    con: sqlite3.Connection,
    ckod: str,
    unvan: str,
    tip: str,
    *,
    aktif: bool = True,
) -> bool:
    """Returns True if newly created."""
    row = con.execute('SELECT CKod FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
    if row:
        return False
    con.execute(
        'INSERT INTO Cari_Kart (CKod, CName, CTip, Aktif) VALUES (?, ?, ?, ?)',
        (ckod, unvan, _ctip_for_tip(tip), 1 if aktif else 0),
    )
    return True


def _ensure_cari_eslestirme(
    con: sqlite3.Connection,
    nexgen_cari_id: int,
    ckod: str,
) -> bool:
    """Returns True if created or updated."""
    if not tablo_var(con, 'cari_eslestirme'):
        return False
    mevcut = con.execute(
        'SELECT id, cari_kart_ckod, eslestirme_durumu FROM cari_eslestirme WHERE nexgen_cari_id=?',
        (int(nexgen_cari_id),),
    ).fetchone()
    if mevcut:
        if mevcut['cari_kart_ckod'] == ckod and (mevcut['eslestirme_durumu'] or '').upper() in ('DOGRULANDI', 'MANUEL'):
            return False
        con.execute(
            """
            UPDATE cari_eslestirme SET
                cari_kart_ckod=?, eslestirme_durumu='DOGRULANDI',
                eslestirme_yontemi='CARI_KODU', aktif=1,
                eslestirme_tarihi=datetime('now','localtime'),
                updated_at=datetime('now','localtime')
            WHERE nexgen_cari_id=?
            """,
            (ckod, int(nexgen_cari_id)),
        )
        return True
    con.execute(
        """
        INSERT INTO cari_eslestirme (
            nexgen_cari_id, cari_kart_ckod, eslestirme_durumu,
            eslestirme_yontemi, aktif, eslestirme_tarihi
        ) VALUES (?, ?, 'DOGRULANDI', 'CARI_KODU', 1, datetime('now','localtime'))
        """,
        (int(nexgen_cari_id), ckod),
    )
    return True


def _ensure_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    ckod: str,
) -> bool:
    if not tablo_var(con, 'tedarikci_eslestirme'):
        return False
    mevcut = con.execute(
        'SELECT id, cari_kart_ckod FROM tedarikci_eslestirme WHERE nexgen_tedarikci_id=?',
        (int(nexgen_tedarikci_id),),
    ).fetchone()
    if mevcut:
        if mevcut['cari_kart_ckod'] == ckod:
            return False
        con.execute(
            """
            UPDATE tedarikci_eslestirme SET
                cari_kart_ckod=?, eslestirme_durumu='DOGRULANDI', aktif=1
            WHERE nexgen_tedarikci_id=?
            """,
            (ckod, int(nexgen_tedarikci_id)),
        )
        return True
    con.execute(
        """
        INSERT INTO tedarikci_eslestirme (
            nexgen_tedarikci_id, cari_kart_ckod, eslestirme_durumu, aktif
        ) VALUES (?, ?, 'DOGRULANDI', 1)
        """,
        (int(nexgen_tedarikci_id), ckod),
    )
    return True


def _ensure_kimlik(
    con: sqlite3.Connection,
    *,
    tip: str,
    operasyonel_id: int,
    ckod: str,
    unvan: str,
    user_id: int | None,
) -> bool:
    """Returns True if created or updated."""
    if not tablo_var(con, 'finans_cari_kimlik'):
        return False
    if tip == CARI_TIP_MUSTERI:
        row = con.execute(
            'SELECT id, cari_kart_ckod, durum FROM finans_cari_kimlik WHERE nexgen_cari_id=? AND aktif=1',
            (int(operasyonel_id),),
        ).fetchone()
        if row:
            if row['cari_kart_ckod'] == ckod and (row['durum'] or '').upper() == 'DOGRULANDI':
                return False
            con.execute(
                """
                UPDATE finans_cari_kimlik SET
                    cari_kart_ckod=?, durum='DOGRULANDI', unvan_snapshot=?,
                    updated_at=?, updated_by=?
                WHERE id=?
                """,
                (ckod, unvan, _now(), user_id, int(row['id'])),
            )
            return True
        con.execute(
            """
            INSERT INTO finans_cari_kimlik (
                kimlik_tipi, nexgen_cari_id, cari_kart_ckod, unvan_snapshot,
                durum, aktif, created_at, updated_at, created_by, updated_by
            ) VALUES ('MUSTERI', ?, ?, ?, 'DOGRULANDI', 1, ?, ?, ?, ?)
            """,
            (int(operasyonel_id), ckod, unvan, _now(), _now(), user_id, user_id),
        )
        return True

    row = con.execute(
        'SELECT id, cari_kart_ckod, durum FROM finans_cari_kimlik WHERE nexgen_tedarikci_id=? AND aktif=1',
        (int(operasyonel_id),),
    ).fetchone()
    if row:
        if row['cari_kart_ckod'] == ckod and (row['durum'] or '').upper() == 'DOGRULANDI':
            return False
        con.execute(
            """
            UPDATE finans_cari_kimlik SET
                cari_kart_ckod=?, durum='DOGRULANDI', unvan_snapshot=?,
                updated_at=?, updated_by=?
            WHERE id=?
            """,
            (ckod, unvan, _now(), user_id, int(row['id'])),
        )
        return True
    con.execute(
        """
        INSERT INTO finans_cari_kimlik (
            kimlik_tipi, nexgen_tedarikci_id, cari_kart_ckod, unvan_snapshot,
            durum, aktif, created_at, updated_at, created_by, updated_by
        ) VALUES ('TEDARIKCI', ?, ?, ?, 'DOGRULANDI', 1, ?, ?, ?, ?)
        """,
        (int(operasyonel_id), ckod, unvan, _now(), _now(), user_id, user_id),
    )
    return True


def _ckod_cakisma_kontrol(
    con: sqlite3.Connection,
    ckod: str,
    tip: str,
    operasyonel_id: int,
) -> None:
    """Başka operasyonel kayıt aynı kodu kullanıyorsa hata."""
    if tip == CARI_TIP_MUSTERI:
        diger = con.execute(
            'SELECT id FROM nexgen_cari WHERE cari_kod=? AND id!=? AND aktif=1',
            (ckod, int(operasyonel_id)),
        ).fetchone()
        if diger:
            raise FinansCariProvisionError(
                f'Kod çakışması — başka müşteri cari: {ckod}', 409, 'KOD_CAKISMA',
            )
    else:
        diger = con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE kod=? AND id!=? AND aktif=1',
            (ckod, int(operasyonel_id)),
        ).fetchone()
        if diger:
            raise FinansCariProvisionError(
                f'Kod çakışması — başka tedarikçi: {ckod}', 409, 'KOD_CAKISMA',
            )


def _already_provisioned(con: sqlite3.Connection, tip: str, operasyonel_id: int, ckod: str) -> bool:
    try:
        res = resolve_by_operasyonel(con, tip, int(operasyonel_id), require_active=True)
        return (
            res.finans_kart is not None
            and res.finance_card_code == ckod
            and not res.requires_manual_link
            and not res.is_legacy_fallback
        )
    except FinansCariIdentityError:
        return False


def provision_operasyonel(
    con: sqlite3.Connection,
    tip: str,
    operasyonel_id: int,
    *,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    owns_transaction: bool = True,
    otomatik_yeni_cari: bool = False,
    skip_test: bool = True,
) -> dict[str, Any]:
    """Tek operasyonel cari için finans kartı + bağlantı — idempotent."""
    tip_u = (tip or '').strip().upper()
    oid = int(operasyonel_id)
    if tip_u == CARI_TIP_MUSTERI:
        op = con.execute(
            'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?',
            (oid,),
        ).fetchone()
        if not op:
            raise FinansCariProvisionError('nexgen_cari bulunamadı.', 404, 'NEXGEN_CARI_YOK')
        ckod = (op['cari_kod'] or '').strip()
        unvan = (op['unvan'] or '').strip()
        para_birimi = 'TRY'
    elif tip_u == CARI_TIP_TEDARIKCI:
        op = con.execute(
            'SELECT id, kod, ad, aktif, para_birimi, varsayilan_vade FROM nexgen_tedarikci WHERE id=?',
            (oid,),
        ).fetchone()
        if not op:
            raise FinansCariProvisionError('nexgen_tedarikci bulunamadı.', 404, 'NEXGEN_TEDARIKCI_YOK')
        ckod = (op['kod'] or '').strip()
        unvan = (op['ad'] or '').strip()
        para_birimi = (op['para_birimi'] or 'TRY').strip().upper()
    else:
        raise FinansCariProvisionError('Geçersiz cari tipi.', 400, 'CARI_TIP_GECERSIZ')

    if not int(op['aktif'] or 0):
        raise FinansCariProvisionError('Operasyonel cari pasif.', 409, 'OPERASYONEL_PASIF')
    if not ckod:
        raise FinansCariProvisionError('Operasyonel cari kodu boş.', 409, 'KOD_BOS')
    if not unvan:
        raise FinansCariProvisionError('Ünvan boş.', 409, 'UNVAN_BOS')
    if skip_test and is_test_kayit(ckod, unvan):
        raise FinansCariProvisionError('Test kaydı — geçiş hariç.', 409, 'TEST_KAYIT')

    _ckod_cakisma_kontrol(con, ckod, tip_u, oid)
    idem = idempotency_gecis(tip_u, oid, ckod)

    if _already_provisioned(con, tip_u, oid, ckod):
        return {
            'sonuc': 'NOOP',
            'ckod': ckod,
            'operasyonel_id': oid,
            'cari_tipi': tip_u,
            'idempotency_key': idem,
        }

    tx_id = new_transaction_id()
    if owns_transaction:
        con.execute('BEGIN IMMEDIATE')

    olusturulan: dict[str, bool] = {
        'legacy_cari_kart': False,
        'finans_cari_kart': False,
        'kimlik': False,
        'eslestirme': False,
    }

    try:
        olusturulan['legacy_cari_kart'] = _ensure_legacy_cari_kart(
            con, ckod, unvan, tip_u, aktif=True,
        )

        if not get_by_ckod_raw(con, ckod):
            kart_create(
                con, ckod=ckod, unvan=unvan, tip=tip_u,
                para_birimi=para_birimi,
                varsayilan_vade_gun=int(op['varsayilan_vade']) if tip_u == CARI_TIP_TEDARIKCI and op['varsayilan_vade'] else None,
                aktif=True,
                kullanici_id=kullanici_id,
                rol_kodu=rol_kodu,
                owns_transaction=False,
            )
            olusturulan['finans_cari_kart'] = True

        olusturulan['kimlik'] = _ensure_kimlik(
            con, tip=tip_u, operasyonel_id=oid, ckod=ckod, unvan=unvan, user_id=kullanici_id,
        )
        if tip_u == CARI_TIP_MUSTERI:
            olusturulan['eslestirme'] = _ensure_cari_eslestirme(con, oid, ckod)
        else:
            olusturulan['eslestirme'] = _ensure_tedarikci_eslestirme(con, oid, ckod)

        if olusturulan['kimlik'] or olusturulan['eslestirme']:
            audit_yaz(
                con,
                islem_turu=AUDIT_GECIS_BAGLANTI_OLUSTUR,
                entity_tipi=AUDIT_ENTITY_CARI_GECIS,
                entity_id=oid,
                yeni={'ckod': ckod, 'tip': tip_u, **olusturulan},
                yeni_durum='DOGRULANDI',
                kullanici_id=kullanici_id,
                transaction_id=tx_id,
                idempotency_key=idem + ':BAGLANTI',
            )

        res = resolve_by_operasyonel(con, tip_u, oid, require_active=True)
        if res.requires_manual_link or not res.finans_kart:
            raise FinansCariProvisionError(
                'Resolver doğrulama başarısız.', 409, 'RESOLVER_DOGRULAMA_HATASI',
            )

        if owns_transaction:
            con.commit()

        degisti = any(olusturulan.values())
        return {
            'sonuc': 'OLUSTURULDU' if degisti else 'GUNCELLENDI',
            'ckod': ckod,
            'operasyonel_id': oid,
            'cari_tipi': tip_u,
            'finans_kart': res.finans_kart,
            'olusturulan': olusturulan,
            'transaction_id': tx_id,
            'idempotency_key': idem,
        }
    except (FinansAuditError, FinansCariKartError, FinansCariIdentityError, FinansCariProvisionError):
        if owns_transaction:
            con.rollback()
        raise
    except Exception:
        if owns_transaction:
            con.rollback()
        raise


def provision_yeni_musteri(
    con: sqlite3.Connection,
    nexgen_cari_id: int,
    *,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    owns_transaction: bool = True,
) -> dict[str, Any]:
    return provision_operasyonel(
        con, CARI_TIP_MUSTERI, int(nexgen_cari_id),
        kullanici_id=kullanici_id,
        rol_kodu=rol_kodu,
        owns_transaction=owns_transaction,
        otomatik_yeni_cari=True,
        skip_test=False,
    )


def provision_yeni_tedarikci(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    *,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    owns_transaction: bool = True,
) -> dict[str, Any]:
    return provision_operasyonel(
        con, CARI_TIP_TEDARIKCI, int(nexgen_tedarikci_id),
        kullanici_id=kullanici_id,
        rol_kodu=rol_kodu,
        owns_transaction=owns_transaction,
        otomatik_yeni_cari=True,
        skip_test=False,
    )
