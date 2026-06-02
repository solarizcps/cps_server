# -*- coding: utf-8 -*-
"""
CPS DEV - Tasks Modulu - Upload Helpers (BACKEND HAZIRLIK)
==========================================================

DOSYA YUKLEME ICIN BACKEND HELPER FONKSIYONLARI.
Bu dosyada HTTP route YOK, frontend kod YOK.
Faz 2'de routes.py'ye eklenecek upload endpoint'i bu helper'lari kullanacak.

KULLANIM:
    from modules.tasks import upload as up

    # 1) Validation
    up.validate_extension("rapor.pdf")          # True
    up.validate_extension("malware.exe")         # False (raise InvalidFileType)
    up.validate_size(file_size_bytes)            # MAX_UPLOAD_MB ile karsilastirir

    # 2) Path uretimi
    path = up.build_storage_path(task_id=42, original_name="LcWaikiki.pdf")
    # -> "uploads/tasks/42/2026-05/<uuid>.pdf"

    # 3) DB insert
    up.insert_task_file(
        task_id=42,
        file_name="LcWaikiki.pdf",
        file_path=path,
        file_type="application/pdf",
        file_size=12345,
        uploaded_by="halil",
    )

KLASOR YAPISI:
    <project_root>/uploads/
        tasks/
            <task_id>/
                <yyyy-mm>/
                    <uuid>.<ext>

GUVENLIK:
    - Extension whitelist (alttaki ALLOWED_EXTENSIONS)
    - Max boyut (Config.MAX_UPLOAD_MB veya 10 MB)
    - secure_filename (Werkzeug)
    - UUID filename (orijinal ad sadece DB'de)
    - Path traversal: os.path.realpath() ile root prefix kontrolu
    - File type sniffing (magic number) - GELECEK

NOT:
    Bu modul DISKE YAZMAZ. Sadece path uretir + DB'ye kayit eder.
    Asil dosya yazimi route handler'da Flask request.files.save() ile yapilir.
"""

import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

from db import qexec, qone


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================
class UploadError(Exception):
    """Generic upload hatasi."""
    pass


class InvalidFileType(UploadError):
    """Whitelist'te olmayan extension."""
    pass


class FileTooLarge(UploadError):
    """Max boyut asildi."""
    pass


class InvalidPath(UploadError):
    """Path traversal denemesi (guvenlik ihlali)."""
    pass


# ============================================================
# WHITELIST + LIMITLER
# ============================================================
ALLOWED_EXTENSIONS = {
    "jpg", "jpeg", "png",
    "pdf",
    "xlsx", "xls",
    "docx", "doc",
}

# Default max boyut (Config.MAX_UPLOAD_MB yoksa)
DEFAULT_MAX_UPLOAD_MB = 10


def _get_max_upload_mb():
    """Config.MAX_UPLOAD_MB varsa onu kullan, yoksa default."""
    try:
        from config import Config
        v = getattr(Config, "MAX_UPLOAD_MB", None)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return DEFAULT_MAX_UPLOAD_MB


# ============================================================
# UPLOAD ROOT PATH (project_root/uploads/tasks)
# ============================================================
def _project_root():
    """C:\\cps_dev veya benzeri - bu dosyadan 2 dizin yukari."""
    # modules/tasks/upload.py -> ../.. = project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_upload_root():
    """uploads/tasks/ tam yolu."""
    return os.path.join(_project_root(), "uploads", "tasks")


# ============================================================
# 1) EXTENSION KONTROLU
# ============================================================
def _extract_extension(filename):
    """Dosya adindan extension'u kucuk harf olarak cikar."""
    if not filename or "." not in filename:
        return ""
    ext = filename.rsplit(".", 1)[-1].lower().strip()
    return ext


def is_allowed_extension(filename):
    """
    Extension whitelist'te mi? bool doner, exception yok.
    """
    ext = _extract_extension(filename)
    return ext in ALLOWED_EXTENSIONS


def validate_extension(filename):
    """
    Whitelist kontrolu. Yoksa InvalidFileType firlatir.

    Returns:
        str: dogrulanmis extension (kucuk harf)
    """
    ext = _extract_extension(filename)
    if not ext:
        raise InvalidFileType(f"Uzantisi olmayan dosya kabul edilmiyor: {filename}")
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileType(
            f"Izin verilmeyen dosya tipi: .{ext}. "
            f"Izin verilenler: {sorted(ALLOWED_EXTENSIONS)}"
        )
    return ext


# ============================================================
# 2) BOYUT KONTROLU
# ============================================================
def validate_size(file_size_bytes):
    """
    Boyut max'i asti mi? Asitysa FileTooLarge firlatir.

    Args:
        file_size_bytes (int)

    Returns:
        int: file_size_bytes (gecerse aynisini doner)
    """
    if file_size_bytes is None or file_size_bytes < 0:
        raise FileTooLarge("Gecersiz dosya boyutu")

    max_mb = _get_max_upload_mb()
    max_bytes = max_mb * 1024 * 1024

    if file_size_bytes > max_bytes:
        raise FileTooLarge(
            f"Dosya cok buyuk: {file_size_bytes / (1024*1024):.2f} MB. "
            f"Max: {max_mb} MB"
        )
    return file_size_bytes


