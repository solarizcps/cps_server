# -*- coding: utf-8 -*-
"""
Mehmet planlama köprüsü — onay sonrası snapshot veri sözleşmesi.

FAZ-CARI-SORUMLU-F1C: workflow uygulanmaz; yalnız sözleşme.
"""
from __future__ import annotations

from typing import Any

OLAY_KODU_ONAY = 'SATIS_SIPARISI_ONAYLANDI'

PLANLAMA_KOPRU_SNAPSHOT_ALANLARI: tuple[str, ...] = (
    'siparis_id',
    'siparis_no',
    'cari_id',
    'cari_kod_snapshot',
    'cari_unvan_snapshot',
    'pazarlamaci_id',
    'pazarlamaci_adi',
    'urun_ozet',
    'miktar',
    'formul_id',
    'renk_kodu',
    'rf_renk_id',
    'termin_tarihi',
    'fiyat',
    'para_birimi',
    'vade_gun',
    'odeme_sekli',
    'cek_sayisi',
    'cek_tarihleri',
    'risk_sonucu',
    'siparis_notlari',
    'teslim_plani',
    'numune_baglanti_id',
    'onayli_renk_baglanti_id',
    'onay_talep_id',
    'snapshot_hash',
    'tahsilat_odeme_sekli',
    'tahsilat_kurali',
    'tahsilat_gun_sayisi',
    'tahsilat_sabit_tarih',
    'planlanan_tahsilat_tarihi',
    'tahsilat_sozu',
    'tahsilat_notu',
    'cek_teslim_tarihi',
    'cek_vadesi',
    'tahsilat_durum_metin',
)

PLANLAMA_KOPRU_KURALLARI: dict[str, Any] = {
    'olay_kodu': OLAY_KODU_ONAY,
    'mehmet_yeniden_giris_yok': True,
    'mehmet_ayri_kuyruk_yok': True,
    'siparis_al_aksiyonu_yok': True,
    'tek_planlama_kaydi': True,
    'siparis_kopyasi_yok': True,
    'onay_sonrasi_degisiklik': 'yeni_revizyon_onay_gerekir',
    'siparis_onayi_uretim_baslatmaz': True,
    'siparis_id_korunur': True,
    'uretime_gonder_audit': 'mevcut audit/timeline (sahiplenme yok)',
    'akış': [
        'Pazarlamacı sipariş oluşturur ve Merkezi Onaya gönderir',
        'Onay adımları tamamlanır',
        'Aynı nexgen_planlama_siparis kaydı ONAYLANDI olur',
        'Onaylı snapshot yazılır',
        'Mevcut Pazarlama Sipariş ekranında aynı kayıt görünür',
        'Mehmet mevcut Malzeme İhtiyaç → Üretime Gönder akışını kullanır',
    ],
}

PLANLAMA_KOPRU_SOZLESMESI: dict[str, Any] = {
    'snapshot_alanlari': list(PLANLAMA_KOPRU_SNAPSHOT_ALANLARI),
    'kurallar': PLANLAMA_KOPRU_KURALLARI,
}
