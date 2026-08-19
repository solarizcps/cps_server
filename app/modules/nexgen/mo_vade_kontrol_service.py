# -*- coding: utf-8 -*-
"""
mo_vade_kontrol_service.py
===========================
Vade Kontrol V1 — tek canonical matematik kaynağı.

Reuse edilecek noktalar:
  - Erhan çek preview (route henüz yok — Faz 3)
  - Yönetim Onayı detay
  - Cari360 Sipariş Geçmişi
  - Onay snapshot freeze

DB yazma yok. Sadece okuma + hesap.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from modules.nexgen.mo_vade_kontrol_config import (
    CEK_ODEME_TIPI,
    DURUM_AVANTAJ,
    DURUM_CEK_YOK,
    DURUM_FAZLA_VADE,
    DURUM_NAKIT_PAKET,
    DURUM_SEVK_BEKLIYOR,
    DURUM_VADE_UYGUN,
    FINANSMAN_AYLIK_ORAN,
    TUTAR_TOLERANS,
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CekSatiriInput:
    """Bir çek satırının hesap girdisi. DB'ye yazılmadan da kullanılabilir."""

    tutar: Decimal
    gercek_cek_vade_tarihi: str          # YYYY-MM-DD
    para_birimi: str
    cek_alim_tarihi: Optional[str] = None   # opsiyonel bağlam
    id: Optional[int] = None                # persist sonrası dolu olabilir
    odeme_referansi: Optional[str] = None
    banka_adi: Optional[str] = None


@dataclass
class CekDetayi:
    """Çek bazlı hesap sonucu (output içinde liste)."""

    id: Optional[int]
    tutar: float
    para_birimi: str
    gercek_cek_vade_tarihi: str
    gercek_vade_gun: Optional[int]
    sapma_gun_raw: Optional[float]
    sapma_gun_gosterim: Optional[int]
    finansman_etkisi: Optional[float]


@dataclass
class VadeKontrolSonuc:
    """hesapla() dönüş tipi. JSON serializable."""

    siparis_id: Optional[int]
    tahsilat_kayit_id: Optional[int]
    odeme_tipi: Optional[str]
    para_birimi: Optional[str]
    gercek_sevk_tarihi: Optional[str]
    onaylanan_vade_gun: Optional[int]
    hedef_vade_tarihi: Optional[str]
    cek_adedi: int
    toplam_cek_tutari: float
    paket_hedef_tutar: Optional[float]
    kalan_tutar: Optional[float]
    karsilama_orani: Optional[float]
    paket_tamamlandi: Optional[bool]
    agirlikli_ortalama_vade_gun_raw: Optional[float]
    agirlikli_ortalama_vade_gun_gosterim: Optional[int]
    agirlikli_ortalama_vade_tarihi: Optional[str]
    vade_sapma_gun_raw: Optional[float]
    vade_sapma_gun_gosterim: Optional[int]
    durum_kodu: str
    durum_etiket: str
    finansman_aylik_oran: float
    finansman_net: Optional[float]
    cek_detaylari: list = field(default_factory=list)
    uyarilar: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class VadeKontrolError(Exception):
    """Validation hatası — exception yerine uyarilar listesi tercih edilir."""
    pass


def _parse_date(value: str, alan: str) -> date:
    """ISO YYYY-MM-DD parse. Hata varsa VadeKontrolError fırlatır."""
    try:
        cleaned = str(value).strip()[:10]
        return date.fromisoformat(cleaned)
    except (ValueError, TypeError):
        raise VadeKontrolError(f"Geçersiz tarih formatı — {alan}: {value!r}")


