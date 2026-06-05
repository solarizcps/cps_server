# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 3 ADIM 2 PATCH UYGULAYICI
=======================================

Bu script:
  1. service.py'nin sonuna 4 yeni fonksiyon ekler (idempotent)
  2. routes.py'deki api_notifications_pending'i degistirir
  3. routes.py sonuna 3 yeni endpoint ekler (idempotent)

Yedek: Her iki dosya patch oncesi YEDEK_FAZ3_ADIM2_<ts> ile yedeklenir.

Idempotent: Tekrar calistirilirsa zarar vermez (zaten varsa SKIP).
"""
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
SERVICE_PY = PROJECT_ROOT / "modules" / "tasks" / "service.py"
ROUTES_PY = PROJECT_ROOT / "modules" / "tasks" / "routes.py"

ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# SERVICE.PY EKLENECEK BLOK
# ============================================================
SERVICE_BLOCK = '''

# ============================================================
# FAZ 3 - OVERLAY NOTIFICATION FONKSIYONLARI
# ============================================================
# Eklendi: Migration 004 sonrasi
# Bagimlilik: bildirim_log yeni kolonlari (snooze_until, dismiss_count, last_shown_at)


def get_pending_notifications(user, since=None, limit=50):
    """
    Aktif (okunmamis, snooze suresi gecmis) bildirimleri dondurur.

    Yetki: Admin tum bildirimleri, diger kullanicilar sadece kendi tasks_user_id'sini.
    Filtre: okundu_mu=0, tip LIKE 'gorev_%', snooze_until IS NULL VEYA <= NOW
    Siralama: priority DESC (kritik>yuksek>orta>dusuk), gonderim_zamani DESC
    """
    is_admin = (user.get("RolAd") in ("Yonetim", "Y\u00f6netim", "Admin", "admin"))

    sql = """
        SELECT
            b.id, b.kullanici_id, b.rol, b.tip, b.mesaj, b.veri_json,
            b.gonderim_zamani, b.okundu_mu, b.okundu_zamani,
            b.snooze_until, b.dismiss_count, b.last_shown_at,
            tu.kullanici_adi
        FROM bildirim_log b
        LEFT JOIN tasks_users tu ON tu.id = b.kullanici_id
        WHERE b.okundu_mu = 0
          AND b.tip LIKE 'gorev_%'
          AND (b.snooze_until IS NULL OR b.snooze_until <= datetime('now', 'localtime'))
    """
    params = []

    if not is_admin:
        tu_id = user.get("tasks_user_id")
        if not tu_id:
            return []
        sql += " AND b.kullanici_id = ?"
        params.append(tu_id)

    if since:
        sql += " AND b.gonderim_zamani > ?"
        params.append(since)

    sql += " ORDER BY b.gonderim_zamani DESC LIMIT ?"
    params.append(int(limit))

    rows = q(sql, tuple(params))

    # Python'da priority sort (veri_json'dan)
    import json as _json
    PRIORITY_ORDER = {"kritik": 4, "yuksek": 3, "orta": 2, "dusuk": 1}

    def _priority_key(row):
        try:
            data = _json.loads(row.get("veri_json") or "{}")
            return PRIORITY_ORDER.get(data.get("priority", "orta"), 2)
        except Exception:
            return 2

    rows.sort(key=lambda r: -_priority_key(r))

    return rows


def _get_notification_or_404(notification_id):
    """Bildirim_log row'u getir, yoksa TaskNotFound."""
    row = qone("SELECT * FROM bildirim_log WHERE id=?", (notification_id,))
    if not row:
        raise TaskNotFound(f"Bildirim bulunamadi: id={notification_id}")
    return row


def _check_notification_permission(notif, user):
    """Bildirim islem yetkisi: admin=true, sahip=true, diger=false."""
    is_admin = (user.get("RolAd") in ("Yonetim", "Y\u00f6netim", "Admin", "admin"))
    if is_admin:
        return True
    tu_id = user.get("tasks_user_id")
    if not tu_id:
        return False
    return notif["kullanici_id"] == tu_id


def mark_notification_read(notification_id, user):
    """
    Bildirimi okundu olarak isaretle. (Devam Ediyorum / Goreve Git)
    Etki: okundu_mu=1, okundu_zamani=NOW
    """
    notif = _get_notification_or_404(notification_id)

    if not _check_notification_permission(notif, user):
        from modules.tasks.permissions import PermissionDenied
        raise PermissionDenied(f"Bu bildirim uzerinde islem yetkiniz yok: id={notification_id}")

    qexec("""
        UPDATE bildirim_log
           SET okundu_mu = 1,
               okundu_zamani = datetime('now', 'localtime')
         WHERE id = ?
    """, (notification_id,))

    return _get_notification_or_404(notification_id)


