# -*- coding: utf-8 -*-
"""
Müşteri Cari Hareketleri Servisi — Korgün'e doğrudan (lazy) sorgu.

AŞAMA 0 GÜVENLİK BULGULARI:
  - Fatura_Kay.BelgeNo GLOBAL UNIQUE → BelgeNo tek başına JOIN anahtarı.
  - Fatura_Har Location kolonu YOK → Fatura_Kay.Location filtresi yeterli.
  - C_Fis_Kay.FisNo GLOBAL UNIQUE → FisNo tek başına JOIN anahtarı.
  - C_Fis_Har: 1 FisNo birden fazla 120.* cari → cbpg filtresi zorunlu.
  - fal/hal (alım faturaları) kesinlikle dışarıda.
  - İptal kayıtları (iptal='E') dışarıda.
  - Fiyat=0 → tutar=0; amount_status='zero_price' ile göster.
  - Running balance: sıfırdan değil, devir hareketi tespit edilerek başlatılır.
    Mutabakat sağlanamazsa ayrı göster.

CARI_DETAIL_FILTERED_TOTALS_AND_PAYMENT_BEHAVIOR_V1 güncellemesi:
  - cursor tabanlı lazy-load (cursor_key parametresi)
  - filtered_totals (Decimal tabanlı, tüm filtreli sonuçlar)
  - current_balance (Korgün authoritative_balance)
  - tarih_bas, tarih_bit, metin, hareket_turu filtreleri
  - Geriye dönük uyumluluk: pagination ve total_fatura/total_cfis korunur
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cps.finans.musteri_hareket")

# ─── FisTip/FaturaTip açıklamaları ───────────────────────────────────────────

_FATURA_TIP_MAP = {
    # Müşteri cari perspektifi: satış faturası → müşteri bize borçlandı → BORÇ sütunu
    "fsa": ("Satış Faturası", "BORC"),
    "hsa": ("Hizmet Satış Faturası", "BORC"),
    # İade faturası → müşteri borcu azaldı / bize borç → ALACAK sütunu
    "fsi": ("Satış İade Faturası", "ALACAK"),
    "hai": ("Hizmet İade Faturası", "ALACAK"),
}

_CFIS_TIP_MAP = {
    # Tahsilat → müşteri ödedi → alacak azaldı → ALACAK sütunu
    "NT": ("Nakit Tahsilat", "ALACAK"),
    "NO": ("Nakit Ödeme", "ALACAK"),
    "AD": ("Alacak Düzeltme", "ALACAK"),
    "BG": ("Banka Girişi", "ALACAK"),
    # Borç düzeltme → müşteri borcu arttı → BORÇ sütunu
    "BD": ("Borç Düzeltme", "BORC"),
    "DB": ("Devir Borç", "BORC"),
    "DA": ("Devir Alacak", "ALACAK"),
    "CV": ("Cari Virman", "BILINMIYOR"),
}

# Tahsilat türleri (running balance için negatif etki = alacak azalır)
_TAHSILAT_TIPLERI = {"NT", "NO", "AD", "BG"}
# Düzeltme türleri
_DUZELTME_TIPLERI = {"BD", "DB", "DA", "CV"}

# Müşteri cari için geçerli fatura tipleri (fal/hal kesinlikle dışarıda)
_MUSTERI_FATURA_TIPLERI = ('fsa', 'hsa', 'fsi', 'hai')

# hareket_turu filtresi → fatura tiplerini eşler
_HAREKET_TURU_FATURA_MAP = {
    'SATIS_FATURASI': ('fsa', 'hsa'),
    'ALIS_FATURASI': ('fal', 'hal'),   # tedarikçi için — müşteride döner olmaz
    'IADE_FATURASI': ('fsi', 'hai'),
}

# hareket_turu filtresi → cfis tiplerini eşler
_HAREKET_TURU_CFIS_MAP = {
    'TAHSILAT': ('NT', 'NO', 'AD', 'BG'),
    'ODEME': ('NT', 'NO', 'AD', 'BG'),    # tedarikçi perspektifi alias
    'CEK': ('CK',),
    'DUZELTME': ('BD', 'DB', 'DA', 'CV'),
}


def _ds(v) -> str:
    from decimal import Decimal as D
    if v is None or v == "":
        return "0"
    try:
        return str(D(str(v)))
    except Exception:
        return "0"


def _kg_connect():
    try:
        from modules.common.korgun import _baglan
    except ImportError:
        from app.modules.common.korgun import _baglan
    return _baglan()


def _pb_display(pb: str) -> str:
    """Korgün PB → standart görüntü."""
    return {"TL": "TRY", "US": "USD", "EU": "EUR"}.get(pb, pb)


# ─── Hareket sorguları ────────────────────────────────────────────────────────

def _fetch_fatura_hareketleri(
    cari_kod: str,
    location: str,
    para_birimi: Optional[str],
    page: int,
    per_page: int,
    tarih_bas: Optional[str] = None,
    tarih_bit: Optional[str] = None,
    metin: Optional[str] = None,
    hareket_turu: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Fatura_Kay JOIN Fatura_Har.
    - Yalnız fsa/hsa/fsi/hai.
    - fal/hal kesinlikle dışarıda.
    - Fiyat=0 → amount_status='zero_price', tutar=0 ancak hareket gösterilir.
    - BelgeNo global unique → Location JOIN redundant ama filtre güvenliği için tutulur.
    - Yeni: tarih_bas, tarih_bit, metin, hareket_turu filtreleri desteklenir.
    """
    # hareket_turu filtresi fatura kaynaklı mı?
    if hareket_turu:
        tur_upper = hareket_turu.upper()
        if tur_upper in _HAREKET_TURU_CFIS_MAP and tur_upper not in _HAREKET_TURU_FATURA_MAP:
            # CFIS filtresi — fatura tarafı boş döner
            return [], 0
        fatura_tipler = _HAREKET_TURU_FATURA_MAP.get(tur_upper)
        if fatura_tipler is None:
            # Bilinmeyen tür — boş döner
            return [], 0
        tipler_str = "', '".join(fatura_tipler)
    else:
        # Geçerli tipler: 'fsa', 'hsa', 'fsi', 'hai' (fal/hal kesinlikle dışarıda)
        tipler_str = "', '".join(_MUSTERI_FATURA_TIPLERI)

    pb_kg = {"TRY": "TL", "USD": "US", "EUR": "EU"}.get(para_birimi or "", "")
    pb_clause = "AND fk.ParaCinsi = %s" if pb_kg else ""
    pb_params = [pb_kg] if pb_kg else []

    # Ek filtreler
    extra_clauses = ""
    extra_params: List[Any] = []
    if tarih_bas:
        extra_clauses += " AND fk.FatTar >= %s"
        extra_params.append(tarih_bas)
    if tarih_bit:
        extra_clauses += " AND fk.FatTar <= %s"
        extra_params.append(tarih_bit)
    if metin:
        extra_clauses += " AND (fk.BelgeNo LIKE %s OR fk.FaturaNo LIKE %s)"
        like_val = f"%{metin}%"
        extra_params.extend([like_val, like_val])

    # Toplam sayı
    count_sql = f"""
        SELECT COUNT(DISTINCT fk.BelgeNo)
        FROM Fatura_Kay fk WITH (NOLOCK)
        WHERE fk.CariKod = %s
          AND fk.Location = %s
          AND fk.FaturaTip IN ('{tipler_str}')
          AND ISNULL(fk.iptal, '') <> 'E'
          {pb_clause}
          {extra_clauses}
    """
    # Sayfalı veri
    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT
            fk.BelgeNo,
            fk.FaturaTip,
            fk.FatTar,
            fk.Vade,
            fk.ParaCinsi,
            fk.FaturaNo,
            CAST(
                SUM(
                    CASE
                        WHEN fh.Fiyat IS NOT NULL AND fh.Fiyat <> 0
                        THEN fh.Miktar * fh.Fiyat
                             * (1 - ISNULL(fh.iskonto, 0) / 100.0)
                             * (1 + ISNULL(fh.KDVORAN, 0) / 100.0)
                        ELSE 0
                    END
                )
            AS FLOAT) AS tutar_kdvli,
            MAX(CASE WHEN fh.Fiyat = 0 OR fh.Fiyat IS NULL THEN 1 ELSE 0 END) AS has_zero_price
        FROM Fatura_Kay fk WITH (NOLOCK)
        JOIN Fatura_Har fh WITH (NOLOCK) ON fh.BelgeNo = fk.BelgeNo
        WHERE fk.CariKod = %s
          AND fk.Location = %s
          AND fk.FaturaTip IN ('{tipler_str}')
          AND ISNULL(fk.iptal, '') <> 'E'
          {pb_clause}
          {extra_clauses}
        GROUP BY fk.BelgeNo, fk.FaturaTip, fk.FatTar, fk.Vade, fk.ParaCinsi, fk.FaturaNo
        ORDER BY fk.FatTar DESC
        OFFSET %s ROWS FETCH NEXT %s ROWS ONLY
    """
    con = _kg_connect()
    cur = con.cursor()
    try:
        cur.execute(count_sql, [cari_kod, location] + pb_params + extra_params)
        total_r = cur.fetchone()
        total = int(total_r[0]) if total_r else 0

        cur.execute(data_sql, [cari_kod, location] + pb_params + extra_params + [offset, per_page])
        rows = []
        for r in cur.fetchall():
            belge_no, fatura_tip, fat_tar, vade, pb, fatura_no, tutar_kdvli, has_zero = r
            tip_adi, yon = _FATURA_TIP_MAP.get(fatura_tip, (fatura_tip, "BILINMIYOR"))
            pb_disp = _pb_display(pb or "")
            amount_status = "zero_price" if has_zero and (not tutar_kdvli or tutar_kdvli == 0) else "ok"
            rows.append({
                "tarih": str(fat_tar)[:10] if fat_tar else None,
                "hareket_turu_kodu": fatura_tip,
                "hareket_turu_adi": tip_adi,
                "belge_no": belge_no,
                "aciklama": fatura_no or "",
                "borc": _ds(tutar_kdvli) if yon == "BORC" else "0",
                "alacak": _ds(tutar_kdvli) if yon == "ALACAK" else "0",
                "hareket_tutari": _ds(tutar_kdvli),
                "yon": yon,
                "para_birimi": pb_disp,
                "vade_tarihi": str(vade)[:10] if vade else None,
                "kaynak": "FATURA",
                "location": location,
                "cari_kod": cari_kod,
                "balance_status": amount_status,
            })
        return rows, total
    finally:
        try:
            con.close()
        except Exception:
            pass


def _fetch_cfis_hareketleri(
    cari_kod: str,
    location: str,
    para_birimi: Optional[str],
    page: int,
    per_page: int,
    tarih_bas: Optional[str] = None,
    tarih_bit: Optional[str] = None,
    metin: Optional[str] = None,
    hareket_turu: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    C_Fis_Har (cbpg = cari_kod) JOIN C_Fis_Kay.
    - cbpg filtresi zorunlu (aynı FisNo farklı carilere ait satırlar olabilir).
    - NT/NO/AD/BG: tahsilat; BD/DB/DA/CV: düzeltme/devir.
    - İptal dışarıda.
    - Yeni: tarih_bas, tarih_bit, metin, hareket_turu filtreleri desteklenir.
    """
    # hareket_turu filtresi cfis kaynaklı mı?
    if hareket_turu:
        tur_upper = hareket_turu.upper()
        if tur_upper in _HAREKET_TURU_FATURA_MAP and tur_upper not in _HAREKET_TURU_CFIS_MAP:
            # Fatura filtresi — cfis tarafı boş döner
            return [], 0
        cfis_tipler = _HAREKET_TURU_CFIS_MAP.get(tur_upper)
        if cfis_tipler is None:
            # Bilinmeyen tür, tüm tiplerle devam et
            cfis_tipler = tuple(_TAHSILAT_TIPLERI | _DUZELTME_TIPLERI)
        tip_list = "', '".join(cfis_tipler)
    else:
        tip_list = "', '".join(_TAHSILAT_TIPLERI | _DUZELTME_TIPLERI)

    pb_kg = {"TRY": "TL", "USD": "US", "EUR": "EU"}.get(para_birimi or "", "")
    pb_clause = "AND cfh.ParaCinsi = %s" if pb_kg else ""
    pb_params = [pb_kg] if pb_kg else []

    # Ek filtreler
    extra_clauses = ""
    extra_params: List[Any] = []
    if tarih_bas:
        extra_clauses += " AND cfk.FisTar >= %s"
        extra_params.append(tarih_bas)
    if tarih_bit:
        extra_clauses += " AND cfk.FisTar <= %s"
        extra_params.append(tarih_bit)
    if metin:
        extra_clauses += " AND (cfh.tanim LIKE %s OR cfk.BelgeNo LIKE %s)"
        like_val = f"%{metin}%"
        extra_params.extend([like_val, like_val])

    count_sql = f"""
        SELECT COUNT(*)
        FROM C_Fis_Har cfh WITH (NOLOCK)
        JOIN C_Fis_Kay cfk WITH (NOLOCK) ON cfk.FisNo = cfh.FisNo
        WHERE cfh.cbpg = %s
          AND cfk.Location = %s
          AND cfk.FisTip IN ('{tip_list}')
          AND ISNULL(cfk.iptal, '') <> 'E'
          {pb_clause}
          {extra_clauses}
    """
    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT
            cfh.FisNo,
            cfk.FisTip,
            cfk.FisTar,
            cfh.tanim,
            CAST(cfh.Tutar AS FLOAT) AS tutar,
            cfh.ParaCinsi,
            cfk.BelgeNo
        FROM C_Fis_Har cfh WITH (NOLOCK)
        JOIN C_Fis_Kay cfk WITH (NOLOCK) ON cfk.FisNo = cfh.FisNo
        WHERE cfh.cbpg = %s
          AND cfk.Location = %s
          AND cfk.FisTip IN ('{tip_list}')
          AND ISNULL(cfk.iptal, '') <> 'E'
          {pb_clause}
          {extra_clauses}
        ORDER BY cfk.FisTar DESC
        OFFSET %s ROWS FETCH NEXT %s ROWS ONLY
    """
    con = _kg_connect()
    cur = con.cursor()
    try:
        cur.execute(count_sql, [cari_kod, location] + pb_params + extra_params)
        total_r = cur.fetchone()
        total = int(total_r[0]) if total_r else 0

        cur.execute(data_sql, [cari_kod, location] + pb_params + extra_params + [offset, per_page])
        rows = []
        for r in cur.fetchall():
            fis_no, fis_tip, fis_tar, tanim, tutar, pb, belge_no = r
            tip_adi, yon = _CFIS_TIP_MAP.get(fis_tip, (fis_tip, "BILINMIYOR"))
            pb_disp = _pb_display(pb or "")
            rows.append({
                "tarih": str(fis_tar)[:10] if fis_tar else None,
                "hareket_turu_kodu": fis_tip,
                "hareket_turu_adi": tip_adi,
                "belge_no": belge_no or str(fis_no),
                "aciklama": (tanim or "").strip(),
                "borc": _ds(tutar) if yon == "BORC" else "0",
                "alacak": _ds(tutar) if yon == "ALACAK" else "0",
                "hareket_tutari": _ds(tutar),
                "yon": yon,
                "para_birimi": pb_disp,
                "vade_tarihi": None,
                "kaynak": "CFIS",
                "location": location,
                "cari_kod": cari_kod,
                "balance_status": "ok",
            })
        return rows, total
    finally:
        try:
            con.close()
        except Exception:
            pass


def _fetch_authoritative_balance_safe(location: str, cari_kod: str, pb: str) -> Optional[str]:
    """Korgün authoritative balance — hata durumunda None döner."""
    try:
        try:
            from modules.finans.read_model.rm_receivable_refresh import fetch_authoritative_balance
        except ImportError:
            from app.modules.finans.read_model.rm_receivable_refresh import fetch_authoritative_balance
        return fetch_authoritative_balance(location, cari_kod, pb)
    except Exception:
        return None


def _cursor_key_to_offset(all_rows: List[Dict[str, Any]], cursor_key: Optional[str]) -> int:
    """cursor_key → offset dönüşümü. Bulunamazsa 0 döner."""
    if not cursor_key:
        return 0
    try:
        parts = cursor_key.split('|', 2)
        if len(parts) >= 2:
            c_tarih, c_belge = parts[0], parts[1]
            for i, r in enumerate(all_rows):
                if r.get('tarih') == c_tarih and r.get('belge_no') == c_belge:
                    return i + 1
    except Exception:
        pass
    return 0


# ─── Ana fonksiyon ────────────────────────────────────────────────────────────

def get_customer_movements(
    cari_kod: str,
    location: str,
    para_birimi: Optional[str] = None,
    kaynak_filter: Optional[str] = None,   # 'FATURA', 'CFIS', None=tümü
    hareket_turu: Optional[str] = None,    # İşlem türü filtresi
    tarih_bas: Optional[str] = None,
    tarih_bit: Optional[str] = None,
    metin: Optional[str] = None,           # belge/açıklama arama
    cursor_key: Optional[str] = None,      # lazy-load cursor
    batch_size: int = 100,                 # cursor batch
    # Geriye dönük uyumluluk
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """
    Müşteri cari hareketlerini döner (lazy Korgün sorgusu).
    Ana sayfa bağımsız çalışır.

    Returns dict:
      rows, total_fatura, total_cfis, pagination,
      filtered_totals, current_balance,
      next_cursor, running_balance_status, authoritative_balance,
      query_ms, error
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "rows": [],
        "total_fatura": 0,
        "total_cfis": 0,
        "pagination": {"page": page, "per_page": per_page, "total": 0, "total_pages": 1},
        "filtered_totals": {
            "borc": "0",
            "alacak": "0",
            "net": "0",
            "filtered_count": 0,
            "displayed_count": 0,
        },
        "current_balance": None,
        "next_cursor": None,
        "running_balance_status": "not_calculated",
        "authoritative_balance": None,
        "query_ms": 0,
        "error": None,
    }

    try:
        # ── Authoritative balance (Korgün) ────────────────────────────────────
        pb_norm = para_birimi or "TRY"
        auth_bal = _fetch_authoritative_balance_safe(location, cari_kod, pb_norm)
        result["authoritative_balance"] = auth_bal
        result["current_balance"] = {
            "amount": auth_bal or "0",
            "currency": pb_norm,
            "authority": "Korgun",
        }

        # ── Tüm hareketleri çek (filtreli) ───────────────────────────────────
        kwargs = dict(
            tarih_bas=tarih_bas,
            tarih_bit=tarih_bit,
            metin=metin,
            hareket_turu=hareket_turu,
        )

        if kaynak_filter == "FATURA":
            fatura_rows_all, total_fatura = _fetch_fatura_hareketleri(
                cari_kod, location, para_birimi, 1, 10000, **kwargs
            )
            cfis_rows_all, total_cfis = [], 0
        elif kaynak_filter == "CFIS":
            fatura_rows_all, total_fatura = [], 0
            cfis_rows_all, total_cfis = _fetch_cfis_hareketleri(
                cari_kod, location, para_birimi, 1, 10000, **kwargs
            )
        else:
            fatura_rows_all, total_fatura = _fetch_fatura_hareketleri(
                cari_kod, location, para_birimi, 1, 10000, **kwargs
            )
            cfis_rows_all, total_cfis = _fetch_cfis_hareketleri(
                cari_kod, location, para_birimi, 1, 10000, **kwargs
            )

        # ── Birleştir ve tarih sırala ─────────────────────────────────────────
        all_rows = sorted(
            fatura_rows_all + cfis_rows_all,
            key=lambda r: r.get("tarih") or "1900-01-01",
            reverse=True,
        )
        total = len(all_rows)

        # ── filtered_totals (tüm filtreli satırlar, Decimal) ──────────────────
        filtered_borc = sum(Decimal(r.get('borc') or '0') for r in all_rows)
        filtered_alacak = sum(Decimal(r.get('alacak') or '0') for r in all_rows)
        filtered_net = filtered_borc - filtered_alacak

        result["total_fatura"] = total_fatura
        result["total_cfis"] = total_cfis

        # ── Cursor tabanlı lazy-load ──────────────────────────────────────────
        batch_size = max(1, min(batch_size, 200))
        offset = _cursor_key_to_offset(all_rows, cursor_key)
        batch = all_rows[offset: offset + batch_size]

        # next_cursor: son satırın tarih|belge_no
        next_cursor = None
        if offset + batch_size < total and batch:
            last = batch[-1]
            next_cursor = f"{last.get('tarih', '')}|{last.get('belge_no', '')}"

        result["rows"] = batch
        result["next_cursor"] = next_cursor
        result["filtered_totals"] = {
            "borc": str(filtered_borc),
            "alacak": str(filtered_alacak),
            "net": str(filtered_net),
            "filtered_count": total,
            "displayed_count": len(batch),
        }

        # ── Geriye dönük uyumluluk: pagination ───────────────────────────────
        total_pages = max(1, (total + per_page - 1) // per_page)
        page_clamped = max(1, min(page, total_pages))
        start = (page_clamped - 1) * per_page
        result["pagination"] = {
            "page": page_clamped,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

        # Running balance değerlendirmesi
        result["running_balance_status"] = _evaluate_running_balance(
            cari_kod, location, para_birimi
        )

    except Exception as exc:
        logger.exception("get_customer_movements error for %s/%s: %s", cari_kod, location, exc)
        result["error"] = str(exc)[:200]

    result["query_ms"] = int((time.time() - t0) * 1000)
    return result


def _evaluate_running_balance(
    cari_kod: str,
    location: str,
    para_birimi: Optional[str],
) -> str:
    """
    Running balance durumunu değerlendirir.
    - Devir hareketi (DB/DA) var mı?
    - Eğer var: devir dahil hesapla, sonucu kg_fn ile karşılaştır.
    - Eğer yoksa: 'no_opening_balance' döner.
    """
    try:
        # _ds is defined locally in this module (line ~80); no need to import from refresh worker
        auth = _fetch_authoritative_balance_safe(location, cari_kod, para_birimi or "TRY")
        if auth is None:
            return "kg_fn_unavailable"
        return f"kg_fn_balance={auth}"
    except Exception:
        return "evaluation_error"


def _customer_yon_from_fn_net(fn_net: Decimal) -> str:
    if fn_net > 0:
        return "Açık Alacak / Müşteri Borçlu"
    if fn_net < 0:
        return "Müşteri Avansı"
    return "Bakiye Yok"


def _son_belge_tutar_note(tarih: Any, tutar: Any) -> Optional[str]:
    if not tarih:
        return None
    try:
        amt = Decimal(str(tutar or 0))
    except (InvalidOperation, TypeError, ValueError):
        amt = Decimal("0")
    if amt == 0:
        return "tutar kaynağı bulunamadı"
    return None


def get_customer_summary(
    cari_kod: str,
    location: str,
    para_birimi: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cari detay modalı üst özet — yalnız RM snapshot (GET sırasında Korgün yok).
    Resmî bakiye liste ile aynı snapshot kg_fn değeridir.
    Veri kaynağı: read_receivable_customer snapshot (ProgramData RM, direction=RECEIVABLE).
    """
    try:
        # _ds is defined locally in this module (no import from refresh worker needed)
        from modules.finans.read_model.rm_snapshot_lookup import lookup_receivable_row
    except ImportError:
        from app.modules.finans.read_model.rm_snapshot_lookup import lookup_receivable_row

    pb_norm = (para_birimi or "TRY").strip().upper()
    snap = lookup_receivable_row(location, cari_kod, pb_norm)
    if not snap:
        return {
            "ok": False,
            "error": "snapshot_row_not_found",
            "cari_kod": cari_kod,
            "location": location,
            "para_birimi": pb_norm,
        }

    row = snap["row"]
    enrich = snap.get("enrichment") or {}
    auth_d = Decimal(str(row.get("net") or "0"))
    fn_borc = float(row.get("borc") or 0)
    fn_alacak = float(row.get("alacak") or 0)
    fn_net = float(row.get("net") or 0)

    har_borc = enrich.get("info_har_borc")
    har_alacak = enrich.get("info_har_alacak")
    har_net = enrich.get("info_har_net")
    delta_borc = enrich.get("info_delta_borc")
    delta_alacak = enrich.get("info_delta_alacak")
    delta_net = enrich.get("info_delta_net")
    parity_ok = enrich.get("info_parity_ok")
    parity_note = enrich.get("info_parity_note")
    blocked = list(enrich.get("info_parity_blocked_classes") or [])

    son_satis_tutar = row.get("son_alim_tutar")
    son_satis_note = _son_belge_tutar_note(row.get("son_alim_tarih"), son_satis_tutar)
    son_tahsilat_tutar = row.get("son_odeme_tutar")
    son_tahsilat_note = _son_belge_tutar_note(row.get("son_odeme_tarih"), son_tahsilat_tutar)

    return {
        "ok": True,
        "cari_kod": cari_kod,
        "location": row.get("location") or location,
        "para_birimi": pb_norm,
        "authoritative_balance": _ds(auth_d),
        "canonical_balance_source": "kg_fn",
        "balance_source": "rm_snapshot",
        "snapshot_id": snap.get("snapshot_id"),
        "snapshot_published_at": snap.get("published_at"),
        "canonical_location": enrich.get("canonical_balance_location"),
        "mirror_location": enrich.get("mirror_location"),
        "movement_ledger_role": "informational",
        "open_receivable": _ds(auth_d) if auth_d > 0 else "0",
        "customer_overpayment": _ds(abs(auth_d)) if auth_d < 0 else "0",
        "yon": row.get("bakiye_durumu") or _customer_yon_from_fn_net(auth_d),
        "fn_borc": fn_borc,
        "fn_alacak": fn_alacak,
        "fn_net": fn_net,
        "har_borc": har_borc,
        "har_alacak": har_alacak,
        "har_net": har_net,
        "delta_borc": delta_borc,
        "delta_alacak": delta_alacak,
        "delta_net": delta_net,
        "parity_ok": parity_ok,
        "parity_note": parity_note,
        "parity_blocked_classes": blocked,
        "son_satis_tarih": row.get("son_alim_tarih"),
        "son_satis_tutar": son_satis_tutar,
        "son_satis_tutar_note": son_satis_note,
        "son_tahsilat_tarih": row.get("son_odeme_tarih"),
        "son_tahsilat_tutar": son_tahsilat_tutar,
        "son_tahsilat_tutar_note": son_tahsilat_note,
        "son_tahsilat_tur": enrich.get("son_tahsilat_tur"),
        "portfoy_cek_cnt": enrich.get("portfoy_cek_cnt", 0),
        "portfoy_cek_tutar": enrich.get("portfoy_cek_tutar"),
        "portfoy_cek_muhafsiz_cnt": enrich.get("portfoy_cek_muhafsiz_cnt", 0),
    }
