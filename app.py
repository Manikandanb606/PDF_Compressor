import os
import re
import time
import uuid
import shutil
import tempfile
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
from PIL import Image
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "temp" / "uploads"
OUTPUT_DIR = BASE_DIR / "temp" / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit


def parse_target_size(value: str, unit: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Target size must be a valid number.")

    if number <= 0:
        raise ValueError("Target size must be greater than zero.")

    multiplier = {"KB": 1024, "MB": 1024 * 1024}
    if unit not in multiplier:
        raise ValueError("Unit must be KB or MB.")

    return int(number * multiplier[unit])


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def flatten_for_jpeg(image: Image.Image) -> Image.Image:
    """Convert PDF image to a JPEG-safe RGB image."""
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A")
        background.paste(image.convert("RGB"), mask=alpha)
        return background

    if image.mode == "P":
        if "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", image.size, "white")
            background.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")

    return image.convert("RGB")


def compress_images(source_pdf: Path, output_pdf: Path, quality: int, max_dimension: int | None = None) -> dict:
    """
    Recompress embedded raster images and save an optimized PDF.

    Text/vector content remains as PDF content. Only images are recompressed.
    If a PDF contains unusual image types that cannot be safely replaced,
    those images are left untouched.
    """
    doc = fitz.open(source_pdf)
    processed_xrefs = set()
    changed = 0

    try:
        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in processed_xrefs:
                    continue
                processed_xrefs.add(xref)

                try:
                    extracted = doc.extract_image(xref)
                    raw = extracted["image"]
                    pil = Image.open(__import__("io").BytesIO(raw))

                    # Do not recompress tiny images; overhead can make them larger.
                    if pil.width < 80 or pil.height < 80:
                        continue

                    pil = flatten_for_jpeg(pil)

                    if max_dimension and max(pil.size) > max_dimension:
                        scale = max_dimension / max(pil.size)
                        new_size = (
                            max(1, int(pil.width * scale)),
                            max(1, int(pil.height * scale)),
                        )
                        pil = pil.resize(new_size, Image.Resampling.LANCZOS)

                    out = __import__("io").BytesIO()
                    pil.save(out, format="JPEG", quality=quality)
                    jpeg_bytes = out.getvalue()

                    # Only replace when it actually saves space.
                    if len(jpeg_bytes) < len(raw) * 0.98:
                        page.replace_image(xref, stream=jpeg_bytes)
                        changed += 1
                except Exception:
                    # Leave unsupported/problematic images unchanged.
                    continue

        doc.save(
            output_pdf,
            garbage=4,
            deflate=True,
            clean=True,
            use_objstms=True,
        )
    finally:
        doc.close()

    return {"images_changed": changed}


def rebuild_as_images(source_pdf: Path, output_pdf: Path, dpi: int, quality: int) -> None:
    """
    Last-resort target-size method.

    Each page is rendered to JPEG and rebuilt as a PDF page.
    This can achieve much smaller files, but the resulting PDF is image-based
    and text will no longer be selectable/searchable.
    """
    src = fitz.open(source_pdf)
    dst = fitz.open()

    try:
        for page in src:
            pix = page.get_pixmap(
                dpi=dpi,
                colorspace=fitz.csRGB,
                alpha=False,
                annots=True,
            )

            # JPEG encode the rendered page.
            jpeg = pix.tobytes("jpg", jpg_quality=quality)

            rect = page.rect
            new_page = dst.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, stream=jpeg)

        dst.save(
            output_pdf,
            garbage=4,
            deflate=True,
            clean=True,
            use_objstms=True,
        )
    finally:
        src.close()
        dst.close()


