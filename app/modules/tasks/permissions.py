# -*- coding: utf-8 -*-
"""
CPS DEV - Tasks Modulu - Permissions
======================================

Yetki kontrolleri - sade ve merkezi.

Kullanim:
    from modules.tasks.permissions import (
        can_view_task, can_edit_task,
        can_change_status, can_approve_task,
        is_admin,
    )

    if not can_view_task(task, user):
        raise PermissionError("Yetki yok")

KURALLAR:
    admin:
        - her seyi yapar
    created_by (gorev olusturan):
        - edit
        - iptal
    assigned_to (atanan kisi):
        - start (devam_ediyor)
        - complete (onay_bekliyor / tamamlandi)
    approval_user_id (onaylayan):
        - approve (tamamlandi)
        - reject (revize_istendi)

    'admin' tanimi:
        - sistem_kullanici.RolAd == 'Yonetim'
        - VEYA sistem_kullanici.KullaniciAdi == 'admin'
        (mevcut auth pattern korunur)

Bu modul SQL DOKUNMAZ. Sadece task dict + user dict alir, bool doner.
"""


# ============================================================
# CUSTOM EXCEPTION
# ============================================================
class PermissionDenied(Exception):
    """Yetki hatasi - routes.py 403 ceviri."""
    pass


# ============================================================
# HELPER: kullanici bilgisi cikar
# ============================================================
def _kullanici_adi(user):
    """user dict'ten KullaniciAdi cikar (auth.py pattern)."""
    if not user:
        return None
    return user.get("KullaniciAdi") or user.get("kullanici_adi")


def _rol_ad(user):
    """user dict'ten RolAd cikar."""
    if not user:
        return None
    return user.get("RolAd")


# ============================================================
# ADMIN KONTROLU
# ============================================================
def is_admin(user):
    """
    Sprint 1.2: auth.is_superadmin standardina baglanildi.
    Tek dogruluk kaynagi: auth.py is_superadmin.
    """
    from modules.auth import is_superadmin as _isa
    return _isa(user)


# ============================================================
# 1) GORME YETKISI
# ============================================================
def can_view_task(task, user):
    """
    Gorevi gorebilir mi?

    Kurallar:
        - admin: her zaman
        - created_by: kendi olusturdugu
        - assigned_to: kendine atanan
        - approval_user_id: onaylamasi gereken
        - department + assigned_to=NULL: birim havuzundaki

    Args:
        task: dict (tasks tablosundan satir)
        user: dict (session.kullanici)

    Returns:
        bool
    """
    if not task or not user:
        return False
    if is_admin(user):
        return True

    kadi = _kullanici_adi(user)
    if not kadi:
        return False

    # Kendisi olusturduysa
    if task.get("created_by") == kadi:
        return True
    # Kendisine atandiysa
    if task.get("assigned_to") == kadi:
        return True
    # Onaylamasi gerekiyorsa
    if task.get("approval_user_id") == kadi:
        return True

    # Birim havuzu (assigned_to NULL ve kullanicinin birimi ile eslesirse)
    # NOT: tasks_users.departman bilgisi user dict'te varsa
    user_dep = user.get("departman") or user.get("Birim")
    if user_dep and task.get("department") == user_dep and not task.get("assigned_to"):
        return True

    return False


# ============================================================
# 2) DUZENLEME YETKISI (title/description/priority/due_date)
# ============================================================
def can_edit_task(task, user):
    """
    Gorevi duzenleyebilir mi?

    Kurallar:
        - admin: her zaman
        - created_by: kendi olusturdugu (sadece terminal degilse)
    """
    if not task or not user:
        return False

    # Terminal state'lerde duzenleme YOK (admin de dahil - audit korumasi)
    if task.get("status") in ("tamamlandi", "iptal"):
        return False

    if is_admin(user):
        return True

    kadi = _kullanici_adi(user)
    return task.get("created_by") == kadi


# ============================================================
# 3) STATUS DEGISTIRME YETKISI
# ============================================================
# Hangi gecisi kim yapabilir
_TRANSITION_PERMISSIONS = {
    # (eski, yeni) -> roller
    ("bekliyor",       "devam_ediyor"):     ("admin", "assigned_to"),
    ("bekliyor",       "iptal"):            ("admin", "created_by"),
    ("devam_ediyor",   "onay_bekliyor"):    ("admin", "assigned_to"),
    ("devam_ediyor",   "tamamlandi"):       ("admin", "assigned_to"),
    ("devam_ediyor",   "iptal"):            ("admin", "created_by"),
    ("onay_bekliyor",  "tamamlandi"):       ("admin", "approval_user_id"),
    ("onay_bekliyor",  "revize_istendi"):   ("admin", "approval_user_id"),
    ("onay_bekliyor",  "iptal"):            ("admin", "created_by"),
    ("revize_istendi", "devam_ediyor"):     ("admin", "assigned_to"),
    ("revize_istendi", "iptal"):            ("admin", "created_by"),
}


def can_change_status(task, user, new_status):
    """
    Bu kullanici task'i bu yeni status'a gecirebilir mi?

    Sadece YETKI kontrolu yapar. Gecisin gecerli olup olmadigini
    service.py'daki ALLOWED_TRANSITIONS kontrol eder.
    """
    if not task or not user:
        return False
    if is_admin(user):
        return True

    old = task.get("status")
    key = (old, new_status)
    roles = _TRANSITION_PERMISSIONS.get(key, ())
    if not roles:
        return False  # Tanimlanmamis gecis

    kadi = _kullanici_adi(user)
    if not kadi:
        return False

    # Roller icinden uygun olani kontrol et
    if "created_by" in roles and task.get("created_by") == kadi:
        return True
    if "assigned_to" in roles and task.get("assigned_to") == kadi:
        return True
    if "approval_user_id" in roles and task.get("approval_user_id") == kadi:
        return True

    return False


# ============================================================
# 4) ONAYLAMA YETKISI (approve/reject)
# ============================================================
def can_approve_task(task, user):
    """
    Gorev onay/reddetme yetkisi var mi?

    Kurallar:
        - admin: her zaman
        - approval_user_id: tanimlanan onaylayan
    """
    if not task or not user:
        return False
    if is_admin(user):
        return True

    kadi = _kullanici_adi(user)
    return task.get("approval_user_id") == kadi


# ============================================================
# Yardimci: hata firlatma
# ============================================================
def require(condition, mesaj="Yetki yok."):
    """
    if not can_x(...): require(False, "...")  yerine
    require(can_x(...), "...")  kullanilabilir.
    """
    if not condition:
        raise PermissionDenied(mesaj)
