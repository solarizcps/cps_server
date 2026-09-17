# -*- coding: utf-8 -*-

"""Planlama > Aktif Kalıplar — PHASE_5 preview DB CRUD."""

from __future__ import annotations



import hashlib

import json

import uuid

from pathlib import Path



from flask import Blueprint, render_template, jsonify, url_for, request, session, send_file

from werkzeug.utils import secure_filename



from modules.auth import login_gerekli

from modules.planlama import mold_library_db as mldb

from modules.planlama.mold_library_normalize import normalize_product_type, build_business_key



aktif_kaliplar_bp = Blueprint(

    "aktif_kaliplar_bp",

    __name__,

    url_prefix="/planlama",

)



_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}

_MAX_IMAGE_BYTES = 5 * 1024 * 1024





def _image_url_for(rec: dict) -> str | None:

    key = rec.get("image_storage_key") or rec.get("image_asset")

    if not key:

        return None

    if "/" in str(key) or "\\" in str(key):

        key = Path(str(key)).name

    try:

        return url_for("aktif_kaliplar_bp.aktif_kaliplar_gorsel", storage_key=key)

    except RuntimeError:

        return f"/planlama/aktif-kaliplar/gorsel/{key}"





def _attach_image_urls(records: list[dict]) -> None:

    for r in records:

        r["image_url"] = _image_url_for(r)





def _current_user() -> str:

    u = session.get("kullanici_adi")

    if u:

        return str(u)

    k = session.get("kullanici")

    if isinstance(k, dict):

        return str(k.get("KullaniciAdi") or k.get("AdSoyad") or "unknown")

    return str(k or "unknown")





def _parse_payload_form() -> tuple[dict | None, str | None]:

    raw_payload = request.form.get("payload", "")

    try:

        return json.loads(raw_payload), None

    except (ValueError, TypeError):

        return None, "Geçersiz payload JSON"





def _validate_weight_pisirme(p: dict) -> list[str]:
    errs = []
    g = p.get("gramaj_gr")
    if g is not None and g != "":
        try:
            gv = float(g)
            if gv < 50 or gv > 2000:
                errs.append("Bir Çift Ürün Gramajı (g) 50–2000 aralığında olmalı")
        except (TypeError, ValueError):
            errs.append("Bir Çift Ürün Gramajı (g) geçersiz")
    ps = p.get("pisirme_suresi_sn")
    if ps is not None and ps != "":
        try:
            pv = float(ps)
            if pv <= 0 or pv > 9999:
                errs.append("Pişme Süresi (sn) pozitif saniye değeri olmalı (max 9999 sn)")
        except (TypeError, ValueError):
            errs.append("Pişme Süresi (sn) geçersiz")
    return errs


def _validate_draft_payload(p: dict) -> list[str]:
    errs = []
    if not (p.get("model_kod") or p.get("visible_mold_code")):
        errs.append("Taslak için model kodu veya kalıp kodu gerekli")
    errs.extend(_validate_weight_pisirme(p))
    return errs


def _validate_full_payload(p: dict) -> list[str]:
    errs = []
    labels = {
        "model_kod": "Model kodu zorunlu",
        "visible_mold_code": "Enjeksiyon kalıp kodu zorunlu",
        "product_category": "Ana ürün ailesi zorunlu",
        "durum": "Durum zorunlu",
    }
    for fld, msg in labels.items():
        if not str(p.get(fld, "")).strip():
            errs.append(msg)
    if p.get("durum") == "TASLAK":
        errs.append("Tam kayıt için durum Taslak olamaz")
    if p.get("cift_miktari") is None:
        errs.append("Kalıp çıkış adedi zorunlu")
    asorti = (p.get("asorti") or "").strip()
    bas, bit = p.get("asorti_bas"), p.get("asorti_bit")
    if not asorti and (bas is None or bit is None or str(bas).strip() == "" or str(bit).strip() == ""):
        errs.append("Asorti bilgisi zorunlu")
    if bas is not None and bit is not None:
        try:
            if int(bit) < int(bas):
                errs.append("Asorti bitiş başlangıçtan küçük olamaz")
        except (TypeError, ValueError):
            pass
    seri = p.get("seri_rows") or []
    if not seri:
        errs.append("En az bir seri satırı zorunlu")
    for i, sr in enumerate(seri, 1):
        lbl = str(sr.get("size_label") or sr.get("numara") or "").strip()
        if not lbl:
            errs.append(f"Seri satır {i}: Numara/Asorti zorunlu")
            continue
        qty = sr.get("mold_quantity") if sr.get("mold_quantity") is not None else sr.get("kalip_adedi")
        cikis = sr.get("output_pair") if sr.get("output_pair") is not None else sr.get("kalip_cikisi_row")
        try:
            if qty is None or int(qty) < 1:
                errs.append(f"Seri satır {i}: Kalıp adedi pozitif tam sayı olmalı")
        except (TypeError, ValueError):
            errs.append(f"Seri satır {i}: Kalıp adedi pozitif tam sayı olmalı")
        try:
            if cikis is None or int(cikis) < 1:
                errs.append(f"Seri satır {i}: Çevrim başına çıkış pozitif tam sayı olmalı")
        except (TypeError, ValueError):
            errs.append(f"Seri satır {i}: Çevrim başına çıkış pozitif tam sayı olmalı")
    errs.extend(_validate_weight_pisirme(p))
    return errs





