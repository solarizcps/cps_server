# -*- coding: utf-8 -*-
"""Solariz CPS — Saha Numune Talep (UI prototip, Enjeksiyon bagimsiz)."""
from flask import Blueprint, render_template

from modules.auth import yetki_gerekli

saha_bp = Blueprint(
    'saha',
    __name__,
    url_prefix='/saha',
    template_folder='../../templates/saha',
)


@saha_bp.route('/numune-talep')
@yetki_gerekli('enjeksiyon', 'can_view')
def numune_talep_sayfa():
    """Saha Numune Talep — iki sekmeli UI prototip (DB yok)."""
    return render_template('saha/numune_talep.html')
