# -*- coding: utf-8 -*-
"""Enjeksiyon Takip modulu (CPS 8080 - FAZ 2 iskelet)

URL yapisi:
  /enjeksiyon/          -> Yonetim paneli (sidebar'li)
  /enjeksiyon/saha      -> Saha ekrani (sidebar'siz, Ferhat icin)
  /enjeksiyon/api/...   -> API (F6+ doldurulacak)
"""
from modules.enjeksiyon.routes import enjeksiyon_bp

__all__ = ['enjeksiyon_bp']