def dismiss_notification(notification_id, user):
    """
    Overlay'den indir, OKUNDU SAYMA.
    Etki: dismiss_count++, last_shown_at=NOW, okundu_mu=0 KALIR
    """
    notif = _get_notification_or_404(notification_id)

    if not _check_notification_permission(notif, user):
        from modules.tasks.permissions import PermissionDenied
        raise PermissionDenied(f"Bu bildirim uzerinde islem yetkiniz yok: id={notification_id}")

    qexec("""
        UPDATE bildirim_log
           SET dismiss_count = COALESCE(dismiss_count, 0) + 1,
               last_shown_at = datetime('now', 'localtime')
         WHERE id = ?
    """, (notification_id,))

    return _get_notification_or_404(notification_id)


def snooze_notification(notification_id, user, minutes):
    """
    Bildirimi X dakika ertele.
    Etki: snooze_until = NOW + minutes, okundu_mu=0 KALIR
    Allowed minutes: 15, 30, 60, 120, 240
    """
    notif = _get_notification_or_404(notification_id)

    if not _check_notification_permission(notif, user):
        from modules.tasks.permissions import PermissionDenied
        raise PermissionDenied(f"Bu bildirim uzerinde islem yetkiniz yok: id={notification_id}")

    try:
        minutes = int(minutes)
    except (ValueError, TypeError):
        raise ValidationError("minutes integer olmali")

    if minutes not in (15, 30, 60, 120, 240):
        raise ValidationError("minutes su degerlerden biri olmali: 15, 30, 60, 120, 240")

    qexec(f"""
        UPDATE bildirim_log
           SET snooze_until = datetime('now', 'localtime', '+{minutes} minutes'),
               last_shown_at = datetime('now', 'localtime')
         WHERE id = ?
    """, (notification_id,))

    return _get_notification_or_404(notification_id)
'''


# ============================================================
# ROUTES.PY ESKI api_notifications_pending FONKSIYONU (DEGISECEK)
# ============================================================
# Mevcut hali (FAZ 1.5'ten kalma) - bu blogu str_replace ile bulup degistirecegiz.
ROUTES_OLD = '''# ============================================================
# 13) GET /api/tasks/notifications/pending
# ============================================================
@tasks_bp.route("/api/tasks/notifications/pending", methods=["GET"])
def api_notifications_pending():
    user = get_current_task_user()
    if not user:
        return err_json("Oturum acik degil", 401)

    try:
        # tasks_user_id'yi al (bildirim_log INTEGER kullanici_id bekliyor)
        tu_id = user.get("tasks_user_id")
        if not tu_id:
            # tasks_users'da kayit yok -> bos liste
            return ok_json({"count": 0, "notifications": []})

        try:
            limit = int(request.args.get("limit", 50))
            limit = max(1, min(limit, 200))
        except ValueError:
            limit = 50

        rows = q("""
            SELECT id, kullanici_id, rol, tip, mesaj, veri_json,
                   gonderim_zamani, okundu_mu
            FROM bildirim_log
            WHERE kullanici_id=? AND okundu_mu=0
              AND tip LIKE 'gorev_%'
            ORDER BY gonderim_zamani DESC
            LIMIT ?
        """, (tu_id, limit))

        return ok_json({
            "count": len(rows),
            "notifications": rows,
        })
    except Exception as e:
        return handle_service_error(e)'''


# ============================================================
# ROUTES.PY YENI api_notifications_pending + 3 ENDPOINT
# ============================================================
ROUTES_NEW = '''# ============================================================
# 13) GET /api/tasks/notifications/pending  (FAZ 3 GUNCEL)
# ============================================================
@tasks_bp.route("/api/tasks/notifications/pending", methods=["GET"])
def api_notifications_pending():
    """
    Aktif bildirimler (snooze gecmis, okunmamis, gorev_*).
    Admin tumunu, normal kullanici sadece kendisinin gorur.
    Query: since (ISO), limit (max 200).
    """
    user = get_current_task_user()
    if not user:
        return err_json("Oturum acik degil", 401)

    try:
        try:
            limit = int(request.args.get("limit", 50))
            limit = max(1, min(limit, 200))
        except ValueError:
            limit = 50

        since = request.args.get("since")
        rows = tsk.get_pending_notifications(user, since=since, limit=limit)

        return ok_json({
            "count": len(rows),
            "notifications": rows,
            "since": since,
        })
    except Exception as e:
        return handle_service_error(e)


