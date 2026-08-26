# -*- coding: utf-8 -*-
"""Migration DB path guard — canonical yazımını engeller."""
from __future__ import annotations

import os

_CANONICAL_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
)


def canonical_db_path() -> str:
    return _CANONICAL_DB


def resolve_db_path(db_path: str | None, *, allow_canonical: bool = False) -> str:
    """
    Migration hedef DB yolunu doğrula.

    Raises:
        ValueError: db_path boş/None
        PermissionError: canonical hedef ve allow_canonical=False
        FileNotFoundError: dosya yok
    """
    if db_path is None or not str(db_path).strip():
        raise ValueError(
            'db_path zorunlu — parametresiz migration çalıştırılamaz. '
            'Örnek: run(r"C:\\path\\to\\mock_data_test.db")'
        )
    path = os.path.normpath(os.path.abspath(str(db_path)))
    if path == _CANONICAL_DB and not allow_canonical:
        raise PermissionError(
            f'Canonical DB hedefi reddedildi: {path} '
            f'(allow_canonical=True olmadan yazılamaz)'
        )
    if not os.path.isfile(path):
        raise FileNotFoundError(f'DB dosyası bulunamadı: {path}')
    return path