def attempt_target(source_pdf: Path, target_bytes: int, output_dir: Path) -> tuple[Path, dict]:
    """
    Fast compression path.

    Keep the original PDF structure where possible and make only a small
    number of compression passes. This avoids the many full-document passes
    that made compression slow. If the target still cannot be reached, use
    one rasterized fallback pass.
    """
    candidates = []

    # Fast first pass: preserve text/vector content and recompress images.
    # A single practical quality level avoids spending time on many retries.
    out = output_dir / "preserve_fast.pdf"
    compress_images(source_pdf, out, quality=55, max_dimension=2000)
    if out.exists():
        size = out.stat().st_size
        candidates.append((size, out, "preserve", 55, None))
        if size <= target_bytes:
            return out, {
                "mode": "Preserve text/vector",
                "quality": 55,
                "dpi": None,
                "size": size,
                "target_met": True,
            }

    # One stronger image pass only when the first pass did not reach target.
    out = output_dir / "preserve_fast_strong.pdf"
    compress_images(source_pdf, out, quality=40, max_dimension=1600)
    if out.exists():
        size = out.stat().st_size
        candidates.append((size, out, "preserve", 40, None))
        if size <= target_bytes:
            return out, {
                "mode": "Preserve text/vector",
                "quality": 40,
                "dpi": None,
                "size": size,
                "target_met": True,
            }

    # One raster fallback. This is much faster than trying 10+ DPI/quality
    # combinations, while still providing a practical small PDF when needed.
    out = output_dir / "raster_fast.pdf"
    try:
        rebuild_as_images(source_pdf, out, dpi=90, quality=50)
    except Exception:
        out = None

    if out is not None and out.exists():
        size = out.stat().st_size
        candidates.append((size, out, "raster", 50, 90))
        if size <= target_bytes:
            return out, {
                "mode": "Page image fallback",
                "quality": 50,
                "dpi": 90,
                "size": size,
                "target_met": True,
            }

    if not candidates:
        raise RuntimeError("The PDF could not be compressed.")

    smallest = min(candidates, key=lambda x: x[0])
    return smallest[1], {
        "mode": "Best available",
        "quality": smallest[3],
        "dpi": smallest[4],
        "size": smallest[0],
        "target_met": smallest[0] <= target_bytes,
    }


def cleanup_old_files(max_age_seconds: int = 3600):
    now = time.time()
    for folder in (UPLOAD_DIR, OUTPUT_DIR):
        for item in folder.iterdir():
            try:
                if now - item.stat().st_mtime > max_age_seconds:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
            except OSError:
                pass


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/compress")
def compress():
    cleanup_old_files()

    uploaded = request.files.get("pdf")
    target = request.form.get("target")
    unit = request.form.get("unit", "MB")

    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Please select a PDF file."}), 400

    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    try:
        target_bytes = parse_target_size(target, unit)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Refuse impossible/unsafe tiny target values.
    if target_bytes < 10 * 1024:
        return jsonify({"error": "Please use a target of at least 10 KB."}), 400

    original_name = secure_filename(uploaded.filename)
    job_id = uuid.uuid4().hex
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    source_pdf = UPLOAD_DIR / f"{job_id}_{original_name}"
    uploaded.save(source_pdf)

    try:
        # Validate PDF.
        test = fitz.open(source_pdf)
        page_count = test.page_count
        test.close()

        original_size = source_pdf.stat().st_size

        # Already below target: don't alter it unnecessarily.
        if original_size <= target_bytes:
            result_pdf = job_dir / f"{Path(original_name).stem}_compressed.pdf"
            shutil.copy2(source_pdf, result_pdf)
            info = {
                "mode": "Original already within target",
                "quality": None,
                "dpi": None,
                "size": original_size,
                "target_met": True,
            }
        else:
            result_pdf, info = attempt_target(source_pdf, target_bytes, job_dir)

        download_name = f"{Path(original_name).stem}_compressed.pdf"

        response = send_file(
            result_pdf,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

        # Headers let the browser UI know what happened.
        response.headers["X-Original-Size"] = str(original_size)
        response.headers["X-Compressed-Size"] = str(info["size"])
        response.headers["X-Target-Size"] = str(target_bytes)
        response.headers["X-Page-Count"] = str(page_count)
        response.headers["X-Target-Met"] = "true" if info["target_met"] else "false"
        response.headers["X-Compression-Mode"] = info["mode"]
        response.headers["Access-Control-Expose-Headers"] = (
            "X-Original-Size, X-Compressed-Size, X-Target-Size, "
            "X-Page-Count, X-Target-Met, X-Compression-Mode"
        )
        return response

    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": f"Compression failed: {exc}"}), 500
    finally:
        source_pdf.unlink(missing_ok=True)


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File is too large. Maximum upload size is 50 MB."}), 413


if __name__ == "__main__":
    print("PDF Toolkit running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