def _process_image_upload() -> tuple[bytes | None, str | None, str | None, str | None]:

    img_file = request.files.get("gorsel")

    if not img_file or not img_file.filename:

        return None, None, None, None

    ext = Path(img_file.filename).suffix.lower()

    if ext not in _ALLOWED_EXT:

        return None, f"İzin verilmeyen görsel formatı: {ext}", None, None

    content = img_file.read()

    if len(content) > _MAX_IMAGE_BYTES:

        return None, "Görsel 5 MB sınırını aşıyor", None, None

    safe_name = secure_filename(img_file.filename) or f"upload_{uuid.uuid4().hex[:8]}{ext}"

    sha = hashlib.sha256(content).hexdigest().upper()

    return content, None, ext, sha





@aktif_kaliplar_bp.route("/aktif-kaliplar/")

@login_gerekli

def aktif_kaliplar():

    return render_template("planlama/aktif_kaliplar.html")





@aktif_kaliplar_bp.route("/aktif-kaliplar/fixture.json")

@login_gerekli

def aktif_kaliplar_fixture():

    fx = mldb.build_fixture_payload()

    _attach_image_urls(fx.get("records", []))

    return jsonify(fx)





@aktif_kaliplar_bp.route("/aktif-kaliplar/gorsel/<storage_key>")

@login_gerekli

def aktif_kaliplar_gorsel(storage_key: str):

    path = mldb.image_file_path(storage_key)

    if not path:

        return jsonify({"error": "Görsel bulunamadı"}), 404

    return send_file(path)





@aktif_kaliplar_bp.route("/aktif-kaliplar/audit/<library_uuid>")

@login_gerekli

def aktif_kaliplar_audit(library_uuid: str):

    rows = mldb.get_audit_trail(library_uuid)

    return jsonify({"ok": True, "audit": rows})





@aktif_kaliplar_bp.route("/aktif-kaliplar/yeni-kalip", methods=["POST"])

@login_gerekli

def aktif_kaliplar_yeni():

    p, err = _parse_payload_form()

    if err:

        return jsonify({"ok": False, "error": err}), 400



    mat = (p.get("material_group") or "EVA").strip().upper()

    if mat == "POLI" and not mldb.POLI_ACTIVE:

        p["_poli_library_only"] = True



    is_draft = bool(p.get("is_draft", False))

    raw_cat = (p.get("product_category") or "").strip()

    _, product_cat = normalize_product_type(raw_cat)

    p["product_category"] = product_cat



    if is_draft:
        errs = _validate_draft_payload(p)
        if errs:
            return jsonify({"ok": False, "error": "; ".join(errs)}), 422
    else:
        errs = _validate_full_payload(p)
        if errs:
            return jsonify({"ok": False, "error": "; ".join(errs)}), 422



    img_content, img_err, img_ext, img_sha = _process_image_upload()

    if img_err:

        return jsonify({"ok": False, "error": img_err}), 422



    try:

        rec = mldb.create_mold(p, _current_user(), img_content, img_ext, img_sha)

        return jsonify({

            "ok": True,

            "uuid": rec.get("library_uuid"),

            "source_seq": rec.get("source_seq"),

            "visible_mold_code": rec.get("visible_mold_code"),

            "is_draft": is_draft,

            "poli_library_only": mat == "POLI" and not mldb.POLI_ACTIVE,

            "PREVIEW_DB_WRITTEN": True,

            "LEGACY_TABLES_MODIFIED": False,

        }), 201

    except ValueError as ve:

        if str(ve) == "DUPLICATE":

            return jsonify({"ok": False, "duplicate": True, "error": "Aynı bileşik anahtarla kayıt zaten mevcut"}), 409

        return jsonify({"ok": False, "error": str(ve)}), 422

    except Exception:

        return jsonify({"ok": False, "error": "Kayıt oluşturulamadı"}), 500





@aktif_kaliplar_bp.route("/aktif-kaliplar/duzenle", methods=["POST"])

@login_gerekli