# ============================================================
# 14) POST /api/tasks/notifications/<id>/read  (FAZ 3)
# ============================================================
@tasks_bp.route("/api/tasks/notifications/<int:notification_id>/read", methods=["POST"])
def api_notification_read(notification_id):
    """
    Bildirimi okundu isaretle.
    Kullanim: 'Devam Ediyorum' / 'Goreve Git' butonlari.
    Etki: okundu_mu=1, okundu_zamani=NOW
    """
    user = get_current_task_user()
    if not user:
        return err_json("Oturum acik degil", 401)

    try:
        notif = tsk.mark_notification_read(notification_id, user)
        return ok_json({"notification": notif})
    except Exception as e:
        return handle_service_error(e)


# ============================================================
# 15) POST /api/tasks/notifications/<id>/dismiss  (FAZ 3)
# ============================================================
@tasks_bp.route("/api/tasks/notifications/<int:notification_id>/dismiss", methods=["POST"])
def api_notification_dismiss(notification_id):
    """
    Bildirimi overlay'den indir, OKUNDU SAYMA.
    Etki: dismiss_count++, last_shown_at=NOW, okundu_mu=0 KALIR
    """
    user = get_current_task_user()
    if not user:
        return err_json("Oturum acik degil", 401)

    try:
        notif = tsk.dismiss_notification(notification_id, user)
        return ok_json({"notification": notif})
    except Exception as e:
        return handle_service_error(e)


# ============================================================
# 16) POST /api/tasks/notifications/<id>/snooze  (FAZ 3)
# ============================================================
@tasks_bp.route("/api/tasks/notifications/<int:notification_id>/snooze", methods=["POST"])
def api_notification_snooze(notification_id):
    """
    Bildirimi X dakika ertele.
    Body: {"minutes": 15|30|60|120|240}
    Etki: snooze_until = NOW + minutes
    """
    user = get_current_task_user()
    if not user:
        return err_json("Oturum acik degil", 401)

    try:
        body = request.get_json(silent=True) or {}
        minutes = body.get("minutes", 15)
        notif = tsk.snooze_notification(notification_id, user, minutes)
        return ok_json({"notification": notif, "minutes": minutes})
    except Exception as e:
        return handle_service_error(e)'''


# ============================================================
# IDEMPOTENT MARKER'LAR
# ============================================================
SERVICE_MARKER = "# FAZ 3 - OVERLAY NOTIFICATION FONKSIYONLARI"
ROUTES_MARKER  = "14) POST /api/tasks/notifications/<id>/read"


def patch_service():
    print()
    print("=== SERVICE.PY PATCH ===")

    if not SERVICE_PY.exists():
        print(f"  [HATA] Dosya yok: {SERVICE_PY}")
        return False

    content = SERVICE_PY.read_text(encoding="utf-8")

    if SERVICE_MARKER in content:
        print("  [SKIP] FAZ 3 fonksiyonlari zaten eklenmis")
        return True

    # Yedek
    backup = SERVICE_PY.with_suffix(f".py.YEDEK_FAZ3_ADIM2_{ts}")
    backup.write_text(content, encoding="utf-8")
    print(f"  [OK] Yedek: {backup.name}")

    # Append (sonuna ekle)
    new_content = content.rstrip() + "\n" + SERVICE_BLOCK + "\n"
    SERVICE_PY.write_text(new_content, encoding="utf-8")
    print(f"  [OK] service.py guncellendi ({len(new_content)} byte, +4 fonksiyon)")
    return True


def patch_routes():
    print()
    print("=== ROUTES.PY PATCH ===")

    if not ROUTES_PY.exists():
        print(f"  [HATA] Dosya yok: {ROUTES_PY}")
        return False

    content = ROUTES_PY.read_text(encoding="utf-8")

    if ROUTES_MARKER in content:
        print("  [SKIP] FAZ 3 endpoint'leri zaten eklenmis")
        return True

    # Eski blok var mi
    if ROUTES_OLD not in content:
        print("  [HATA] Mevcut api_notifications_pending bulunamadi!")
        print("  Manuel kontrol gerekli. Eski fonksiyonu bulamadigim icin guvenli replace yapamiyorum.")
        return False

    # Yedek
    backup = ROUTES_PY.with_suffix(f".py.YEDEK_FAZ3_ADIM2_{ts}")
    backup.write_text(content, encoding="utf-8")
    print(f"  [OK] Yedek: {backup.name}")

    # Replace
    new_content = content.replace(ROUTES_OLD, ROUTES_NEW)
    if new_content == content:
        print("  [HATA] Replace yapilamadi!")
        return False

    ROUTES_PY.write_text(new_content, encoding="utf-8")
    print(f"  [OK] routes.py guncellendi ({len(new_content)} byte, +3 endpoint)")
    return True


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 3 ADIM 2 PATCH (Backend)")
    print("=" * 60)

    if not patch_service():
        return 1
    if not patch_routes():
        return 1

    print()
    print("=" * 60)
    print("[OK] ADIM 2 PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki: Flask restart + endpoint testleri")
    return 0


if __name__ == "__main__":
    sys.exit(main())
