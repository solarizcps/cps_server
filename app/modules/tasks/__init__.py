# -*- coding: utf-8 -*-
"""
CPS DEV - Tasks Modulu (Gorev Sistemi)
=======================================

FAZ 1 - Iskelet adim: blueprint kayit + basit GET endpoint'ler.

Tablolar (002_tasks.sql):
  - tasks_users     (bagimsiz kullanici havuzu)
  - tasks           (ana gorev tablosu, 33 kolon)
  - task_files      (dosya ekleri)
  - task_logs       (audit history)
  - task_settings   (kullanici/departman ayarlari)

Bildirimler: mevcut bildirim_log tablosu uzerinden.

Eski usta_gorevleri tablosu PARALEL yasar, dokunulmaz.
"""

from .routes import tasks_bp

__all__ = ["tasks_bp"]