def aktif_kaliplar_duzenle():

    p, err = _parse_payload_form()

    if err:

        return jsonify({"ok": False, "error": err}), 400



    source_seq = p.get("source_seq")

    if not source_seq:

        return jsonify({"ok": False, "error": "source_seq zorunlu"}), 422



    raw_cat = (p.get("product_category") or "").strip()

    _, norm_cat = normalize_product_type(raw_cat)

    p["product_category"] = norm_cat



    p["asorti"] = (
        f"{p.get('asorti_bas')}-{p.get('asorti_bit')}"
        if p.get("asorti_bas") is not None and p.get("asorti_bit") is not None
        and str(p.get("asorti_bas")).strip() and str(p.get("asorti_bit")).strip()
        else (p.get("asorti") or "")
    )
    if (p.get("durum") or "").upper() == "TASLAK":
        errs = _validate_draft_payload(p)
    else:
        errs = _validate_full_payload(p)
    if errs:
        return jsonify({"ok": False, "error": "; ".join(errs)}), 422



    remove_image = bool(p.get("remove_image"))

    img_content, img_err, img_ext, img_sha = _process_image_upload()

    if img_err:

        return jsonify({"ok": False, "error": img_err}), 422



    try:

        after = mldb.update_mold(

            int(source_seq), p, _current_user(),

            img_content, img_ext, img_sha, remove_image=remove_image,

        )

        return jsonify({

            "ok": True,

            "source_seq": int(source_seq),

            "row_version": after.get("row_version"),

            "PREVIEW_DB_WRITTEN": True,

            "LEGACY_TABLES_MODIFIED": False,

        }), 200

    except ValueError as ve:

        code = str(ve)

        if code == "NOT_FOUND":

            return jsonify({"ok": False, "error": "Kayıt bulunamadı"}), 404

        if code == "DUPLICATE":

            return jsonify({"ok": False, "duplicate": True, "error": "Aynı bileşik anahtarla başka kayıt mevcut"}), 409

        if code == "VERSION_CONFLICT":

            return jsonify({"ok": False, "conflict": True, "error": "Kayıt başka oturumda güncellendi; yenileyin"}), 409

        return jsonify({"ok": False, "error": code}), 422

    except Exception:

        return jsonify({"ok": False, "error": "Düzenleme başarısız"}), 500





@aktif_kaliplar_bp.route("/aktif-kaliplar/arsivle", methods=["POST"])

@login_gerekli

def aktif_kaliplar_arsivle():

    p, err = _parse_payload_form()

    if err:

        return jsonify({"ok": False, "error": err}), 400

    source_seq = p.get("source_seq")

    reason = (p.get("change_reason") or "").strip()

    if not source_seq:

        return jsonify({"ok": False, "error": "source_seq zorunlu"}), 422

    if not reason:

        return jsonify({"ok": False, "error": "Arşiv gerekçesi zorunlu"}), 422

    try:

        mldb.archive_mold(int(source_seq), _current_user(), reason)

        return jsonify({"ok": True, "PREVIEW_DB_WRITTEN": True}), 200

    except ValueError:

        return jsonify({"ok": False, "error": "Kayıt bulunamadı"}), 404

    except Exception:

        return jsonify({"ok": False, "error": "Arşivleme başarısız"}), 500





@aktif_kaliplar_bp.route("/aktif-kaliplar/geri-aktive", methods=["POST"])

@login_gerekli

def aktif_kaliplar_geri_aktive():

    p, err = _parse_payload_form()

    if err:

        return jsonify({"ok": False, "error": err}), 400

    source_seq = p.get("source_seq")

    reason = (p.get("change_reason") or "Geri aktive").strip()

    if not source_seq:

        return jsonify({"ok": False, "error": "source_seq zorunlu"}), 422

    try:

        mldb.restore_mold(int(source_seq), _current_user(), reason)

        return jsonify({"ok": True, "PREVIEW_DB_WRITTEN": True}), 200

    except ValueError as ve:

        code = str(ve)

        if code == "NOT_FOUND":

            return jsonify({"ok": False, "error": "Kayıt bulunamadı"}), 404

        if code.startswith("RESTORE_CONFLICT"):

            parts = code.split("|")

            active_seq = int(parts[1]) if len(parts) > 1 else None

            return jsonify({

                "ok": False,

                "conflict": True,

                "error": "Aynı model, kalıp kodu, ürün tipi ve asortiyle aktif bir kayıt bulunuyor. Önce mevcut kaydı inceleyin.",

                "active_source_seq": active_seq,

            }), 409

        return jsonify({"ok": False, "error": code}), 422

    except Exception:

        return jsonify({"ok": False, "error": "Geri aktive başarısız"}), 500

