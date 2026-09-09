# -*- coding: utf-8 -*-
"""Üretim Plan — CPS SQLite plan kayıtları."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from db import get_conn
from modules.planlama.uretim_plan_service import parse_cift_quantity

PLAN_DONEMLERI = ('bu_hafta', 'gelecek_hafta', 'bu_ay', '3_ay', 'gecmis')
GEREKCE_SECENEKLERI = (
    'Müşteri Acil', 'Termin', 'Hammadde Hazır', 'Kalıp Boş',
    'Ödeme/Ticari Öncelik', 'Üretim Uygunluğu', 'Diğer',
)


def _ensure_table(con: sqlite3.Connection) -> None:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='uretim_model_plan'"
    ).fetchone()
    if row:
        return
    import importlib.util
    import os
    mig = os.path.join(
        os.path.dirname(__file__), '..', '..', 'migrations', '158_uretim_model_plan.py'
    )
    spec = importlib.util.spec_from_file_location('mig158', mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ensure_table(con)


def canonical_key(sip_no, sip_harinx, mamul_skod, rkod) -> str:
    return f'{int(sip_no)}|{int(sip_harinx)}|{mamul_skod}|{int(rkod or 0)}'


def parse_canonical_key(key: str) -> dict:
    parts = (key or '').split('|')
    if len(parts) != 4:
        raise ValueError('Geçersiz canonical key')
    return {
        'sip_no': int(parts[0]),
        'sip_harinx': int(parts[1]),
        'mamul_skod': parts[2],
        'rkod': int(parts[3]),
    }


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d['canonical_key'] = canonical_key(
        d['sip_no'], d['sip_harinx'], d['mamul_skod'], d['rkod']
    )
    return d


def _week_bounds(ref: date | None = None) -> tuple[date, date]:
    ref = ref or date.today()
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def donem_aralik(donem: str, ref: date | None = None) -> tuple[date | None, date | None]:
    ref = ref or date.today()
    if donem == 'bu_hafta':
        return _week_bounds(ref)
    if donem == 'gelecek_hafta':
        s, _ = _week_bounds(ref)
        s = s + timedelta(days=7)
        return s, s + timedelta(days=6)
    if donem == 'bu_ay':
        start = ref.replace(day=1)
        if ref.month == 12:
            end = date(ref.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(ref.year, ref.month + 1, 1) - timedelta(days=1)
        return start, end
    if donem == '3_ay':
        end = ref + timedelta(days=92)
        return ref, end
    if donem == 'gecmis':
        return None, ref - timedelta(days=1)
    return None, None


def _overlap(plan_bas, plan_bit, d_start, d_end) -> bool:
    if not plan_bas and not plan_bit:
        return True
    try:
        pb = datetime.strptime((plan_bas or plan_bit)[:10], '%Y-%m-%d').date() if (plan_bas or plan_bit) else None
        pe = datetime.strptime((plan_bit or plan_bas)[:10], '%Y-%m-%d').date() if (plan_bit or plan_bas) else pb
    except ValueError:
        return True
    if d_start is None and d_end is None:
        return True
    if d_start is None:
        return pe <= d_end if pe else False
    if d_end is None:
        return pb >= d_start if pb else False
    if not pb or not pe:
        return True
    return not (pe < d_start or pb > d_end)


def liste_aktif_planlar(donem: str = 'bu_hafta') -> list[dict]:
    con = get_conn()
    try:
        _ensure_table(con)
        rows = con.execute("""
            SELECT * FROM uretim_model_plan
             WHERE aktif = 1
             ORDER BY oncelik ASC, plan_baslangic ASC, id ASC
        """).fetchall()
        d_start, d_end = donem_aralik(donem)
        out = []
        for r in rows:
            d = _row_to_dict(r)
            if donem == 'gecmis':
                pb = d.get('plan_bitis') or d.get('plan_baslangic')
                if pb:
                    try:
                        if datetime.strptime(pb[:10], '%Y-%m-%d').date() >= date.today():
                            continue
                    except ValueError:
                        pass
            elif not _overlap(d.get('plan_baslangic'), d.get('plan_bitis'), d_start, d_end):
                continue
            out.append(d)
        return out
    finally:
        con.close()


def plan_get(plan_id: int) -> dict | None:
    con = get_conn()
    try:
        _ensure_table(con)
        row = con.execute(
            'SELECT * FROM uretim_model_plan WHERE id=?', (int(plan_id),)
        ).fetchone()
        plan = _row_to_dict(row)
        if plan is not None:
            plan['enj_istasyonlar'] = _plan_istasyonlar(
                con, plan['id'], plan.get('enj_istasyon_no')
            )
        return plan
    finally:
        con.close()


ENJ_ALANLARI = (
    'enj_makine_id', 'enj_istasyon_no', 'enj_slot', 'enj_kalip_id',
    'enj_kalip_kod', 'enj_aktif_goz', 'enj_kalip_basi_cift', 'enj_tur_cift',
    'enj_gunluk_tur_plan', 'enj_gunluk_kapasite',
    'enj_plan_baslangic', 'enj_plan_bitis',
    'enj_tahmini_gun', 'enj_planlanacak_cift',
    'enj_calisma_modu', 'enj_hafta_sonu_calisma', 'enj_hafta_sonu_vardiya',
    'enj_kapasite_snapshot',
)

ENJ_ISTASYON_TABLO = 'uretim_model_plan_enj_istasyon'


def _normalize_istasyon_list(value) -> list[int]:
    """İstasyon değerini tekrarsız, sıralı int listesine çevir.

    None/'' -> [], 7 veya '7' -> [7], '7,8' -> [7, 8], [7, '8'] -> [7, 8].
    Parse edilemeyen parçalar atılır; eski/bozuk kayıtlar hata üretmez.
    """
    if value is None or value == '':
        return []
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        parts = [value]
    else:
        parts = str(value).replace(';', ',').split(',')
    bulunan: set[int] = set()
    for parca in parts:
        if parca is None:
            continue
        metin = str(parca).strip()
        if not metin:
            continue
        try:
            no = int(metin)
        except (ValueError, TypeError):
            continue
        if no > 0:
            bulunan.add(no)
    return sorted(bulunan)


def _istasyon_no_db_degeri(istasyonlar: list[int]):
    """Normalize listeyi enj_istasyon_no kolonunun saklama biçimine çevir.

    Kolon INTEGER affinity: tek istasyon '7' -> 7 olarak, çoklu istasyon
    '7,8' metin olarak saklanır. Böylece tek istasyonlu legacy sorgular
    (enj_istasyon_no = ?) bozulmadan çalışmaya devam eder.
    """
    if not istasyonlar:
        return None
    if len(istasyonlar) == 1:
        return istasyonlar[0]
    return ','.join(str(no) for no in istasyonlar)


def _payload_istasyonlar(payload: dict) -> list[int]:
    """Payload'daki istasyon seçimini tek noktadan çöz.

    Öncelik enj_istasyonlar (UI listesi); yoksa kayıtlı enj_istasyon_no.
    """
    istasyonlar = _normalize_istasyon_list(payload.get('enj_istasyonlar'))
    if not istasyonlar:
        istasyonlar = _normalize_istasyon_list(payload.get('enj_istasyon_no'))
    return istasyonlar


def _istasyon_tablosu_var(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (ENJ_ISTASYON_TABLO,),
    ).fetchone())


def _sync_enj_istasyonlar(con, plan_id, makine_id, slot, istasyonlar) -> None:
    """Planın istasyon satırlarını child tabloyla eşitle.

    _check_conflicts, _load_raw_plans ve genel plan sorguları çoklu istasyonu
    bu tablodan okur; virgüllü enj_istasyon_no tek başına görünmediği için
    çoklu rezervasyon yazılmazsa sonraki planlar çakışmayı fark etmez.
    """
    if not _istasyon_tablosu_var(con):
        return
    con.execute(
        f'DELETE FROM {ENJ_ISTASYON_TABLO} WHERE plan_id=?', (int(plan_id),)
    )
    slot = (slot or '').upper()
    if not istasyonlar or not makine_id or slot not in ('A', 'B'):
        return
    con.executemany(
        f'INSERT INTO {ENJ_ISTASYON_TABLO} '
        '(plan_id, enj_makine_id, enj_slot, istasyon_no) VALUES (?,?,?,?)',
        [(int(plan_id), int(makine_id), slot, int(no)) for no in istasyonlar],
    )


ENJ_PAYLOAD_ANAHTARLARI = frozenset(ENJ_ALANLARI) | {
    'enj_istasyonlar', 'enj_kalip_adedi', 'has_enjeksiyon',
}


def _enj_payload_dokunuldu(payload: dict) -> bool:
    """Payload enjeksiyon rezervasyon alanlarına dokunuyor mu."""
    return any(k in payload for k in ENJ_PAYLOAD_ANAHTARLARI)


def _enj_update_payload(payload: dict, mevcut: dict) -> dict:
    """Güncelleme doğrulaması için payload'ı mevcut kayıtla tamamla.

    Kısmi güncellemede payload'da olmayan enjeksiyon alanları mevcut kayıttan
    gelir; böylece doğrulama eksik veriyle yanlış tetiklenmez.
    """
    birlesik = dict(mevcut)
    birlesik.update(payload)
    if 'has_enjeksiyon' not in payload:
        birlesik['has_enjeksiyon'] = bool(
            birlesik.get('enj_makine_id') or birlesik.get('enj_plan_baslangic')
        )
    if 'enj_istasyonlar' not in payload:
        birlesik['enj_istasyonlar'] = _payload_istasyonlar(birlesik)
    return birlesik


def _plan_istasyonlar(con, plan_id, enj_istasyon_no) -> list[int]:
    """Planın istasyonlarını child tablodan, yoksa legacy kolondan oku."""
    if _istasyon_tablosu_var(con):
        satirlar = con.execute(
            f'SELECT istasyon_no FROM {ENJ_ISTASYON_TABLO} '
            'WHERE plan_id=? ORDER BY istasyon_no', (int(plan_id),)
        ).fetchall()
        if satirlar:
            return _normalize_istasyon_list([s[0] for s in satirlar])
    return _normalize_istasyon_list(enj_istasyon_no)


def _resolve_canonical_skod_for_guard(payload: dict, mevcut: dict | None) -> str | None:
    """Save guard için canonical mamul_skod'u Korgun'dan çöz.

    Yeni plan  → payload sip_no+sip_harinx+rkod kullanılır.
    Mevcut plan → DB kaydındaki sip_no+sip_harinx+rkod kullanılır
                  (istemci payload'ı sipariş anahtarını değiştiremez).

    Korgun erişilemezse ValueError fırlatır (fail-closed).
    """
    from modules.planlama.uretim_plan_service import (
        resolve_canonical_mamul_skod, CanonicalResolveError,
    )

    if mevcut is not None:
        # Update: canonical anahtarı DB'den — istemci değiştiremez
        sip_no  = mevcut.get('sip_no')
        sip_har = mevcut.get('sip_harinx')
        rkod    = mevcut.get('rkod', 0)
        client_skod = mevcut.get('mamul_skod', '')   # DB değeri = doğru
        # Update'te sipariş kimliği değiştirilemez
        if (payload.get('sip_no') and int(payload['sip_no']) != int(sip_no or 0)) or \
           (payload.get('mamul_skod') and
            payload['mamul_skod'].strip().upper() != (client_skod or '').strip().upper()):
            raise ValueError(
                'Plan güncellemede sipariş veya model değiştirilemez. '
                'Yeni plan oluşturun.'
            )
    else:
        # Yeni plan
        sip_no  = payload.get('sip_no')
        sip_har = payload.get('sip_harinx')
        rkod    = payload.get('rkod', 0)
        client_skod = payload.get('mamul_skod', '')

    if not sip_no or sip_har is None:
        return None  # zorunlu anahtar yoksa zaten başka validation yakalar

    try:
        return resolve_canonical_mamul_skod(sip_no, sip_har, client_skod, rkod)
    except CanonicalResolveError as exc:
        raise ValueError(str(exc)) from exc


def _validate_enj_kalip_model_match(con: sqlite3.Connection, payload: dict,
                                     mevcut: dict | None = None) -> None:
    """Kalıp-model eşleşmesini Korgun canonical kaynağıyla doğrula.

    Mod ayrımı:
      - kalip_mode='manuel' ve kalip_id YOK  → manuel akış, liste guard atlanır.
      - kalip_mode='liste' (veya belirtilmemiş) ve kalip_id YOK → BLOCKED
        (liste modunda kalıp seçimi zorunlu).
      - kalip_mode='manuel' ve kalip_id VAR → BLOCKED (mod çelişkisi).
      - kalip_mode='liste' ve kalip_id VAR → canonical model eşleşmesi zorunlu.

    Update'te kalıp değişmiyorsa geriye uyumluluk için atlanır.
    Canonical Korgun erişilemezse fail-closed.
    """
    kalip_mode = (payload.get('kalip_mode') or 'liste').lower().strip()
    kalip_id   = payload.get('enj_kalip_id')

    # has_enjeksiyon False ise kalıp validasyonu geçersiz
    if not payload.get('has_enjeksiyon'):
        return

    if kalip_mode == 'manuel':
        # Manuel mod: kalip_id olmamalı
        if kalip_id:
            raise ValueError(
                'Manuel kalıp modunda liste kalıp ID\'si (enj_kalip_id) gönderilemez. '
                'Liste guard bypass girişimi reddedildi.'
            )
        # Manuel kalıp kodu zorunlu
        kalip_kod_manuel = (payload.get('enj_kalip_kod') or '').strip()
        if not kalip_kod_manuel:
            raise ValueError('Manuel kalıp modunda enj_kalip_kod boş olamaz.')
        return  # Manuel mod doğrulaması geçti

    # Liste modu (varsayılan)
    if not kalip_id:
        raise ValueError(
            'Liste kalıp modunda enj_kalip_id zorunludur. '
            'Manuel kalıp için kalip_mode=manuel kullanın.'
        )

    # Update: sipariş/model değişikliği koruması — kalıp skip'inden ÖNCE
    if mevcut is not None:
        db_skod    = (mevcut.get('mamul_skod') or '').strip().upper()
        pay_skod   = (payload.get('mamul_skod') or '').strip().upper()
        if pay_skod and db_skod and pay_skod != db_skod:
            raise ValueError(
                'Plan güncellemede sipariş modeli değiştirilemez. '
                'Yeni plan oluşturun.'
            )

    # Update: kalıp değişmiyorsa geriye uyumluluk (model kontrolü geçtikten sonra)
    if mevcut is not None:
        mevcut_kid = mevcut.get('enj_kalip_id')
        if mevcut_kid and int(mevcut_kid) == int(kalip_id):
            return  # kalıp aynı kaldı — eski kayıt bozulmasın

    # Canonical mamul_skod: Korgun'dan çöz (istemci beyanına güvenmiyoruz)
    canonical_skod = _resolve_canonical_skod_for_guard(payload, mevcut)
    if not canonical_skod:
        # Canonical çözülemedi ama sip_no da yoksa — diğer validation yakalar
        return

    # Kalıp master'dan model_kod oku
    kalip_row = con.execute(
        'SELECT model_kod, aktif FROM enj_kalip WHERE id=?', (int(kalip_id),)
    ).fetchone()
    if not kalip_row:
        raise ValueError(f'Seçilen kalıp (id={kalip_id}) sistemde bulunamadı.')
    if not kalip_row['aktif']:
        raise ValueError(f'Seçilen kalıp (id={kalip_id}) pasif durumdadır.')

    kalip_model = (kalip_row['model_kod'] or '').strip().upper()
    canon_upper = canonical_skod.strip().upper()

    if kalip_model and kalip_model != canon_upper:
        raise ValueError(
            f'Seçilen kalıp sipariş modeliyle uyumlu değil. '
            f'Kalıp modeli: {kalip_model}, Sipariş (Korgun canonical): {canonical_skod}.'
        )


def _validate_enj_required(payload: dict) -> None:
    """has_enjeksiyon=True ürünlerde enjeksiyon rezervasyon alanlarının zorunlu kontrolü.

    Sadece payload'da 'has_enjeksiyon' anahtarı açıkça True ise devreye girer.
    Yoksa (False veya eksik) geçer — enjeksiyonsuz ürünler serbest.
    """
    if not payload.get('has_enjeksiyon'):
        return
    required_enj = {
        'enj_makine_id': 'Enjeksiyon makine seçimi',
        'enj_slot': 'Enjeksiyon taraf (A/B)',
        'enj_kalip_id': 'Enjeksiyon kalıp',
        'enj_plan_baslangic': 'Enjeksiyon başlangıç tarihi',
        'enj_plan_bitis': 'Enjeksiyon bitiş tarihi',
    }
    missing = [lbl for k, lbl in required_enj.items() if not payload.get(k)]
    if missing:
        raise ValueError('Enjeksiyonlu plan için eksik: ' + ', '.join(missing))

    # Enjeksiyon başlangıç < bitiş
    bas = payload.get('enj_plan_baslangic') or ''
    bit = payload.get('enj_plan_bitis') or ''
    if bas and bit and str(bas) >= str(bit):
        raise ValueError('Enjeksiyon bitiş tarihi, başlangıçtan sonra olmalı')

    # Kalıp adedi kadar istasyonun tarih aralığında uygun olduğunu doğrula
    enj_ist_list = _payload_istasyonlar(payload)
    kalip_adedi = int(payload.get('enj_kalip_adedi') or payload.get('enj_aktif_goz') or 0)
    # kalip_adedi 0 ise kontrol atlama (eski kayıtlar için geriye dönük uyumluluk)
    if kalip_adedi > 0 and len(enj_ist_list) < kalip_adedi:
        raise ValueError(
            f'Seçilen istasyon sayısı ({len(enj_ist_list)}) kalıp adedinden ({kalip_adedi}) az. '
            'Lütfen tüm istasyonların planlama döneminde uygun olduğunu doğrulayın.'
        )

def _validate_general_after_enj(payload: dict) -> None:
    """Genel plan başlangıcı enjeksiyon bitişinden önce olamaz."""
    enj_bit = payload.get('enj_plan_bitis') or ''
    plan_bas = payload.get('plan_baslangic') or ''
    if not enj_bit or not plan_bas:
        return
    # Karşılaştırma: ISO tarih/datetime string — ilk 10 karakter yeterli
    if str(plan_bas)[:10] < str(enj_bit)[:10]:
        raise ValueError(
            'Genel plan başlangıcı, enjeksiyon tamamlanmadan önce olamaz. '
            f'Enjeksiyon bitiş: {str(enj_bit)[:16]}, Plan başlangıç: {str(plan_bas)[:10]}'
        )


def _enj_vals(payload: dict) -> dict:
    """Payload'dan enj_ alanlarını çek; tip dönüşümü yap."""
    out = {}
    int_fields = {'enj_makine_id', 'enj_kalip_id',
                  'enj_aktif_goz', 'enj_kalip_basi_cift', 'enj_tur_cift',
                  'enj_gunluk_tur_plan', 'enj_gunluk_kapasite'}
    real_fields = {'enj_tahmini_gun', 'enj_planlanacak_cift'}
    for k in ENJ_ALANLARI:
        if k == 'enj_istasyon_no':
            # Tek int'e zorlanırsa çoklu seçim ('7,8') NULL'a düşer.
            out[k] = _istasyon_no_db_degeri(_payload_istasyonlar(payload))
            continue
        v = payload.get(k)
        if v is not None and v != '':
            if k in int_fields:
                try:
                    v = int(v)
                except (ValueError, TypeError):
                    v = None
            elif k in real_fields:
                try:
                    v = float(v)
                except (ValueError, TypeError):
                    v = None
        else:
            v = None
        out[k] = v
    return out


def _validate_enj_istasyon_availability(con, payload: dict,
                                        haric_plan_id: int | None = None) -> None:
    """Kayıt öncesinde seçili enjeksiyon istasyonlarını ayrı ayrı doğrula.

    Kontroller:
    1. Seçili istasyon sayısı == kalıp adedi
    2. Her istasyon numarası makinenin istasyon_sayisi sınırında
    3. Seçili tarih aralığında her istasyon için çakışma yok

    haric_plan_id verilirse o plan çakışma taramasından çıkarılır; güncelleme
    yolunda plan kendi rezervasyonuyla çakışmış gibi görünmez.
    """
    from modules.planlama.enj_kapasite_motor import _check_conflicts, _parse_dt

    makine_id  = int(payload.get('enj_makine_id') or 0)
    slot       = (payload.get('enj_slot') or '').upper()
    bas_str    = payload.get('enj_plan_baslangic') or ''
    bit_str    = payload.get('enj_plan_bitis')    or ''
    if not makine_id or not slot or not bas_str or not bit_str:
        return  # zorunlu alan kontrolü zaten _validate_enj_required'de

    ist_list = _payload_istasyonlar(payload)
    kalip_adedi = int(payload.get('enj_kalip_adedi') or 0)

    # 1. Sayı kontrolü
    if kalip_adedi > 0 and len(ist_list) != kalip_adedi:
        raise ValueError(
            f'Seçili istasyon sayısı ({len(ist_list)}) kalıp adediyle ({kalip_adedi}) uyuşmuyor. '
            'İST listesi ve kalıp adedi eşit olmalı.'
        )
    if not ist_list:
        return

    # 2. Makine istasyon_sayisi sınır kontrolü
    mk_row = con.execute(
        'SELECT istasyon_sayisi FROM enj_makine WHERE id=? AND aktif=1', (makine_id,)
    ).fetchone()
    if not mk_row:
        raise ValueError(f'Makine id={makine_id} bulunamadı veya pasif.')
    ist_max = int(mk_row['istasyon_sayisi'])
    gecersiz = [i for i in ist_list if i < 1 or i > ist_max]
    if gecersiz:
        raise ValueError(
            f'İstasyon no {gecersiz} makine kapasitesi dışında (1–{ist_max}).'
        )

    # 3. Tarih aralığında çakışma kontrolü
    try:
        bas_dt = _parse_dt(bas_str)
        bit_dt = _parse_dt(bit_str)
    except (ValueError, TypeError):
        return  # tarih parse hatası zaten başka kontrol yakalar

    conflicts = _check_conflicts(
        con, makine_id, slot, ist_list, bas_dt, bit_dt,
        haric_plan_id=haric_plan_id,
    )
    if conflicts:
        cnames = ', '.join(
            f"İST{c.get('enj_istasyon_no','?')} (Plan #{c.get('id','?')})"
            for c in conflicts[:3]
        )
        raise ValueError(
            f'Seçilen tarih aralığında çakışma tespit edildi: {cnames}. '
            'Lütfen uygun bir başlangıç tarihi seçin.'
        )


def _planned_qty_from_row(row: dict) -> int | None:
    """Aktif plandan güvenilir planlanan çift miktarını çöz.

    Öncelik: enj_planlanacak_cift → enj_kapasite_snapshot.planlanacak_cift.
    Çözülemezse None (legacy belirsizlik).
    """
    raw = row.get('enj_planlanacak_cift')
    if raw is not None and raw != '':
        try:
            return parse_cift_quantity(raw, field_label='Planlanacak çift')
        except ValueError:
            pass

    snap_raw = row.get('enj_kapasite_snapshot')
    if snap_raw:
        try:
            snap = json.loads(snap_raw) if isinstance(snap_raw, str) else snap_raw
            if isinstance(snap, dict) and snap.get('planlanacak_cift') is not None:
                return parse_cift_quantity(
                    snap['planlanacak_cift'], field_label='Planlanacak çift',
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


def _sum_already_planned(
    con: sqlite3.Connection,
    sip_no: int,
    sip_harinx: int,
    mamul_skod: str,
    rkod: int,
    *,
    exclude_plan_id: int | None = None,
) -> tuple[int, list[int]]:
    """Aynı kanonik sipariş kalemi için aktif planların planlanan çift toplamı."""
    sql = """
        SELECT id, enj_planlanacak_cift, enj_kapasite_snapshot
          FROM uretim_model_plan
         WHERE aktif = 1
           AND sip_no = ? AND sip_harinx = ? AND mamul_skod = ? AND rkod = ?
    """
    params: list = [int(sip_no), int(sip_harinx), mamul_skod, int(rkod or 0)]
    if exclude_plan_id is not None:
        sql += ' AND id <> ?'
        params.append(int(exclude_plan_id))

    already = 0
    unresolved: list[int] = []
    for row in con.execute(sql, params).fetchall():
        d = dict(row)
        pq = _planned_qty_from_row(d)
        if pq is None:
            unresolved.append(int(d['id']))
        else:
            already += pq
    return already, unresolved


def _quantity_error_message(
    *,
    remaining: int,
    requested: int,
    order_total: int,
) -> str:
    if requested > order_total:
        return f'Sipariş miktarı {order_total} çift. {requested} çift planlanamaz.'
    return f'Kalan miktar {remaining} çift. {requested} çift planlanamaz.'


def _validate_enj_plan_quantity(
    con: sqlite3.Connection,
    payload: dict,
    order_total: int,
    *,
    exclude_plan_id: int | None = None,
) -> dict:
    """Enjeksiyonlu plan create/update — kalan miktar guard.

    order_total: server-side doğrulanmış sipariş kalemi toplamı (çift).
    """
    if not payload.get('has_enjeksiyon'):
        return {}

    requested = parse_cift_quantity(
        payload.get('enj_planlanacak_cift'),
        field_label='Planlanacak çift',
    )
    order_total_int = parse_cift_quantity(order_total, field_label='Sipariş miktarı')

    already, unresolved = _sum_already_planned(
        con,
        int(payload['sip_no']),
        int(payload['sip_harinx']),
        payload['mamul_skod'],
        int(payload.get('rkod') or 0),
        exclude_plan_id=exclude_plan_id,
    )
    if unresolved:
        ids = ', '.join(f'#{i}' for i in unresolved[:5])
        raise ValueError(
            'Bu sipariş kaleminde miktarı çözümlenemeyen legacy plan(lar) var '
            f'({ids}). Kalan miktar güvenli hesaplanamıyor; plan kaydı yapılamaz.'
        )

    remaining = order_total_int - already
    if requested > order_total_int:
        raise ValueError(_quantity_error_message(
            remaining=remaining, requested=requested, order_total=order_total_int,
        ))
    if requested > remaining:
        raise ValueError(_quantity_error_message(
            remaining=remaining, requested=requested, order_total=order_total_int,
        ))

    remaining_after = remaining - requested
    return {
        'order_total_quantity': order_total_int,
        'already_planned_quantity': already,
        'remaining_quantity': remaining,
        'requested_quantity': requested,
        'remaining_after_save': remaining_after,
        'siparis_toplam_miktar': order_total_int,
        'planlanmis_miktar': already,
        'kalan_miktar': remaining,
        'talep_miktar': requested,
        'kayit_sonrasi_kalan': remaining_after,
    }


def _resolve_order_total_for_payload(payload: dict, order_total: int | None) -> int:
    if order_total is not None:
        return parse_cift_quantity(order_total, field_label='Sipariş miktarı')
    from modules.planlama.uretim_plan_service import resolve_order_line_quantity

    info = resolve_order_line_quantity(
        payload['sip_no'],
        payload['sip_harinx'],
        payload['mamul_skod'],
        payload.get('rkod') or 0,
    )
    return int(info['order_total_quantity'])


def plan_ekle(payload: dict, user_id: int, *, order_total: int | None = None) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        dup = con.execute("""
            SELECT id FROM uretim_model_plan
             WHERE aktif=1 AND sip_no=? AND sip_harinx=? AND mamul_skod=? AND rkod=? AND plan_donemi=?
        """, (
            int(payload['sip_no']), int(payload['sip_harinx']),
            payload['mamul_skod'], int(payload.get('rkod') or 0),
            payload['plan_donemi'],
        )).fetchone()
        if dup:
            raise ValueError('Bu model+renk bu plan döneminde zaten planlı')

        # ENJ validation: enjeksiyonlu üründe rezervasyon alanları zorunlu
        _validate_enj_required(payload)

        # MOLD GUARD: liste modunda kalıp modeli canonical mamul_skod ile eşleşmeli
        _validate_enj_kalip_model_match(con, payload, mevcut=None)

        qty_meta: dict = {}
        if payload.get('has_enjeksiyon'):
            ot = _resolve_order_total_for_payload(payload, order_total)
            qty_meta = _validate_enj_plan_quantity(con, payload, ot)

        # Genel plan başlangıcı enjeksiyon bitişinden önce olamaz
        _validate_general_after_enj(payload)

        # Enjeksiyonlu plan: seçili istasyonların gerçek çakışma ve varlık kontrolü
        if payload.get('has_enjeksiyon'):
            _validate_enj_istasyon_availability(con, payload)

        istasyonlar = _payload_istasyonlar(payload)
        enj = _enj_vals(payload)
        enj_cols = ', '.join(enj.keys())
        enj_ph = ', '.join(['?'] * len(enj))

        cur = con.execute(f"""
            INSERT INTO uretim_model_plan (
                sip_no, sip_harinx, mamul_skod, rkod,
                model_adi, renk_adi, miktar, termin,
                plan_donemi, plan_baslangic, plan_bitis,
                oncelik, plan_gerekce, plan_notu,
                aktif, created_by,
                {enj_cols}
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,{enj_ph})
        """, (
            int(payload['sip_no']), int(payload['sip_harinx']),
            payload['mamul_skod'], int(payload.get('rkod') or 0),
            payload.get('model_adi'), payload.get('renk_adi'),
            payload.get('miktar'), payload.get('termin'),
            payload['plan_donemi'],
            payload.get('plan_baslangic'), payload.get('plan_bitis'),
            int(payload.get('oncelik') or 3),
            payload.get('plan_gerekce'), payload.get('plan_notu'),
            int(user_id),
            *enj.values(),
        ))
        _sync_enj_istasyonlar(
            con, cur.lastrowid, enj.get('enj_makine_id'),
            enj.get('enj_slot'), istasyonlar,
        )
        con.commit()
        out = plan_get(cur.lastrowid)
        if qty_meta:
            out['_quantity_meta'] = qty_meta
        return out
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def plan_guncelle(
    plan_id: int,
    payload: dict,
    user_id: int,
    *,
    order_total: int | None = None,
) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        mevcut = plan_get(plan_id)
        if not mevcut or not mevcut.get('aktif'):
            raise ValueError('Plan bulunamadı')

        donem = payload.get('plan_donemi', mevcut['plan_donemi'])
        dup = con.execute("""
            SELECT id FROM uretim_model_plan
             WHERE aktif=1 AND id<>? AND sip_no=? AND sip_harinx=? AND mamul_skod=? AND rkod=? AND plan_donemi=?
        """, (
            int(plan_id), mevcut['sip_no'], mevcut['sip_harinx'],
            mevcut['mamul_skod'], mevcut['rkod'], donem,
        )).fetchone()
        if dup:
            raise ValueError('Bu model+renk bu plan döneminde zaten planlı')

        birlesik = _enj_update_payload(payload, mevcut)
        # Genel plan başlangıcı genel bir alan; enjeksiyon alanlarına
        # dokunulmasa da enjeksiyon bitişinin önüne çekilemez.
        _validate_general_after_enj(birlesik)

        qty_meta: dict = {}
        enj = None
        istasyonlar = None
        if _enj_payload_dokunuldu(payload):
            # plan_ekle ile aynı iş kuralları
            _validate_enj_required(birlesik)
            # MOLD GUARD: kalıp değiştiriliyorsa model eşleşmesi zorunlu
            _validate_enj_kalip_model_match(con, birlesik, mevcut=mevcut)
            if birlesik.get('has_enjeksiyon'):
                ot = _resolve_order_total_for_payload(birlesik, order_total)
                qty_meta = _validate_enj_plan_quantity(
                    con, birlesik, ot, exclude_plan_id=int(plan_id),
                )
                _validate_enj_istasyon_availability(
                    con, birlesik, haric_plan_id=int(plan_id)
                )
            istasyonlar = _payload_istasyonlar(birlesik)
            enj = _enj_vals(birlesik)

        set_parcalari = [
            'plan_donemi=?', 'plan_baslangic=?', 'plan_bitis=?',
            'oncelik=?', 'plan_gerekce=?', 'plan_notu=?',
        ]
        args = [
            donem,
            payload.get('plan_baslangic', mevcut.get('plan_baslangic')),
            payload.get('plan_bitis', mevcut.get('plan_bitis')),
            int(payload.get('oncelik', mevcut.get('oncelik') or 3)),
            payload.get('plan_gerekce', mevcut.get('plan_gerekce')),
            payload.get('plan_notu', mevcut.get('plan_notu')),
        ]
        if enj is not None:
            # Enjeksiyona dokunulmadıysa kolonlar UPDATE'e hiç girmez;
            # aksi halde mevcut rezervasyon NULL'a düşerdi.
            set_parcalari += [f'{k}=?' for k in enj]
            args += list(enj.values())

        con.execute(f"""
            UPDATE uretim_model_plan SET
                {', '.join(set_parcalari)},
                updated_at=datetime('now','localtime'), updated_by=?
             WHERE id=?
        """, (*args, int(user_id), int(plan_id)))

        if enj is not None:
            _sync_enj_istasyonlar(
                con, plan_id, enj.get('enj_makine_id'),
                enj.get('enj_slot'), istasyonlar,
            )
        con.commit()
        out = plan_get(plan_id)
        if qty_meta:
            out['_quantity_meta'] = qty_meta
        return out
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def plan_pasif(plan_id: int, user_id: int) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        con.execute("""
            UPDATE uretim_model_plan SET aktif=0,
                updated_at=datetime('now','localtime'), updated_by=?
             WHERE id=? AND aktif=1
        """, (int(user_id), int(plan_id)))
        con.commit()
        return plan_get(plan_id)
    finally:
        con.close()
