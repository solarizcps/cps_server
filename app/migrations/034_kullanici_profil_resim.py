# -*- coding: utf-8 -*-
"""
Migration 034 — kullanici_profil.profil_resim
Personel 360 profil fotoğrafı desteği için kolon ekleme.
Idempotent: kolon zaten varsa tekrar eklemez.
"""
import sys
import os
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    try:
        mevcut = [r[1] for r in con.execute('PRAGMA table_info(kullanici_profil)').fetchall()]
        if 'profil_resim' in mevcut:
            print('[034] profil_resim kolonu zaten var — atlanıyor.')
            return
        con.execute('ALTER TABLE kullanici_profil ADD COLUMN profil_resim TEXT DEFAULT NULL')
        con.commit()
        n = con.execute('SELECT COUNT(*) FROM kullanici_profil').fetchone()[0]
        print(f'[034] profil_resim kolonu eklendi. Mevcut {n} profil etkilenmedi (NULL).')
    finally:
        con.close()


if __name__ == '__main__':
    run()