# ============================================================
# 3) GUVENLI DOSYA ADI
# ============================================================
def make_safe_filename(original_name):
    """
    secure_filename + UUID prefix.

    Returns:
        (uuid_filename, safe_original)
            uuid_filename: diske yazilacak ad ('a1b2c3.pdf')
            safe_original: DB'ye yazilacak orijinal ad ('LcWaikiki.pdf')
    """
    if not original_name:
        raise InvalidFileType("Dosya adi bos olamaz")

    # Werkzeug secure_filename: '../', '\0', kontrol karakterleri vb. temizler
    safe = secure_filename(original_name)
    if not safe:
        # secure_filename bos string dondurursa (Turkce karakter vs. cok agresif)
        # fallback: UUID + extension
        ext = _extract_extension(original_name)
        if not ext:
            raise InvalidFileType("Guvenli dosya adi olusturulamadi")
        safe = f"file.{ext}"

    # Validation
    ext = validate_extension(safe)

    # UUID filename (diske bu ad ile yazilacak)
    uuid_part = uuid.uuid4().hex[:16]
    uuid_filename = f"{uuid_part}.{ext}"

    return uuid_filename, safe


# ============================================================
# 4) PATH URETIMI
# ============================================================
def build_storage_path(task_id, original_name):
    """
    Tam disk path uretir:
        <upload_root>/<task_id>/<yyyy-mm>/<uuid>.<ext>

    Args:
        task_id (int)
        original_name (str): orijinal dosya adi

    Returns:
        dict: {
            'absolute_path':  tam disk yolu,
            'relative_path':  upload_root'a gore goreceli,
            'uuid_filename':  diske yazilacak ad,
            'safe_original':  DB icin temiz orijinal ad,
            'extension':      uzanti
        }

    Raises:
        InvalidFileType, InvalidPath
    """
    if not task_id or int(task_id) <= 0:
        raise UploadError(f"Gecersiz task_id: {task_id}")

    uuid_name, safe_orig = make_safe_filename(original_name)
    ext = _extract_extension(uuid_name)

    yyyy_mm = datetime.now().strftime("%Y-%m")

    upload_root = get_upload_root()
    abs_dir = os.path.join(upload_root, str(int(task_id)), yyyy_mm)
    abs_path = os.path.join(abs_dir, uuid_name)

    # PATH TRAVERSAL KORUMASI:
    # abs_path realpath'i upload_root altinda mi?
    real_root = os.path.realpath(upload_root)
    real_target = os.path.realpath(abs_path)

    # Windows'ta case-insensitive karsilastirma
    if os.name == "nt":
        if not real_target.lower().startswith(real_root.lower() + os.sep) and real_target.lower() != real_root.lower():
            raise InvalidPath(f"Path traversal denemesi: {abs_path}")
    else:
        if not real_target.startswith(real_root + os.sep) and real_target != real_root:
            raise InvalidPath(f"Path traversal denemesi: {abs_path}")

    # Goreceli yol (DB'ye bunu yazariz)
    rel_path = os.path.relpath(abs_path, _project_root()).replace("\\", "/")

    return {
        "absolute_path":  abs_path,
        "relative_path":  rel_path,
        "directory":      abs_dir,
        "uuid_filename":  uuid_name,
        "safe_original":  safe_orig,
        "extension":      ext,
    }


def ensure_directory(directory):
    """Klasoru olustur (yoksa). Faz 2'de route handler cagiracak."""
    if not directory:
        raise InvalidPath("Bos directory")
    os.makedirs(directory, exist_ok=True)
    return directory


# ============================================================
# 5) DB INSERT (task_files)
# ============================================================
def insert_task_file(task_id, file_name, file_path, file_type, file_size, uploaded_by):
    """
    task_files tablosuna kayit ekle.

    Args:
        task_id (int):       FK -> tasks.id
        file_name (str):     orijinal dosya adi (kullanicinin verdigi)
        file_path (str):     diske yazilan yol (relative)
        file_type (str):     mime type (ornek: 'application/pdf')
        file_size (int):     byte
        uploaded_by (str):   tasks_users.kullanici_adi

    Returns:
        int: yeni task_files.id

    Raises:
        UploadError
    """
    # Task var mi?
    t = qone("SELECT id FROM tasks WHERE id=?", (int(task_id),))
    if not t:
        raise UploadError(f"Task bulunamadi: {task_id}")

    if not file_name or not file_path or not uploaded_by:
        raise UploadError("file_name, file_path, uploaded_by zorunlu")

    new_id = qexec("""
        INSERT INTO task_files (
            task_id, file_name, file_path, file_type, file_size, uploaded_by
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        int(task_id),
        file_name,
        file_path,
        file_type,
        int(file_size) if file_size is not None else None,
        uploaded_by,
    ))

    if not new_id:
        # Fallback: en son insert'i bul
        r = qone("""
            SELECT id FROM task_files
            WHERE task_id=? AND file_path=? AND uploaded_by=?
            ORDER BY id DESC LIMIT 1
        """, (int(task_id), file_path, uploaded_by))
        if r:
            new_id = r["id"]

    if not new_id:
        raise UploadError("task_files insert basarisiz, id alinamadi")

    return new_id


# ============================================================
# 6) SOFT DELETE
# ============================================================
def soft_delete_task_file(file_id):
    """task_files.deleted = 1 yap (fiziki silme YOK)."""
    if not file_id:
        raise UploadError("file_id bos")
    qexec("UPDATE task_files SET deleted = 1 WHERE id = ?", (int(file_id),))


# ============================================================
# 7) HELPER: MIME GUESS (basit)
# ============================================================
_MIME_MAP = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "pdf":  "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
}


def guess_mime_type(filename):
    """Extension'a gore mime tahmini."""
    ext = _extract_extension(filename)
    return _MIME_MAP.get(ext, "application/octet-stream")
