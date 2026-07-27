# -*- coding: utf-8 -*-
from .routes import (
    nexgen_bp,
    _db,
    _kullanici_id,
    _pzm_aktif_cari_liste,
    _pzm_renk_kart_listesi,
    _tablet_can_arge_ops,
)
from .nx_ar_api import register_nx_ar_routes
from .numune_talep_routes import register_numune_talep_routes
from .mo_sevkiyat_routes import register_mo_sevkiyat_routes
from .finans_routes import register_finans_routes
from .finans_cari_kimlik_routes import register_finans_cari_kimlik_routes
from .musteri_pazarlama_routes import register_musteri_pazarlama_routes

register_nx_ar_routes(nexgen_bp, _db, _kullanici_id)
register_mo_sevkiyat_routes(nexgen_bp, _db, _kullanici_id)
register_finans_routes(nexgen_bp, _db, _kullanici_id)
register_finans_cari_kimlik_routes(nexgen_bp, _db, _kullanici_id)
register_musteri_pazarlama_routes(nexgen_bp, _db, _kullanici_id)

register_numune_talep_routes(
    nexgen_bp,
    _db,
    _kullanici_id,
    renk_kart_fn=_pzm_renk_kart_listesi,
    cari_liste_fn=_pzm_aktif_cari_liste,
    tablet_arge_guard=_tablet_can_arge_ops,
)
