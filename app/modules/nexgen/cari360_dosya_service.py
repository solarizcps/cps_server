# -*- coding: utf-8 -*-
"""Cari 360 — Müşteri Dijital Dosyası (read-only, gerçek veri)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_golden_master_service import get_golden_master_snapshot
from modules.nexgen.cari_sorumlu_service import can_view_cari, list_aktif_cari_sorumlulari
from modules.nexgen.cari360_yetki import can_cari360_finans_view
from modules.nexgen.cari_yetkili_service import list_cari_yetkilileri
from modules.nexgen.mo_gorusme_config import KAYNAK_MUSTERI_OPERASYONU, TABLO as GORUSME_TABLO
from modules.nexgen.mo_gorusme_service import timeline_olay_sozlesmesi
from modules.nexgen.mo_tahsilat_config import PLAN_DURUM_SEVK_BEKLIYOR
from modules.nexgen.mo_tahsilat_plan_service import plan_hatirlatma_grubu, tahsilat_kural_etiket

_TEST_ISARETLERI = (
    'MO-GORUSME-TEST', 'MO-KAPANIS-TEST', 'MO-TAHSILAT-TEST', 'MO-SIPARIS-TEST', 'C360-TEST', '-TEST-',
)


class Cari360DosyaError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    return any(c[1] == kolon for c in con.execute(f'PRAGMA table_info({tablo})').fetchall())


def _test_mi(*vals: str | None) -> bool:
    for v in vals:
        if not v:
            continue
        u = str(v).upper()
        if any(t in u for t in _TEST_ISARETLERI):
            return True
    return False


def _parse_dt(val: str | None) -> str:
    if not val:
        return ''
    s = str(val).strip()
    return (s + ' 12:00:00') if len(s) == 10 else s[:19]


def _gun_fark(bitis: str | None, bas: date | None = None) -> int | None:
    if not bitis:
        return None
    try:
        d = date.fromisoformat(str(bitis)[:10])
        return (bas or date.today()) - d
    except ValueError:
        return None


def _fmt_tl(v: float | None) -> str:
    if v is None or v <= 0:
        return '—'
    return f'{v:,.0f} TL'


def _erisim(con, cari_id: int, uid: int, yk: set[str] | None) -> None:
    """Kart + hafıza: atanmış pazarlamacı / yönetici — can_view_cari."""
    if not can_view_cari(con, uid, cari_id, yk):
        raise Cari360DosyaError('Bu cari için görüntüleme yetkiniz yok.', 403)


def _siparis_durum_metin(durum: str | None, tahsilat_durumu: str | None = None) -> tuple[str, str]:
    d = (durum or '').upper()
    if d == 'TASLAK':
        return 'Sipariş talebi oluşturuldu', 'Taslak'
    if d in ('ONAY_BEKLIYOR',) or (tahsilat_durumu or '').upper() == 'ONAY_BEKLIYOR':
        return 'Sipariş — Onay bekliyor', 'Onay bekliyor'
    if d == 'REVIZYON':
        return 'Sipariş — Revizyon istendi', 'Revizyon'
    if d == 'REDDEDILDI':
        return 'Sipariş — Reddedildi', 'Reddedildi'
    if d in ('ONAYLANDI', 'PLANLAMAYA_HAZIR', 'MPR_BEKLIYOR'):
        return 'Sipariş — Planlamaya aktarıldı', 'Planlamaya aktarıldı'
    if d == 'URETIMDE':
        return 'Sipariş — Üretimde', 'Üretimde'
    if d == 'TAMAMLANDI':
        return 'Sipariş tamamlandı', 'Tamamlandı'
    return f'Sipariş — {(durum or "—").replace("_", " ")}', durum or '—'


def _numune_durum_metin(durum: str | None) -> tuple[str, str]:
    d = (durum or '').upper()
    m = {
        'TASLAK': ('Numune — Talep açıldı', 'Talep açıldı'),
        'YENI_TALEP': ('Numune — Talep açıldı', 'Talep açıldı'),
        'BEKLEYEN_NUMUNE': ('Numune — İşleme alınmayı bekliyor', 'İşleme bekliyor'),
        'ONAY_BEKLIYOR': ('Numune — Yönetim sonucu bekliyor', 'Yönetim sonucu bekliyor'),
        'REVIZYON_ISTENDI': ('Numune — Revizyonda', 'Revizyonda'),
        'REVIZYONDA': ('Numune — Revizyonda', 'Revizyonda'),
        'REDDEDILDI': ('Numune — Reddedildi', 'Reddedildi'),
        'ONAYLANDI': ('Numune — Onaylandı', 'Onaylandı'),
        'CALISILIYOR': ('Numune — AR-GE çalışıyor', 'AR-GE çalışıyor'),
        'FERHAT_TESTINDE': ('Numune — Ferhat denemesi', 'Ferhat denemesi'),
        'RECETE_MERKEZINE_AKTARILDI': ('Numune — Onaylandı', 'Onaylandı'),
    }
    return m.get(d, (f'Numune — {(durum or "—").replace("_", " ")}', durum or '—'))


def _hafiza_satir(
    *,
    event_date: str,
    hareket_turu: str,
    baslik: str,
    aciklama: str = '',
    durum: str = '',
    source_type: str,
    source_id: int | str,
    kayit_no: str = '',
    tutar: str = '',
    termin: str = '',
    kategori: str,
    test: bool = False,
    audit: list | None = None,
    metadata: dict | None = None,
    detay_url: str = '',
    oncelik: int = 50,
    sonraki_asama: str = '',
    gecikme: str = '',
    dedupe_suffix: str = '',
) -> dict[str, Any]:
    dk = f'{source_type}:{source_id}:{kategori}:{hareket_turu}'
    if dedupe_suffix:
        dk = f'{dk}:{dedupe_suffix}'
    return {
        'event_date': _parse_dt(event_date),
        'hareket_turu': hareket_turu,
        'title': baslik,
        'short_description': aciklama[:500],
        'status': durum or '—',
        'source_type': source_type,
        'source_id': source_id,
        'kayit_no': kayit_no,
        'tutar': tutar,
        'termin': termin,
        'category': kategori,
        'test_kayit': test,
        'dedupe_key': dk,
        'audit_events': audit or [],
        'metadata': metadata or {},
        'detay_url': detay_url or '',
        'oncelik': oncelik,
        'sonraki_asama': sonraki_asama or '',
        'gecikme': gecikme or '',
    }


def _gecikme_etiket(hedef: str | None) -> str:
    if not hedef:
        return ''
    gf = _gun_fark(hedef)
    if gf is None:
        return ''
    # _gun_fark = bugün - hedef → pozitif = gecikmiş
    if gf.days > 0:
        return f'{gf.days} gün gecikmiş'
    if gf.days == 0:
        return 'Bugün'
    return ''


def _siparis_canli_surec(con: sqlite3.Connection, siparis_id: int, durum: str | None,
                         tahsilat_durumu: str | None, termin: str | None) -> dict[str, str]:
    """Gerçek plan/batch/parça/sevk kayıtlarından sipariş süreç etiketi."""
    d = (durum or '').upper()
    _, base_st = _siparis_durum_metin(durum, tahsilat_durumu)
    st = base_st
    sonraki = ''
    if d in ('TASLAK', 'ONAY_BEKLIYOR') or (tahsilat_durumu or '').upper() == 'ONAY_BEKLIYOR':
        st, sonraki = 'Onay bekliyor', 'Planlamaya aktarım'
    elif d == 'REDDEDILDI':
        return {'durum': 'Reddedildi', 'sonraki': '', 'gecikme': _gecikme_etiket(termin), 'ozet': ''}
    elif d == 'REVIZYON':
        st, sonraki = 'Revizyon', 'Yeniden onay'

    plan_ids: list[int] = []
    if _tablo_var(con, 'nexgen_uretim_plan') and _kolon_var(con, 'nexgen_uretim_plan', 'planlama_siparis_id'):
        plan_ids = [int(r['id']) for r in con.execute(
            'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? AND cari_id IS NOT NULL',
            (siparis_id,),
        ).fetchall()]

    batch_ids: list[int] = []
    if plan_ids and _tablo_var(con, 'nexgen_uretim_batch'):
        ph = ','.join('?' * len(plan_ids))
        batch_ids = [int(r['id']) for r in con.execute(
            f'SELECT id FROM nexgen_uretim_batch WHERE plan_id IN ({ph})', plan_ids,
        ).fetchall()]

    basladi = False
    tamam_parca = 0
    toplam_parca = 0
    if batch_ids and _tablo_var(con, 'nexgen_uretim_parca'):
        ph = ','.join('?' * len(batch_ids))
        for r in con.execute(
            f"""SELECT durum, baslama_zamani, bitis_zamani FROM nexgen_uretim_parca
                WHERE batch_id IN ({ph})""", batch_ids,
        ).fetchall():
            toplam_parca += 1
            if r['baslama_zamani']:
                basladi = True
            if (r['durum'] or '').upper() in ('TAMAM', 'TAMAMLANDI', 'BITTI') or r['bitis_zamani']:
                tamam_parca += 1

    sevk_adet = 0
    sevk_tamam = 0
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        for r in con.execute(
            'SELECT durum FROM mo_musteri_sevkiyat WHERE siparis_id=? AND aktif=1',
            (siparis_id,),
        ).fetchall():
            sevk_adet += 1
            if (r['durum'] or '').upper() in ('SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'):
                sevk_tamam += 1

    if sevk_adet and sevk_tamam >= sevk_adet:
        st, sonraki = 'Sevk edildi', ''
    elif sevk_adet and sevk_tamam:
        st, sonraki = 'Kısmi sevk', 'Kalan sevk'
    elif d == 'TAMAMLANDI' or (toplam_parca and tamam_parca >= toplam_parca and basladi):
        st, sonraki = 'Üretim tamamlandı', 'Sevkiyat'
    elif basladi:
        st, sonraki = 'Üretimde', 'Üretim tamamlanması'
    elif batch_ids and not basladi:
        st, sonraki = 'Üretim başlamadı', 'Üretim başlangıcı'
    elif batch_ids:
        st, sonraki = 'Batch oluştu', 'Üretim başlangıcı'
    elif plan_ids:
        st, sonraki = 'Planlamaya aktarıldı', 'Batch oluşumu'
    elif d in ('ONAYLANDI', 'PLANLAMAYA_HAZIR', 'MPR_BEKLIYOR') and not plan_ids:
        st, sonraki = 'Planlanmadı', 'Üretim planı'
    elif sevk_adet == 0 and basladi is False and d not in ('TASLAK', 'ONAY_BEKLIYOR', 'REDDEDILDI', 'REVIZYON'):
        if st in ('Planlamaya aktarıldı', 'Onaylandı') and not plan_ids:
            st, sonraki = 'Planlanmadı', 'Üretim planı'

    if st in ('Üretim tamamlandı', 'Üretimde', 'Üretim başlamadı', 'Batch oluştu') and sevk_adet == 0:
        if st == 'Üretim tamamlandı':
            sonraki = 'Sevkiyat'
        elif not sonraki:
            sonraki = 'Sevkiyat bekliyor' if st == 'Üretim tamamlandı' else sonraki

    ozet = ''
    if plan_ids:
        ozet += f'{len(plan_ids)} plan'
    if batch_ids:
        ozet += ('; · ' if ozet else '') + f'{len(batch_ids)} batch'
    if basladi:
        ozet += ('; · ' if ozet else '') + 'üretim başladı'
    return {'durum': st, 'sonraki': sonraki, 'gecikme': _gecikme_etiket(termin), 'ozet': ozet}


def _numune_sonraki(durum: str | None) -> str:
    d = (durum or '').upper()
    return {
        'TASLAK': 'İşleme alma',
        'YENI_TALEP': 'İşleme alma',
        'BEKLEYEN_NUMUNE': 'İşleme alma',
        'CALISILIYOR': 'Ferhat / yönetim sonucu',
        'FERHAT_TESTINDE': 'Yönetim sonucu',
        'ONAY_BEKLIYOR': 'Onay / red / revizyon',
        'REVIZYON_ISTENDI': 'Yeniden çalışma',
        'REVIZYONDA': 'Yeniden çalışma',
        'ONAYLANDI': '',
        'REDDEDILDI': '',
        'RECETE_MERKEZINE_AKTARILDI': '',
    }.get(d, '')


def hafiza_liste(
    con: sqlite3.Connection,
    cari_id: int,
    uid: int,
    yk: set[str] | None = None,
    *,
    kategori: str | None = None,
    tarih_preset: str | None = None,
    arama: str | None = None,
    limit: int | None = None,
    include_test: bool = False,
) -> list[dict[str, Any]]:
    """Federasyon read-model — nexgen_cari.id üzerinden; append-only tablo yok."""
    _erisim(con, cari_id, uid, yk)
    events: list[dict] = []
    seen: set[str] = set()
    finans_ok = can_cari360_finans_view(yk or set())
    kart_base = f'/nexgen/cari360/{cari_id}'

    def _add(ev: dict):
        if ev.get('test_kayit') and not include_test:
            return
        if ev['dedupe_key'] in seen:
            return
        seen.add(ev['dedupe_key'])
        events.append(ev)

    # --- Cari kimlik özeti ---
    if _tablo_var(con, 'nexgen_cari'):
        nc = con.execute(
            'SELECT id, cari_kod, unvan, created_at, updated_at, aktif FROM nexgen_cari WHERE id=?',
            (cari_id,),
        ).fetchone()
        if nc:
            d = dict(nc)
            if d.get('created_at'):
                _add(_hafiza_satir(
                    event_date=d['created_at'],
                    hareket_turu='Cari',
                    baslik='Cari kartı oluşturuldu',
                    aciklama=f"{d.get('cari_kod') or ''} · {d.get('unvan') or ''}".strip(' ·'),
                    durum='Aktif' if d.get('aktif') else 'Pasif',
                    source_type='nexgen_cari',
                    source_id=d['id'],
                    kayit_no=d.get('cari_kod') or str(d['id']),
                    kategori='cari',
                    detay_url=f'{kart_base}?tab=genel',
                    oncelik=40,
                    dedupe_suffix='create',
                ))
            if d.get('updated_at') and (d.get('updated_at') or '')[:16] != (d.get('created_at') or '')[:16]:
                _add(_hafiza_satir(
                    event_date=d['updated_at'],
                    hareket_turu='Cari',
                    baslik='Cari bilgileri güncellendi',
                    aciklama=f"{d.get('cari_kod') or ''} · {d.get('unvan') or ''}".strip(' ·'),
                    durum='Güncellendi',
                    source_type='nexgen_cari',
                    source_id=d['id'],
                    kayit_no=d.get('cari_kod') or str(d['id']),
                    kategori='cari',
                    detay_url=f'{kart_base}?tab=genel',
                    oncelik=30,
                    dedupe_suffix='update',
                ))

    # --- Sorumlu pazarlamacı ---
    if _tablo_var(con, 'cari_sorumlu'):
        for r in con.execute(
            """SELECT cs.*, sk.KullaniciAdi FROM cari_sorumlu cs
               LEFT JOIN sistem_kullanici sk ON sk.Id=cs.kullanici_id
               WHERE cs.cari_id=? ORDER BY cs.baslangic_tarihi DESC, cs.id DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            rol = d.get('sorumluluk_rolu') or 'SORUMLU'
            aktif = int(d.get('aktif') or 0) == 1
            bas = 'Sorumlu pazarlamacı atandı' if aktif else 'Sorumlu pazarlamacı değişti/sonlandı'
            _add(_hafiza_satir(
                event_date=d.get('baslangic_tarihi') or d.get('created_at') or '',
                hareket_turu='Sorumlu',
                baslik=bas,
                aciklama=f"{d.get('KullaniciAdi') or d.get('kullanici_id')} · {rol}"
                         + (f" · {d.get('atama_notu')}" if d.get('atama_notu') else ''),
                durum='Aktif' if aktif else 'Pasif',
                source_type='cari_sorumlu',
                source_id=d['id'],
                kayit_no=str(d['id']),
                kategori='cari',
                detay_url=f'{kart_base}?tab=genel',
                oncelik=55,
            ))

    # --- Yetkililer ---
    if _tablo_var(con, 'cari_yetkili'):
        for y in list_cari_yetkilileri(con, cari_id, sadece_aktif=False):
            ad = y.get('ad_soyad') or y.get('ad') or 'Yetkili'
            ts = y.get('created_at') or y.get('updated_at') or ''
            if not ts:
                continue
            _add(_hafiza_satir(
                event_date=ts,
                hareket_turu='Yetkili',
                baslik='Yetkili kaydı',
                aciklama=f"{ad} · {y.get('unvan') or y.get('departman') or ''}".strip(' ·'),
                durum='Aktif' if int(y.get('aktif') or 0) == 1 else 'Pasif',
                source_type='cari_yetkili',
                source_id=y['id'],
                kayit_no=str(y['id']),
                kategori='cari',
                detay_url=f'{kart_base}?tab=yetkililer',
                oncelik=35,
            ))

    # --- Görüşme / takip ---
    if _tablo_var(con, GORUSME_TABLO):
        for r in con.execute(
            f"""SELECT g.*, sk.KullaniciAdi FROM {GORUSME_TABLO} g
                LEFT JOIN sistem_kullanici sk ON sk.Id=g.kullanici_id
                WHERE g.cari_id=? AND g.aktif=1 ORDER BY g.gorusme_tarihi DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            test = _test_mi(d.get('kisa_not'), d.get('idempotency_key'))
            soz = timeline_olay_sozlesmesi(d)
            tip = d.get('gorusme_tipi') or 'Görüşme'
            kat = 'sozler' if d.get('musteri_sozu') or d.get('bizim_sozumuz') else 'gorusmeler'
            takip = (d.get('sonraki_takip_tarihi') or '')[:10]
            _add(_hafiza_satir(
                event_date=d.get('gorusme_tarihi') or d.get('olusturma_tarihi') or '',
                hareket_turu=tip,
                baslik=soz.get('baslik') or f'{tip}',
                aciklama=soz.get('ozet') or d.get('kisa_not') or '',
                durum=d.get('sonuc_tipi') or '—',
                source_type='musteri_operasyon_gorusme',
                source_id=d['id'],
                kayit_no=str(d['id']),
                termin=takip,
                kategori=kat,
                test=test,
                audit=[{'kullanici': d.get('KullaniciAdi'), 'not': d.get('kisa_not')}],
                metadata={
                    'musteri_sozu': d.get('musteri_sozu'), 'bizim_sozumuz': d.get('bizim_sozumuz'),
                    'sonraki_takip': d.get('sonraki_takip_tarihi'),
                },
                detay_url=f'{kart_base}?tab=gorusmeler',
                oncelik=90,
                sonraki_asama='Takip' if takip else '',
                gecikme=_gecikme_etiket(takip) if takip else '',
            ))

    # --- Numune + gelişme ---
    if _tablo_var(con, 'nexgen_numune_talep'):
        cols = ['id', 'talep_kodu', 'durum', 'urun_adi', 'urun_tipi', 'olusturma_tarihi',
                'guncelleme_tarihi', 'revizyon_gerekce', 'hedef_tarih', 'arge_test_id']
        for o in ('aciklama', 'ek_not', 'idempotency_key', 'isleme_alinma_tarihi'):
            if _kolon_var(con, 'nexgen_numune_talep', o):
                cols.append(o)
        sql = f"SELECT {', '.join(cols)} FROM nexgen_numune_talep WHERE cari_id=? AND aktif=1"
        for r in con.execute(sql, (cari_id,)).fetchall():
            d = dict(r)
            test = _test_mi(d.get('talep_kodu'), d.get('aciklama'), d.get('idempotency_key'))
            kod = d.get('talep_kodu') or str(d['id'])
            bas, st = _numune_durum_metin(d.get('durum'))
            termin = (d.get('hedef_tarih') or '')[:10]
            _add(_hafiza_satir(
                event_date=d.get('guncelleme_tarihi') or d.get('olusturma_tarihi') or '',
                hareket_turu='Numune',
                baslik=bas,
                aciklama=f"{kod} · {d.get('urun_adi') or d.get('urun_tipi') or ''}",
                durum=st,
                source_type='nexgen_numune_talep',
                source_id=d['id'],
                kayit_no=kod,
                termin=termin,
                kategori='numuneler',
                test=test,
                metadata={'revizyon_gerekce': d.get('revizyon_gerekce'), 'arge_test_id': d.get('arge_test_id')},
                detay_url=f'{kart_base}?tab=numuneler',
                oncelik=88,
                sonraki_asama=_numune_sonraki(d.get('durum')),
                gecikme=_gecikme_etiket(termin),
            ))
            if d.get('olusturma_tarihi') and (d.get('guncelleme_tarihi') or '')[:16] != (d.get('olusturma_tarihi') or '')[:16]:
                _add(_hafiza_satir(
                    event_date=d['olusturma_tarihi'],
                    hareket_turu='Numune',
                    baslik='Numune — Talep açıldı',
                    aciklama=f"{kod} · {d.get('urun_adi') or ''}",
                    durum='Talep açıldı',
                    source_type='nexgen_numune_talep',
                    source_id=d['id'],
                    kayit_no=kod,
                    kategori='numuneler',
                    test=test,
                    detay_url=f'{kart_base}?tab=numuneler',
                    oncelik=85,
                    dedupe_suffix='open',
                ))

        if _tablo_var(con, 'nexgen_numune_talep_gelisme'):
            for r in con.execute(
                """SELECT g.*, nt.talep_kodu, nt.cari_id FROM nexgen_numune_talep_gelisme g
                   JOIN nexgen_numune_talep nt ON nt.id=g.talep_id
                   WHERE nt.cari_id=? AND COALESCE(g.aktif,1)=1 AND COALESCE(nt.aktif,1)=1
                   ORDER BY g.olay_tarihi DESC""",
                (cari_id,),
            ).fetchall():
                d = dict(r)
                tip = (d.get('olay_tipi') or 'Gelişme').replace('_', ' ')
                _add(_hafiza_satir(
                    event_date=d.get('olay_tarihi') or '',
                    hareket_turu='Numune gelişme',
                    baslik=f'Numune — {tip}',
                    aciklama=(d.get('olay_metni') or d.get('talep_kodu') or '')[:300],
                    durum=tip,
                    source_type='nexgen_numune_talep_gelisme',
                    source_id=d['id'],
                    kayit_no=d.get('talep_kodu') or str(d.get('talep_id')),
                    kategori='numuneler',
                    detay_url=f'{kart_base}?tab=numuneler',
                    oncelik=87,
                ))

    # --- AR-GE olayları (cari_id FK veya numune köprüsü) ---
    if _tablo_var(con, 'nexgen_arge_olay') and _tablo_var(con, 'nexgen_arge_test'):
        rows = con.execute(
            """SELECT o.*, a.test_no, a.cari_id AS arge_cari_id
               FROM nexgen_arge_olay o
               JOIN nexgen_arge_test a ON a.id=o.arge_test_id
               WHERE a.cari_id=?""",
            (cari_id,),
        ).fetchall()
        if _tablo_var(con, 'nexgen_numune_talep'):
            rows = list(rows) + list(con.execute(
                """SELECT o.*, a.test_no, nt.cari_id AS arge_cari_id
                   FROM nexgen_arge_olay o
                   JOIN nexgen_arge_test a ON a.id=o.arge_test_id
                   JOIN nexgen_numune_talep nt ON nt.arge_test_id=a.id AND nt.aktif=1
                   WHERE nt.cari_id=? AND (a.cari_id IS NULL OR a.cari_id=0 OR a.cari_id!=?)""",
                (cari_id, cari_id),
            ).fetchall())
        for r in rows:
            d = dict(r)
            if int(d.get('arge_cari_id') or 0) != int(cari_id):
                continue
            tip = (d.get('olay_tipi') or 'AR-GE').replace('_', ' ')
            tip_u = tip.upper()
            if any(x in tip_u for x in ('DEBUG', 'TEST', 'TOPLU SILME', 'TOPLU_SILME')):
                continue
            _add(_hafiza_satir(
                event_date=d.get('olusturma_tarihi') or '',
                hareket_turu='AR-GE',
                baslik=f'AR-GE — {tip}',
                aciklama=(d.get('aciklama') or f"{d.get('eski_durum') or ''} → {d.get('yeni_durum') or ''}")[:300],
                durum=(d.get('yeni_durum') or tip),
                source_type='nexgen_arge_olay',
                source_id=d['id'],
                kayit_no=d.get('test_no') or str(d.get('arge_test_id')),
                kategori='numuneler',
                detay_url=f'{kart_base}?tab=numuneler',
                oncelik=86,
            ))

    # --- Sipariş (+ tahsilat planı; finans yetkisine bağlı) ---
    if _tablo_var(con, 'nexgen_planlama_siparis'):
        sql = """SELECT id, siparis_no, durum, notlar, olusturma_tarihi, guncelleme_tarihi,
                 anlasma_birim_fiyat, vade_gun, musteri_termin, revizyon_gerekce,
                 tahsilat_kurali, planlanan_tahsilat_tarihi, tahsilat_durumu, tahsilat_sozu,
                 idempotency_key, talep_referansi FROM nexgen_planlama_siparis WHERE cari_id=?"""
        for r in con.execute(sql, (cari_id,)).fetchall():
            d = dict(r)
            test = _test_mi(d.get('notlar'), d.get('idempotency_key'), d.get('siparis_no'))
            no = d.get('siparis_no') or str(d['id'])
            termin = (d.get('musteri_termin') or '')[:10]
            surec = _siparis_canli_surec(con, int(d['id']), d.get('durum'), d.get('tahsilat_durumu'), termin)
            bas = f"Sipariş — {surec['durum']}"
            tutar = _fmt_tl(float(d.get('anlasma_birim_fiyat') or 0)) if finans_ok else ''
            acik = f"{no} · {d.get('notlar') or d.get('talep_referansi') or ''}"[:200]
            if surec.get('ozet'):
                acik = f"{acik} · {surec['ozet']}"[:300]
            _add(_hafiza_satir(
                event_date=d.get('guncelleme_tarihi') or d.get('olusturma_tarihi') or '',
                hareket_turu='Sipariş',
                baslik=bas,
                aciklama=acik,
                durum=surec['durum'],
                source_type='nexgen_planlama_siparis',
                source_id=d['id'],
                kayit_no=no,
                tutar=tutar if tutar and tutar != '—' else '',
                termin=termin,
                kategori='siparisler',
                test=test,
                metadata={'vade_gun': d.get('vade_gun'), 'revizyon_gerekce': d.get('revizyon_gerekce')},
                detay_url=f'{kart_base}?tab=siparisler',
                oncelik=92,
                sonraki_asama=surec.get('sonraki') or '',
                gecikme=surec.get('gecikme') or '',
            ))
            if finans_ok and d.get('tahsilat_kurali'):
                td = (d.get('tahsilat_durumu') or '').upper()
                if td == PLAN_DURUM_SEVK_BEKLIYOR:
                    tb, ts = 'Tahsilat — Gerçek sevk bekleniyor', 'Sevk bekleniyor'
                elif d.get('planlanan_tahsilat_tarihi'):
                    tb, ts = 'Tahsilat planı — Sabit tarih', plan_hatirlatma_grubu(
                        d.get('planlanan_tahsilat_tarihi'), td) or 'Planlandı'
                else:
                    tb = f"Tahsilat planı — {tahsilat_kural_etiket(d.get('tahsilat_kurali'))}"
                    ts = tahsilat_kural_etiket(d.get('tahsilat_kurali')) or '—'
                _add(_hafiza_satir(
                    event_date=d.get('guncelleme_tarihi') or d.get('olusturma_tarihi') or '',
                    hareket_turu='Tahsilat Planı',
                    baslik=tb,
                    aciklama=d.get('tahsilat_sozu') or d.get('planlanan_tahsilat_tarihi') or '',
                    durum=str(ts),
                    source_type='nexgen_planlama_siparis',
                    source_id=f"plan-{d['id']}",
                    kayit_no=no,
                    tutar=tutar if tutar and tutar != '—' else '',
                    kategori='tahsilatlar',
                    test=test,
                    detay_url=f'{kart_base}?tab=siparisler',
                    oncelik=70,
                    dedupe_suffix='tahsilat-plan',
                ))

    # --- Üretim planı ---
    if _tablo_var(con, 'nexgen_uretim_plan'):
        for r in con.execute(
            """SELECT p.*, sk.KullaniciAdi FROM nexgen_uretim_plan p
               LEFT JOIN sistem_kullanici sk ON sk.Id=p.created_by
               WHERE p.cari_id=? ORDER BY COALESCE(p.created_at, p.plan_tarihi) DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            kod = d.get('plan_kodu') or str(d['id'])
            _add(_hafiza_satir(
                event_date=d.get('created_at') or d.get('plan_tarihi') or '',
                hareket_turu='Üretim planı',
                baslik='Üretim planı oluşturuldu',
                aciklama=f"{kod} · {d.get('siparis_no') or ''} · {d.get('notlar') or ''}"[:250],
                durum=(d.get('durum') or '—').replace('_', ' '),
                source_type='nexgen_uretim_plan',
                source_id=d['id'],
                kayit_no=kod,
                termin=(d.get('termin_tarihi') or '')[:10],
                kategori='uretim',
                audit=[{'kullanici': d.get('KullaniciAdi')}],
                detay_url=f'{kart_base}?tab=uretim',
                oncelik=91,
                sonraki_asama='Batch / üretim',
                gecikme=_gecikme_etiket(d.get('termin_tarihi')),
            ))

    # --- Batch + Ali başladı (parça MIN baslama) + son hareket ---
    if _tablo_var(con, 'nexgen_uretim_batch') and _tablo_var(con, 'nexgen_uretim_plan'):
        for r in con.execute(
            """SELECT b.*, p.cari_id AS plan_cari_id, p.plan_kodu, p.siparis_no AS plan_siparis_no
               FROM nexgen_uretim_batch b
               JOIN nexgen_uretim_plan p ON p.id=b.plan_id
               WHERE p.cari_id=?""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            if int(d.get('plan_cari_id') or 0) != int(cari_id):
                continue
            bk = d.get('batch_kodu') or str(d['id'])
            _add(_hafiza_satir(
                event_date=d.get('olusturma_tarihi') or '',
                hareket_turu='Batch',
                baslik='Batch oluştu',
                aciklama=f"{bk} · plan {d.get('plan_kodu') or d.get('plan_id')} · {d.get('plan_siparis_no') or ''}"[:250],
                durum=(d.get('durum') or '—').replace('_', ' '),
                source_type='nexgen_uretim_batch',
                source_id=d['id'],
                kayit_no=bk,
                kategori='uretim',
                detay_url=f'{kart_base}?tab=uretim',
                oncelik=93,
                sonraki_asama='Üretim başlangıcı',
            ))

            if not _tablo_var(con, 'nexgen_uretim_parca'):
                continue
            first = con.execute(
                """SELECT p.id, p.baslama_zamani, p.operator_id, p.parca_no, p.durum,
                          sk.KullaniciAdi
                   FROM nexgen_uretim_parca p
                   LEFT JOIN sistem_kullanici sk ON sk.Id=p.operator_id
                   WHERE p.batch_id=? AND p.baslama_zamani IS NOT NULL AND TRIM(p.baslama_zamani)!=''
                   ORDER BY p.baslama_zamani ASC, p.id ASC LIMIT 1""",
                (d['id'],),
            ).fetchone()
            if first:
                fd = dict(first)
                op = fd.get('KullaniciAdi') or (f"op#{fd['operator_id']}" if fd.get('operator_id') else '—')
                _add(_hafiza_satir(
                    event_date=fd['baslama_zamani'],
                    hareket_turu='Üretim',
                    baslik='Üretim başladı',
                    aciklama=f"{bk} · parça {fd.get('parca_no')} · {op}",
                    durum='Üretimde',
                    source_type='nexgen_uretim_parca',
                    source_id=fd['id'],
                    kayit_no=bk,
                    kategori='uretim',
                    audit=[{'kullanici': op, 'operator_id': fd.get('operator_id')}],
                    metadata={
                        'batch_id': d['id'],
                        'dedupe': 'batch_first_start',
                        'baslama_zamani': fd['baslama_zamani'],
                    },
                    detay_url=f'{kart_base}?tab=uretim',
                    oncelik=95,
                    sonraki_asama='Üretim tamamlanması / sevkiyat',
                    dedupe_suffix=f"batch-start-{d['id']}",
                ))
                # Aynı batch için ikinci "başladı" üretme: dedupe_suffix batch-start-{id}
                last = con.execute(
                    """SELECT p.id, p.updated_at, p.baslama_zamani, p.durum, p.uretilen_kg, p.parca_no
                       FROM nexgen_uretim_parca p
                       WHERE p.batch_id=? AND (
                         UPPER(COALESCE(p.durum,'')) IN ('DEVAM','BASLADI','URETIMDE')
                         OR (p.baslama_zamani IS NOT NULL AND (p.bitis_zamani IS NULL OR TRIM(p.bitis_zamani)=''))
                       )
                       ORDER BY COALESCE(p.updated_at, p.baslama_zamani) DESC, p.id DESC LIMIT 1""",
                    (d['id'],),
                ).fetchone()
                if last:
                    ld = dict(last)
                    last_ts = ld.get('updated_at') or ld.get('baslama_zamani') or ''
                    if last_ts and last_ts[:16] != (fd.get('baslama_zamani') or '')[:16]:
                        _add(_hafiza_satir(
                            event_date=last_ts,
                            hareket_turu='Üretim',
                            baslik='Üretim — son hareket',
                            aciklama=f"{bk} · parça {ld.get('parca_no')} · {(ld.get('durum') or '')}",
                            durum=(ld.get('durum') or 'DEVAM').replace('_', ' '),
                            source_type='nexgen_uretim_parca',
                            source_id=ld['id'],
                            kayit_no=bk,
                            kategori='uretim',
                            detay_url=f'{kart_base}?tab=uretim',
                            oncelik=80,
                            dedupe_suffix=f"batch-last-{d['id']}",
                        ))

    # --- Sevkiyat ---
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        for r in con.execute(
            """SELECT s.*, ps.siparis_no FROM mo_musteri_sevkiyat s
               LEFT JOIN nexgen_planlama_siparis ps ON ps.id=s.siparis_id AND ps.cari_id=s.cari_id
               WHERE s.cari_id=? AND s.aktif=1 ORDER BY COALESCE(s.sevk_tarihi, s.olusturma_tarihi) DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            if int(d.get('cari_id') or 0) != int(cari_id):
                continue
            st = (d.get('durum') or '').upper()
            if st in ('SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'):
                bas = 'Sevk edildi'
            elif st in ('HAZIRLANIYOR', 'HAZIR', 'BEKLIYOR'):
                bas = 'Sevkiyat bekliyor'
            else:
                bas = f'Sevkiyat — {st.replace("_", " ")}'
            _add(_hafiza_satir(
                event_date=d.get('sevk_tarihi') or d.get('guncelleme_tarihi') or d.get('olusturma_tarihi') or '',
                hareket_turu='Sevkiyat',
                baslik=bas,
                aciklama=f"{d.get('sevkiyat_no') or d['id']} · {d.get('siparis_no') or ''}"[:200],
                durum=st.replace('_', ' ') or '—',
                source_type='mo_musteri_sevkiyat',
                source_id=d['id'],
                kayit_no=d.get('sevkiyat_no') or str(d['id']),
                kategori='sevkiyatlar',
                detay_url=f'{kart_base}?tab=sevkiyatlar',
                oncelik=94,
            ))

    # --- Tahsilat kaydı (finans yetkisi) ---
    if finans_ok and _tablo_var(con, 'mo_tahsilat_kayit'):
        for r in con.execute(
            """SELECT tk.*, ps.siparis_no FROM mo_tahsilat_kayit tk
               LEFT JOIN nexgen_planlama_siparis ps ON ps.id=tk.siparis_id
               WHERE tk.cari_id=? AND tk.aktif=1 ORDER BY tk.guncelleme_tarihi DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            if _test_mi(d.get('aciklama'), d.get('kayit_kodu')):
                continue
            durum = (d.get('durum') or '').upper()
            bas = {
                'ONAYLANDI': 'Tahsilat alındı',
                'MUHASEBE_ONAY_BEKLIYOR': 'Tahsilat — Muhasebe onayında',
                'REVIZYON_ISTENDI': 'Tahsilat — Revizyon istendi',
                'REDDEDILDI': 'Tahsilat — Reddedildi',
            }.get(durum, 'Tahsilat kaydı')
            _add(_hafiza_satir(
                event_date=d.get('alinan_tarih') or d.get('guncelleme_tarihi') or '',
                hareket_turu='Tahsilat',
                baslik=bas,
                aciklama=d.get('aciklama') or d.get('kayit_kodu') or '',
                durum=durum.replace('_', ' '),
                source_type='mo_tahsilat_kayit',
                source_id=d['id'],
                kayit_no=d.get('kayit_kodu') or str(d['id']),
                tutar=_fmt_tl(float(d.get('alinan_tutar') or 0)),
                kategori='tahsilatlar',
                metadata={'revizyon_gerekce': d.get('revizyon_gerekce'), 'siparis_no': d.get('siparis_no')},
                detay_url=f'{kart_base}?tab=siparisler',
                oncelik=89,
            ))

    # --- Onay ---
    if _tablo_var(con, 'onay_talep'):
        for r in con.execute(
            "SELECT * FROM onay_talep WHERE cari_id=? ORDER BY talep_tarihi DESC", (cari_id,),
        ).fetchall():
            d = dict(r)
            durum = (d.get('durum') or '').upper()
            if durum not in ('REVIZYON', 'REDDEDILDI', 'ONAYLANDI', 'BEKLIYOR', 'ONAY_BEKLIYOR'):
                continue
            notu = ''
            if _tablo_var(con, 'onay_talep_adim'):
                a = con.execute(
                    """SELECT karar_notu FROM onay_talep_adim
                       WHERE talep_id=? AND durum IN ('REVIZYON','REDDEDILDI','TAMAMLANDI')
                       ORDER BY id DESC LIMIT 1""", (d['id'],),
                ).fetchone()
                if a:
                    notu = a['karar_notu'] or ''
            lbl = {
                'ONAYLANDI': 'Onaylandı', 'REVIZYON': 'Revizyon', 'REDDEDILDI': 'Red',
                'BEKLIYOR': 'Onay bekliyor', 'ONAY_BEKLIYOR': 'Onay bekliyor',
            }.get(durum, durum)
            _add(_hafiza_satir(
                event_date=d.get('updated_at') or d.get('talep_tarihi') or '',
                hareket_turu='Onay',
                baslik=f"Merkezi Onay — {lbl}",
                aciklama=notu or str(d.get('talep_kod') or d['id']),
                durum=lbl,
                source_type='onay_talep',
                source_id=d['id'],
                kayit_no=str(d.get('talep_kod') or d['id']),
                kategori='onaylar',
                detay_url=f'{kart_base}?tab=genel',
                oncelik=84,
            ))

    bas, bit = _tarih_araligi(tarih_preset)
    out = []
    for e in events:
        if kategori and kategori != 'tumu':
            if kategori == 'sozler' and e['category'] not in ('sozler', 'gorusmeler'):
                if not (e.get('metadata') or {}).get('musteri_sozu') and not (e.get('metadata') or {}).get('bizim_sozumuz'):
                    continue
            elif kategori != 'sozler' and e['category'] != kategori:
                continue
        d = (e.get('event_date') or '')[:10]
        if bas and d and d < bas:
            continue
        if bit and d and d > bit:
            continue
        if arama:
            blob = json.dumps(e, ensure_ascii=False).lower()
            if arama.lower() not in blob:
                continue
        out.append(e)
    out.sort(key=lambda x: (x.get('event_date') or '', x.get('oncelik') or 0), reverse=True)
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def _tarih_araligi(preset: str | None) -> tuple[str | None, str | None]:
    if not preset or preset == 'tumu':
        return None, None
    today = date.today()
    if preset == '30':
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    if preset == '90':
        return (today - timedelta(days=90)).isoformat(), today.isoformat()
    if preset == 'yil':
        return date(today.year, 1, 1).isoformat(), today.isoformat()
    return None, None


def _soz_durum(hedef: str | None) -> str:
    if not hedef:
        return 'açık'
    gf = _gun_fark(hedef)
    if gf is None:
        return 'açık'
    if gf.days < 0:
        return 'geçti'
    return 'açık'


def dosya_yukle(con: sqlite3.Connection, cari_id: int, uid: int, yk: set[str] | None = None) -> dict[str, Any]:
    _erisim(con, cari_id, uid, yk)
    nc = con.execute('SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
    if not nc:
        raise Cari360DosyaError('Cari bulunamadı.', 404)

    sorumlular = list_aktif_cari_sorumlulari(con, cari_id)
    ana = next((s for s in sorumlular if s.get('sorumluluk_rolu') == 'ANA'), None)
    today = date.today()

    gorusmeler: list[dict] = []
    musteri_sozleri: list[dict] = []
    bizim_sozler: list[dict] = []
    if _tablo_var(con, GORUSME_TABLO):
        for r in con.execute(
            f"SELECT * FROM {GORUSME_TABLO} WHERE cari_id=? AND aktif=1 ORDER BY gorusme_tarihi DESC",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            test = _test_mi(d.get('kisa_not'), d.get('idempotency_key'))
            gorusmeler.append({
                'tarih': (d.get('gorusme_tarihi') or '')[:10],
                'tip': d.get('gorusme_tipi'),
                'not': d.get('kisa_not'),
                'takip': d.get('sonraki_takip_tarihi'),
                'konu': d.get('sonuc_tipi'),
                'test': test,
            })
            if d.get('musteri_sozu'):
                musteri_sozleri.append({
                    'soz': d['musteri_sozu'], 'verilen_tarih': (d.get('gorusme_tarihi') or '')[:10],
                    'hedef_tarih': (d.get('sonraki_takip_tarihi') or '')[:10] or None,
                    'durum': _soz_durum(d.get('sonraki_takip_tarihi')),
                    'gorusme_id': d['id'], 'test': test,
                })
            if d.get('bizim_sozumuz'):
                bizim_sozler.append({
                    'soz': d['bizim_sozumuz'], 'verilen_tarih': (d.get('gorusme_tarihi') or '')[:10],
                    'hedef_tarih': (d.get('sonraki_takip_tarihi') or '')[:10] or None,
                    'durum': _soz_durum(d.get('sonraki_takip_tarihi')),
                    'gorusme_id': d['id'], 'test': test,
                })

    siparisler_prod: list[dict] = []
    acik_sip_adet = 0
    acik_sip_tutar = 0.0
    vadeler: list[int] = []
    tab_satis: list[dict] = []
    ilk_tarih: list[str] = []

    if _tablo_var(con, 'nexgen_planlama_siparis'):
        q = "SELECT * FROM nexgen_planlama_siparis WHERE cari_id=?"
        pr: tuple[Any, ...] = (cari_id,)
        if _kolon_var(con, 'nexgen_planlama_siparis', 'kaynak_modul'):
            q += " AND kaynak_modul=?"; pr = (cari_id, KAYNAK_MUSTERI_OPERASYONU)
        for r in con.execute(q + ' ORDER BY olusturma_tarihi DESC', pr).fetchall():
            d = dict(r)
            if _test_mi(d.get('notlar'), d.get('idempotency_key')):
                continue
            siparisler_prod.append(d)
            if d.get('olusturma_tarihi'):
                ilk_tarih.append(str(d['olusturma_tarihi'])[:10])
            durum = (d.get('durum') or '').upper()
            tutar = float(d.get('anlasma_birim_fiyat') or 0)
            if durum not in ('TAMAMLANDI', 'REDDEDILDI', 'IPTAL', 'TASLAK'):
                acik_sip_adet += 1
                acik_sip_tutar += tutar
            if d.get('vade_gun') is not None:
                try:
                    vadeler.append(int(d['vade_gun']))
                except (TypeError, ValueError):
                    pass
            _, st = _siparis_durum_metin(d.get('durum'), d.get('tahsilat_durumu'))
            tab_satis.append({
                'siparis_no': d.get('siparis_no') or d['id'],
                'tarih': (d.get('olusturma_tarihi') or '')[:10],
                'urun': d.get('talep_referansi') or d.get('notlar') or '—',
                'miktar': '—',
                'tutar': _fmt_tl(tutar),
                'termin': (d.get('musteri_termin') or '')[:10] or '—',
                'vade': f"{d.get('vade_gun')} gün" if d.get('vade_gun') is not None else '—',
                'durum': st,
            })

    numuneler_prod: list[dict] = []
    acik_num = 0
    tab_numune: list[dict] = []
    if _tablo_var(con, 'nexgen_numune_talep'):
        nq = "SELECT * FROM nexgen_numune_talep WHERE cari_id=? AND aktif=1"
        npr: tuple[Any, ...] = (cari_id,)
        if _kolon_var(con, 'nexgen_numune_talep', 'kaynak_modul'):
            nq += " AND kaynak_modul=?"; npr = (cari_id, KAYNAK_MUSTERI_OPERASYONU)
        for r in con.execute(nq + ' ORDER BY olusturma_tarihi DESC', npr).fetchall():
            d = dict(r)
            if _test_mi(d.get('talep_kodu'), d.get('aciklama')):
                continue
            numuneler_prod.append(d)
            if d.get('olusturma_tarihi'):
                ilk_tarih.append(str(d['olusturma_tarihi'])[:10])
            st = (d.get('durum') or '').upper()
            if st not in ('REDDEDILDI', 'IPTAL', 'TAMAMLANDI', 'RECETE_MERKEZINE_AKTARILDI'):
                acik_num += 1
            _, durum_txt = _numune_durum_metin(d.get('durum'))
            tab_numune.append({
                'kod': d.get('talep_kodu') or d['id'],
                'tarih': (d.get('olusturma_tarihi') or '')[:10],
                'urun': d.get('urun_adi') or d.get('urun_tipi') or '—',
                'tip': d.get('urun_tipi') or '—',
                'durum': durum_txt,
                'sonuc': d.get('onay_notu') or '—',
                'siparise_donustu': '—',
            })

    plan_top = bugun_top = yakin_top = geciken_top = tahsil_edildi = 0.0
    tab_tahsilat: list[dict] = []
    son_odeme_sozu = '—'
    if _tablo_var(con, 'nexgen_planlama_siparis') and _kolon_var(con, 'nexgen_planlama_siparis', 'tahsilat_kurali'):
        for d in siparisler_prod:
            if not d.get('tahsilat_kurali') or d.get('tahsilat_durumu') == PLAN_DURUM_SEVK_BEKLIYOR:
                continue
            tutar = float(d.get('anlasma_birim_fiyat') or 0)
            if tutar <= 0:
                continue
            grup = plan_hatirlatma_grubu(d.get('planlanan_tahsilat_tarihi'), d.get('tahsilat_durumu'))
            if grup == 'gecikti':
                geciken_top += tutar
            elif grup == 'bugun':
                bugun_top += tutar
            elif grup == 'yaklasan':
                yakin_top += tutar
            elif d.get('planlanan_tahsilat_tarihi'):
                plan_top += tutar
            if d.get('tahsilat_sozu'):
                son_odeme_sozu = d['tahsilat_sozu']
            tab_tahsilat.append({
                'siparis': d.get('siparis_no') or d['id'],
                'plan_tarih': (d.get('planlanan_tahsilat_tarihi') or '')[:10] or '—',
                'beklenen': _fmt_tl(tutar),
                'alinan': '—',
                'kalan': _fmt_tl(tutar) if grup in ('gecikti', 'bugun', 'yakin') or plan_top else '—',
                'odeme_tipi': d.get('tahsilat_odeme_sekli') or '—',
                'muhasebe': (d.get('tahsilat_durumu') or '—').replace('_', ' '),
            })
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        for r in con.execute(
            "SELECT tk.*, ps.siparis_no FROM mo_tahsilat_kayit tk LEFT JOIN nexgen_planlama_siparis ps ON ps.id=tk.siparis_id WHERE tk.cari_id=? AND tk.aktif=1",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            if _test_mi(d.get('aciklama')):
                continue
            al = float(d.get('alinan_tutar') or 0)
            if (d.get('durum') or '').upper() == 'ONAYLANDI':
                tahsil_edildi += al
            tab_tahsilat.append({
                'siparis': d.get('siparis_no') or '—',
                'plan_tarih': (d.get('alinan_tarih') or '')[:10] or '—',
                'beklenen': _fmt_tl(float(d.get('beklenen_tutar') or 0)),
                'alinan': _fmt_tl(al),
                'kalan': _fmt_tl(float(d.get('kalan_tutar') or 0)),
                'odeme_tipi': d.get('odeme_tipi') or '—',
                'muhasebe': (d.get('durum') or '—').replace('_', ' '),
            })

    ort_vade = round(sum(vadeler) / len(vadeler)) if vadeler else None
    max_vade = max(vadeler) if vadeler else None
    son_siparis = '—'
    son_sip_gun = None
    if siparisler_prod:
        s = siparisler_prod[0]
        son_siparis = f"{(s.get('olusturma_tarihi') or '')[:10]} · {s.get('siparis_no') or '—'}"
        gf = _gun_fark((s.get('olusturma_tarihi') or '')[:10])
        son_sip_gun = gf.days if gf else None
    son_gorusme = son_ziyaret = '—'
    son_gorusme_gun = None
    if gorusmeler:
        g0 = gorusmeler[0]
        son_gorusme = f"{g0.get('tarih')} — {g0.get('tip')}"
        gf = _gun_fark(g0.get('tarih'))
        son_gorusme_gun = gf.days if gf else None
        for g in gorusmeler:
            if (g.get('tip') or '').upper().replace('İ', 'I') == 'ZIYARET':
                son_ziyaret = g.get('tarih') or '—'
                break
    son_tahsilat = '—'
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        tr = con.execute(
            "SELECT alinan_tarih, alinan_tutar FROM mo_tahsilat_kayit WHERE cari_id=? AND durum='ONAYLANDI' ORDER BY alinan_tarih DESC LIMIT 1",
            (cari_id,),
        ).fetchone()
        if tr and tr['alinan_tarih']:
            son_tahsilat = f"{tr['alinan_tarih'][:10]} · {_fmt_tl(float(tr['alinan_tutar'] or 0))}"

    ilk_calisma = min(ilk_tarih) if ilk_tarih else '—'
    if gorusmeler:
        gt = [g['tarih'] for g in gorusmeler if g.get('tarih')]
        if gt and (ilk_calisma == '—' or min(gt) < ilk_calisma):
            ilk_calisma = min(gt)

    vade_uyari = None
    if ort_vade and siparisler_prod and siparisler_prod[0].get('vade_gun') is not None:
        try:
            sv = int(siparisler_prod[0]['vade_gun'])
            if sv > ort_vade:
                vade_uyari = f'Son sipariş talebi {sv} gün — ortalamanın {sv - ort_vade} gün üzerinde'
        except (TypeError, ValueError):
            pass

    acik_num_asamalar: list[str] = []
    eski_acik = None
    if numuneler_prod:
        acik_rows = [n for n in numuneler_prod if (n.get('durum') or '').upper() not in
                     ('REDDEDILDI', 'IPTAL', 'TAMAMLANDI', 'RECETE_MERKEZINE_AKTARILDI')]
        if acik_rows:
            eski_acik = min((n.get('olusturma_tarihi') or '')[:10] for n in acik_rows if n.get('olusturma_tarihi'))
            for n in acik_rows[:5]:
                _, dt = _numune_durum_metin(n.get('durum'))
                acik_num_asamalar.append(dt)

    acik_sip_durumlar: list[str] = []
    for s in siparisler_prod:
        if (s.get('durum') or '').upper() not in ('TAMAMLANDI', 'REDDEDILDI', 'IPTAL', 'TASLAK'):
            _, dt = _siparis_durum_metin(s.get('durum'), s.get('tahsilat_durumu'))
            acik_sip_durumlar.append(dt)

    urun_renk = None
    urun_cnt: dict[str, int] = {}
    for n in numuneler_prod:
        u = n.get('urun_adi') or n.get('urun_tipi')
        if u:
            urun_cnt[str(u)] = urun_cnt.get(str(u), 0) + 1
    if urun_cnt:
        top = max(urun_cnt.items(), key=lambda x: x[1])
        urun_renk = {'en_cok_urun': top[0], 'adet': top[1]}

    return {
        'cari_id': cari_id,
        'unvan': nc['unvan'],
        'cari_kod': nc['cari_kod'],
        'golden_master': get_golden_master_snapshot(con, cari_id),
        'kimlik': {
            'unvan': nc['unvan'],
            'cari_kod': nc['cari_kod'],
            'sorumlu': (ana or {}).get('kullanici_adi') or '—',
            'ilk_calisma': ilk_calisma,
            'son_gorusme': son_gorusme,
            'son_ziyaret': son_ziyaret,
            'son_siparis': son_siparis,
            'son_tahsilat': son_tahsilat,
        },
        'durum': {
            'acik_siparis': acik_sip_adet or '—',
            'acik_numune': acik_num or '—',
            'beklenen_tahsilat': _fmt_tl(plan_top + yakin_top + bugun_top) if (plan_top + yakin_top + bugun_top) else '—',
            'geciken_tahsilat': _fmt_tl(geciken_top) if geciken_top else '—',
            'ortalama_vade': f'{ort_vade} gün' if ort_vade is not None else '—',
            'en_uzun_vade': f'{max_vade} gün' if max_vade is not None else '—',
            'son_siparis_gun': son_sip_gun if son_sip_gun is not None else '—',
            'son_gorusme_gun': son_gorusme_gun if son_gorusme_gun is not None else '—',
        },
        'son_gorusmeler': gorusmeler[:5],
        'musteri_sozleri': musteri_sozleri,
        'bizim_sozlerimiz': bizim_sozler,
        'tahsilat_vade': {
            'planlanan': _fmt_tl(plan_top),
            'bugun': _fmt_tl(bugun_top) if bugun_top else '—',
            'yaklasan': _fmt_tl(yakin_top) if yakin_top else '—',
            'geciken': _fmt_tl(geciken_top) if geciken_top else '—',
            'tahsil_edildi': _fmt_tl(tahsil_edildi) if tahsil_edildi else '—',
            'ortalama_vade': f'{ort_vade} gün' if ort_vade is not None else '—',
            'en_uzun_vade': f'{max_vade} gün' if max_vade is not None else '—',
            'son_odeme_sozu': son_odeme_sozu,
            'vade_uyari': vade_uyari,
        },
        'acik_numune': {'adet': acik_num or '—', 'en_eski': eski_acik or '—', 'asamalar': acik_num_asamalar},
        'acik_siparis': {
            'adet': acik_sip_adet or '—',
            'tutar': _fmt_tl(acik_sip_tutar) if acik_sip_tutar else '—',
            'durumlar': acik_sip_durumlar[:5],
        },
        'tab_satis': tab_satis,
        'tab_numune': tab_numune,
        'tab_tahsilat': tab_tahsilat,
        'urun_renk': urun_renk,
    }


def cari_liste(con: sqlite3.Connection, uid: int, yk: set[str] | None = None) -> list[dict]:
    if not can_cari360_dosya_ekrani(yk):
        raise Cari360DosyaError('Cari 360 ekranına erişim yetkiniz yok.', 403)
    rows = con.execute(
        'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari ORDER BY aktif DESC, unvan',
    ).fetchall()
    from modules.nexgen.cari360_yetki import can_cari360_view_all
    if can_cari360_view_all(yk):
        return [dict(r) for r in rows]
    return [dict(r) for r in rows if can_view_cari(con, uid, int(r['id']), yk)]
