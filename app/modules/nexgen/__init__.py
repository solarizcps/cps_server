# -*- coding: utf-8 -*-
from .routes import nexgen_bp, _db, _kullanici_id
from .nx_ar_api import register_nx_ar_routes

register_nx_ar_routes(nexgen_bp, _db, _kullanici_id)