def _to_decimal(value, alan: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise VadeKontrolError(f"Geçersiz tutar — {alan}: {value!r}")


def _half_up(d: Decimal) -> int:
    """Decimal → int, ROUND_HALF_UP."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _float2(d: Optional[Decimal]) -> Optional[float]:
    if d is None:
        return None
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _durum_etiket(kod: str, sapma: Optional[int]) -> str:
    if kod == DURUM_VADE_UYGUN:
        return "Vade Uygun"
    if kod == DURUM_FAZLA_VADE:
        return f"+{sapma} Gün Fazla Vade"
    if kod == DURUM_AVANTAJ:
        return f"{sapma} Gün Avantaj"
    if kod == DURUM_SEVK_BEKLIYOR:
        return "Sevk Bekleniyor"
    if kod == DURUM_CEK_YOK:
        return "Çek Girilmedi"
    if kod == DURUM_NAKIT_PAKET:
        return "Nakit Paket"
    if kod == "AVANS_CEK":
        return "Avans Çeki"
    return kod


# ---------------------------------------------------------------------------
# Canonical DB reads
# ---------------------------------------------------------------------------


def _tablo_var(con: sqlite3.Connection, tablo: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
        ).fetchone()
    )


def _cek_vade_fallback(vade_gun, odeme_tipi, talep_referansi) -> int | None:
    """CEK siparişlerinde vade_gun NULL ise PZM V2 JSON cek_vade_gun fallback.

    Öncelik: vade_gun kolonu → talep_referansi.cek_vade_gun (yalnız CEK)
    0/negatif/bozuk → None.
    """
    if vade_gun is not None:
        try:
            v = int(vade_gun)
            return v if v > 0 else None
        except (TypeError, ValueError):
            pass
    if (odeme_tipi or '').upper() != 'CEK':
        return None
    if not talep_referansi:
        return None
    ref = str(talep_referansi)
    marker = '__PZM_V2__'
    idx = ref.find(marker)
    if idx < 0:
        return None
    try:
        payload = json.loads(ref[idx + len(marker):])
        raw = payload.get('cek_vade_gun')
        if raw is None:
            return None
        v = int(str(raw).strip())
        return v if v > 0 else None
    except Exception:
        return None


def siparis_vade_baglam(con: sqlite3.Connection, siparis_id: int) -> dict:
    """
    Sipariş bağlamı: onaylanan vade, para birimi.
    CEK'te vade_gun NULL ise talep_referansi.cek_vade_gun fallback kullanılır.
    Pure read.
    """
    row = con.execute(
        """
        SELECT vade_gun, anlasma_para_birimi, siparis_no, odeme_tipi, talep_referansi
        FROM nexgen_planlama_siparis
        WHERE id = ?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return {}
    vade = _cek_vade_fallback(
        row["vade_gun"],
        row["odeme_tipi"],
        row["talep_referansi"],
    )
    return {
        "siparis_id": siparis_id,
        "siparis_no": row["siparis_no"],
        "onaylanan_vade_gun": vade,
        "para_birimi": (row["anlasma_para_birimi"] or "TRY"),
    }


def _gercek_sevk_tarihi_from_db(con: sqlite3.Connection, siparis_id: int) -> Optional[str]:
    """mo_sevkiyat_service.gercek_sevk_tarihi ile aynı sorgu; circular import kaçınmak için local."""
    if not _tablo_var(con, "mo_musteri_sevkiyat"):
        return None
    row = con.execute(
        """
        SELECT sevk_tarihi FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1 AND sevk_tarihi IS NOT NULL AND sevk_tarihi != ''
          AND durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        ORDER BY sevk_tarihi ASC, id ASC LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return None
    val = row[0] if not hasattr(row, "keys") else row["sevk_tarihi"]
    return (val or "")[:10] or None


def _parent_row(con: sqlite3.Connection, tahsilat_kayit_id: int) -> Optional[sqlite3.Row]:
    if not _tablo_var(con, "mo_tahsilat_kayit"):
        return None
    con.row_factory = sqlite3.Row
    return con.execute(
        """
        SELECT id, siparis_id, odeme_tipi, para_birimi,
               paket_hedef_tutar, onaylanan_vade_gun_snapshot,
               gercek_sevk_tarihi_snapshot, hedef_vade_tarihi
        FROM mo_tahsilat_kayit
        WHERE id = ?
        """,
        (tahsilat_kayit_id,),
    ).fetchone()


def _aktif_cekler(con: sqlite3.Connection, tahsilat_kayit_id: int) -> list[dict]:
    if not _tablo_var(con, "mo_tahsilat_cek"):
        return []
    rows = con.execute(
        """
        SELECT id, tutar, para_birimi, gercek_cek_vade_tarihi,
               cek_alim_tarihi, odeme_referansi, banka_adi
        FROM mo_tahsilat_cek
        WHERE tahsilat_kayit_id = ? AND aktif = 1
        ORDER BY sira_no, id
        """,
        (tahsilat_kayit_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Core hesap — pure function (con opsiyonel, live DB gerekirse verilir)
# ---------------------------------------------------------------------------


def hesapla(
    *,
    siparis_id: Optional[int] = None,
    tahsilat_kayit_id: Optional[int] = None,
    odeme_tipi: Optional[str] = None,
    cek_satirlari: Optional[list[CekSatiriInput]] = None,
    paket_hedef_tutar: Optional[Decimal] = None,
    para_birimi: Optional[str] = None,
    onaylanan_vade_gun: Optional[int] = None,
    sevk_tarihi: Optional[str] = None,
    aylik_finansman_orani: Optional[Decimal] = None,
    con: Optional[sqlite3.Connection] = None,
    tahsilat_tipi: Optional[str] = None,
) -> VadeKontrolSonuc:
    """
    Canonical vade hesabı.

    Preview modda: con=None, cek_satirlari sağlanır.
    Persist modda: con + tahsilat_kayit_id sağlanır; çekler DB'den okunur.

    Öncelik zinciri:
      onaylanan_vade_gun → param > parent snapshot > sipariş vade_gun
      sevk_tarihi        → param > parent snapshot > DB sorgu
      cek_satirlari      → param > DB aktif çekler

    AVANS modu (tahsilat_tipi='AVANS'):
      Sevkiyat olmasa da çek vade analizi yapılır.
      Vade referans = çekin cek_alim_tarihi (yoksa vade_tarihi − onaylanan_vade_gun).
      sevkiyata bağlı finansman etkisi hesaplanmaz.
      Durum = AVANS_CEK (sevkiyat bağımsız).
    """
    oran = aylik_finansman_orani if aylik_finansman_orani is not None else FINANSMAN_AYLIK_ORAN
    uyarilar: list[str] = []
    is_avans = (tahsilat_tipi or '').strip().upper() == 'AVANS'

    # --- NAKIT kontrolü (parent'tan veya parametre) ---
    efektif_odeme_tipi = odeme_tipi
    _resolved_siparis_id = siparis_id
    _resolved_hedef_tutar = paket_hedef_tutar
    _resolved_para_birimi = para_birimi
    _resolved_onaylanan = onaylanan_vade_gun
    _resolved_sevk = sevk_tarihi

    # Eğer DB bağlantısı ve tahsilat_kayit_id varsa parent'ı oku
    parent = None
    if con is not None and tahsilat_kayit_id is not None:
        con.row_factory = sqlite3.Row
        parent = _parent_row(con, tahsilat_kayit_id)
        if parent:
            if efektif_odeme_tipi is None:
                efektif_odeme_tipi = parent["odeme_tipi"]
            if _resolved_siparis_id is None:
                _resolved_siparis_id = parent["siparis_id"]
            if _resolved_hedef_tutar is None and parent["paket_hedef_tutar"] is not None:
                _resolved_hedef_tutar = Decimal(str(parent["paket_hedef_tutar"]))
            if _resolved_para_birimi is None:
                _resolved_para_birimi = parent["para_birimi"]
            if _resolved_onaylanan is None and parent["onaylanan_vade_gun_snapshot"] is not None:
                _resolved_onaylanan = int(parent["onaylanan_vade_gun_snapshot"])
            if _resolved_sevk is None and parent["gercek_sevk_tarihi_snapshot"]:
                _resolved_sevk = parent["gercek_sevk_tarihi_snapshot"]

    # Sipariş bağlamı (onaylanan vade + para birimi fallback)
    _siparis_baglam: dict = {}
    if con is not None and _resolved_siparis_id is not None:
        con.row_factory = sqlite3.Row
        _siparis_baglam = siparis_vade_baglam(con, _resolved_siparis_id)
        if _resolved_onaylanan is None and _siparis_baglam.get("onaylanan_vade_gun") is not None:
            _resolved_onaylanan = int(_siparis_baglam["onaylanan_vade_gun"])
        if _resolved_para_birimi is None:
            _resolved_para_birimi = _siparis_baglam.get("para_birimi") or "TRY"

    # Sevk tarihi DB fallback
    if con is not None and _resolved_sevk is None and _resolved_siparis_id is not None:
        _resolved_sevk = _gercek_sevk_tarihi_from_db(con, _resolved_siparis_id)

    # Para birimi default
    if _resolved_para_birimi is None:
        _resolved_para_birimi = "TRY"

    # Hedef çek tarihi
    _hedef_vade_tarihi: Optional[str] = None
    if _resolved_sevk and _resolved_onaylanan is not None:
        try:
            sevk_d = _parse_date(_resolved_sevk, "sevk_tarihi")
            _hedef_vade_tarihi = (sevk_d + timedelta(days=_resolved_onaylanan)).isoformat()
        except VadeKontrolError:
            pass

    # NAKIT — erken çıkış
    if efektif_odeme_tipi is not None and efektif_odeme_tipi.upper() != CEK_ODEME_TIPI:
        return VadeKontrolSonuc(
            siparis_id=_resolved_siparis_id,
            tahsilat_kayit_id=tahsilat_kayit_id,
            odeme_tipi=efektif_odeme_tipi,
            para_birimi=_resolved_para_birimi,
            gercek_sevk_tarihi=_resolved_sevk,
            onaylanan_vade_gun=_resolved_onaylanan,
            hedef_vade_tarihi=_hedef_vade_tarihi,
            cek_adedi=0,
            toplam_cek_tutari=0.0,
            paket_hedef_tutar=_float2(_resolved_hedef_tutar),
            kalan_tutar=None,
            karsilama_orani=None,
            paket_tamamlandi=None,
            agirlikli_ortalama_vade_gun_raw=None,
            agirlikli_ortalama_vade_gun_gosterim=None,
            agirlikli_ortalama_vade_tarihi=None,
            vade_sapma_gun_raw=None,
            vade_sapma_gun_gosterim=None,
            durum_kodu=DURUM_NAKIT_PAKET,
            durum_etiket=_durum_etiket(DURUM_NAKIT_PAKET, None),
            finansman_aylik_oran=float(oran),
            finansman_net=None,
            cek_detaylari=[],
            uyarilar=[],
        )

    # SEVK BEKLIYOR — erken çıkış (AVANS modunda bypass: çek vade analizi sevkten bağımsız)
    if not _resolved_sevk and not is_avans:
        return VadeKontrolSonuc(
            siparis_id=_resolved_siparis_id,
            tahsilat_kayit_id=tahsilat_kayit_id,
            odeme_tipi=efektif_odeme_tipi or CEK_ODEME_TIPI,
            para_birimi=_resolved_para_birimi,
            gercek_sevk_tarihi=None,
            onaylanan_vade_gun=_resolved_onaylanan,
            hedef_vade_tarihi=None,
            cek_adedi=0,
            toplam_cek_tutari=0.0,
            paket_hedef_tutar=_float2(_resolved_hedef_tutar),
            kalan_tutar=None,
            karsilama_orani=None,
            paket_tamamlandi=None,
            agirlikli_ortalama_vade_gun_raw=None,
            agirlikli_ortalama_vade_gun_gosterim=None,
            agirlikli_ortalama_vade_tarihi=None,
            vade_sapma_gun_raw=None,
            vade_sapma_gun_gosterim=None,
            durum_kodu=DURUM_SEVK_BEKLIYOR,
            durum_etiket=_durum_etiket(DURUM_SEVK_BEKLIYOR, None),
            finansman_aylik_oran=float(oran),
            finansman_net=None,
            cek_detaylari=[],
            uyarilar=[],
        )

    # AVANS: sevk tarihi yok — çek bazlı vade alim_tarihi referansla hesaplanır
    # Normal: sevk_d vade hesabının referans noktasıdır
    sevk_d = _parse_date(_resolved_sevk, "sevk_tarihi") if _resolved_sevk else None

    # Çek satırları: parametre yoksa DB'den
    satir_listesi: list[CekSatiriInput] = []
    if cek_satirlari is not None:
        satir_listesi = list(cek_satirlari)
    elif con is not None and tahsilat_kayit_id is not None:
        for row in _aktif_cekler(con, tahsilat_kayit_id):
            satir_listesi.append(CekSatiriInput(
                tutar=Decimal(str(row["tutar"])),
                gercek_cek_vade_tarihi=row["gercek_cek_vade_tarihi"],
                para_birimi=row["para_birimi"],
                cek_alim_tarihi=row.get("cek_alim_tarihi"),
                id=row.get("id"),
            ))

    # Para birimi validasyonu
    for s in satir_listesi:
        if s.para_birimi.upper() != _resolved_para_birimi.upper():
            raise VadeKontrolError(
                f"Para birimi uyumsuzluğu: paket={_resolved_para_birimi}, çek={s.para_birimi}"
            )

    # Tutar validasyonu
    for i, s in enumerate(satir_listesi):
        if s.tutar <= Decimal("0"):
            raise VadeKontrolError(
                f"Çek {i+1}: tutar sıfır veya negatif olamaz ({s.tutar})"
            )

    # ÇEK YOK
    if not satir_listesi:
        return VadeKontrolSonuc(
            siparis_id=_resolved_siparis_id,
            tahsilat_kayit_id=tahsilat_kayit_id,
            odeme_tipi=efektif_odeme_tipi or CEK_ODEME_TIPI,
            para_birimi=_resolved_para_birimi,
            gercek_sevk_tarihi=_resolved_sevk,
            onaylanan_vade_gun=_resolved_onaylanan,
            hedef_vade_tarihi=_hedef_vade_tarihi,
            cek_adedi=0,
            toplam_cek_tutari=0.0,
            paket_hedef_tutar=_float2(_resolved_hedef_tutar),
            kalan_tutar=_float2(_resolved_hedef_tutar) if _resolved_hedef_tutar is not None else None,
            karsilama_orani=0.0 if _resolved_hedef_tutar else None,
            paket_tamamlandi=False if _resolved_hedef_tutar else None,
            agirlikli_ortalama_vade_gun_raw=None,
            agirlikli_ortalama_vade_gun_gosterim=None,
            agirlikli_ortalama_vade_tarihi=None,
            vade_sapma_gun_raw=None,
            vade_sapma_gun_gosterim=None,
            durum_kodu=DURUM_CEK_YOK,
            durum_etiket=_durum_etiket(DURUM_CEK_YOK, None),
            finansman_aylik_oran=float(oran),
            finansman_net=None,
            cek_detaylari=[],
            uyarilar=[],
        )

    # --- Çek bazlı hesap ---
    cek_detaylari: list[CekDetayi] = []
    toplam_tutar = Decimal("0")
    agirlikli_toplam = Decimal("0")
    finansman_net = Decimal("0")

    for s in satir_listesi:
        vade_d = _parse_date(s.gercek_cek_vade_tarihi, "gercek_cek_vade_tarihi")

        if is_avans:
            # AVANS: vade gün = vade_tarihi - alim_tarihi (kendi çek vadesi)
            if s.cek_alim_tarihi:
                ref_d = _parse_date(s.cek_alim_tarihi, "cek_alim_tarihi")
            else:
                # alim tarihi yoksa vade günü = 0 (aynı gün varsayımı)
                ref_d = vade_d
            gercek_vade_gun = max((vade_d - ref_d).days, 0)
        else:
            gercek_vade_gun = (vade_d - sevk_d).days  # type: ignore[operator]

        agirlikli_toplam += s.tutar * Decimal(str(gercek_vade_gun))
        toplam_tutar += s.tutar

        # Çek bazlı finansman — AVANS'ta sevkiyat olmadığı için finansman hesaplanmaz
        sapma_gun_raw: Optional[Decimal] = None
        cek_finansman: Optional[Decimal] = None
        if not is_avans and _resolved_onaylanan is not None:
            sapma_d = Decimal(str(gercek_vade_gun)) - Decimal(str(_resolved_onaylanan))
            sapma_gun_raw = sapma_d
            cek_finansman = s.tutar * oran * (sapma_d / Decimal("30"))
            finansman_net += cek_finansman

        cek_detaylari.append(CekDetayi(
            id=s.id,
            tutar=float(s.tutar),
            para_birimi=s.para_birimi,
            gercek_cek_vade_tarihi=s.gercek_cek_vade_tarihi,
            gercek_vade_gun=gercek_vade_gun,
            sapma_gun_raw=_float2(sapma_gun_raw),
            sapma_gun_gosterim=_half_up(sapma_gun_raw) if sapma_gun_raw is not None else None,
            finansman_etkisi=_float2(cek_finansman),
        ))

    # Ağırlıklı ortalama
    ort_raw: Decimal = agirlikli_toplam / toplam_tutar
    ort_gosterim: int = _half_up(ort_raw)

    # Ortalama vade tarihi referansı:
    # Normal: sevk_d + ort_gosterim
    # AVANS: ilk çekin alım tarihi + ort_gosterim (ya da vade_tarihi olarak direkt)
    if is_avans:
        # AVANS için ort. vade tarihi = ilk çekin alım tarihi + ağırlıklı ort. vade gün
        _alim_ref = None
        if satir_listesi and satir_listesi[0].cek_alim_tarihi:
            try:
                _alim_ref = _parse_date(satir_listesi[0].cek_alim_tarihi, "alim_ref")
            except VadeKontrolError:
                pass
        if _alim_ref is None:
            # Fallback: son çekin vade tarihi
            _alim_ref = _parse_date(satir_listesi[-1].gercek_cek_vade_tarihi, "vade_ref")
        ort_vade_tarihi: Optional[str] = (_alim_ref + timedelta(days=ort_gosterim)).isoformat()
    else:
        ort_vade_tarihi = (sevk_d + timedelta(days=ort_gosterim)).isoformat()  # type: ignore[operator]

    # Sapma — AVANS'ta sevkiyata göre sapma hesaplanamaz
    sapma_raw: Optional[Decimal] = None
    sapma_gosterim: Optional[int] = None
    durum_kodu: str
    if is_avans:
        # AVANS: sevk olmadan FAZLA_VADE/AVANTAJ karşılaştırması yapılmaz
        # Onaylanan vade ile kıyaslama AVANS'ta anlamsız; durum = AVANS_CEK
        durum_kodu = "AVANS_CEK"
    elif _resolved_onaylanan is not None:
        sapma_raw = ort_raw - Decimal(str(_resolved_onaylanan))
        sapma_gosterim = _half_up(sapma_raw)
        if sapma_gosterim > 0:
            durum_kodu = DURUM_FAZLA_VADE
        elif sapma_gosterim < 0:
            durum_kodu = DURUM_AVANTAJ
        else:
            durum_kodu = DURUM_VADE_UYGUN
    else:
        durum_kodu = DURUM_CEK_YOK  # onaylanan vade bilinmiyor

    # Paket rollup
    hedef_d = _resolved_hedef_tutar
    if hedef_d is not None:
        kalan = hedef_d - toplam_tutar
        karsilama = (toplam_tutar / hedef_d * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        tamamlandi = abs(kalan) <= TUTAR_TOLERANS
        kalan_f = _float2(kalan)
        karsilama_f = float(karsilama)
    else:
        kalan_f = None
        karsilama_f = None
        tamamlandi = None
        uyarilar.append("paket_hedef_tutar belirtilmedi; rollup hesaplanamadı")

    if kalan_f is not None and kalan_f > 0.009:
        uyarilar.append(f"Eksik paket: kalan {kalan_f:.2f} {_resolved_para_birimi}")
    if durum_kodu == DURUM_FAZLA_VADE:
        uyarilar.append(f"Fazla vade: +{sapma_gosterim} gün")

    # AVANS: finansman sevkiyat olmadığı için hesaplanamaz
    finansman_net_result = None if is_avans else (_float2(finansman_net) if _resolved_onaylanan is not None else None)

    return VadeKontrolSonuc(
        siparis_id=_resolved_siparis_id,
        tahsilat_kayit_id=tahsilat_kayit_id,
        odeme_tipi=efektif_odeme_tipi or CEK_ODEME_TIPI,
        para_birimi=_resolved_para_birimi,
        gercek_sevk_tarihi=_resolved_sevk,
        onaylanan_vade_gun=_resolved_onaylanan,
        hedef_vade_tarihi=_hedef_vade_tarihi,
        cek_adedi=len(satir_listesi),
        toplam_cek_tutari=float(toplam_tutar),
        paket_hedef_tutar=_float2(hedef_d),
        kalan_tutar=kalan_f,
        karsilama_orani=karsilama_f,
        paket_tamamlandi=tamamlandi,
        agirlikli_ortalama_vade_gun_raw=_float2(ort_raw),
        agirlikli_ortalama_vade_gun_gosterim=ort_gosterim,
        agirlikli_ortalama_vade_tarihi=ort_vade_tarihi,
        vade_sapma_gun_raw=_float2(sapma_raw),
        vade_sapma_gun_gosterim=sapma_gosterim,
        durum_kodu=durum_kodu,
        durum_etiket=_durum_etiket(durum_kodu, sapma_gosterim),
        finansman_aylik_oran=float(oran),
        finansman_net=finansman_net_result,
        cek_detaylari=[
            {
                "id": c.id,
                "tutar": c.tutar,
                "para_birimi": c.para_birimi,
                "gercek_cek_vade_tarihi": c.gercek_cek_vade_tarihi,
                "gercek_vade_gun": c.gercek_vade_gun,
                "sapma_gun_raw": c.sapma_gun_raw,
                "sapma_gun_gosterim": c.sapma_gun_gosterim,
                "finansman_etkisi": c.finansman_etkisi,
            }
            for c in cek_detaylari
        ],
        uyarilar=uyarilar,
    )


# ---------------------------------------------------------------------------
# Snapshot helper (Faz 4 için — onay anında parent freeze)
# ---------------------------------------------------------------------------

def onay_snapshot_blogu(sonuc: VadeKontrolSonuc) -> dict:
    """
    Yönetim Onayı snapshot_json içine yazılacak vade_kontrol bloğu.
    Faz 4'te onay_tahsilat_adapter tarafından kullanılacak.
    """
    return {
        "vade_kontrol": {
            "durum_kodu": sonuc.durum_kodu,
            "onaylanan_vade_gun": sonuc.onaylanan_vade_gun,
            "gercek_sevk_tarihi": sonuc.gercek_sevk_tarihi,
            "hedef_vade_tarihi": sonuc.hedef_vade_tarihi,
            "agirlikli_ortalama_vade_gun_gosterim": sonuc.agirlikli_ortalama_vade_gun_gosterim,
            "agirlikli_ortalama_vade_tarihi": sonuc.agirlikli_ortalama_vade_tarihi,
            "vade_sapma_gun_gosterim": sonuc.vade_sapma_gun_gosterim,
            "finansman_net": sonuc.finansman_net,
            "paket_hedef_tutar": sonuc.paket_hedef_tutar,
            "karsilama_orani": sonuc.karsilama_orani,
            "cek_adedi": sonuc.cek_adedi,
            "finansman_aylik_oran": sonuc.finansman_aylik_oran,
        }
    }
