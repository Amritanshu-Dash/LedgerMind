import logging
from pathlib import Path
from typing import Dict, Any
import tempfile
import os
import io

import fitz  # pymupdf
from docx import Document
from PIL import Image

# ============================================================
# VISION MODEL SWITCH
# Just comment / uncomment the model you want to use
# ============================================================

from .vision_model import analyze_images                  # ← Currently Active (MiniCPM-V)

# from .vision_model_florence import analyze_images
# from .vision_model_llava import analyze_images
# from .vision_model_moondream import analyze_images
# from .vision_model_qwen import analyze_images

# ============================================================

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when content extraction fails."""
    pass


def extract_content(file_path: str) -> Dict[str, Any]:
    """
    Main function: Extract all useful content from a document.
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    logger.info(f"Extracting content from: {path.name} ({suffix})")

    try:
        if suffix == ".pdf":
            return _extract_pdf(path)
        elif suffix == ".docx":
            return _extract_docx(path)
        elif suffix in [".txt", ".md"]:
            return _extract_txt(path)
        elif suffix in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
            return _extract_image(path)
        else:
            raise ExtractionError(f"Unsupported file type: {suffix}")

    except Exception as e:
        logger.error(f"Extraction failed for {path.name}: {e}")
        raise ExtractionError(f"Failed to extract content: {str(e)}")


def _extract_pdf(path: Path) -> Dict[str, Any]:
    doc = fitz.open(path)
    normal_text_parts = []
    image_paths = []

    with tempfile.TemporaryDirectory(prefix="pdf_images_") as temp_dir:
        try:
            for page in doc:
                text = page.get_text("text").strip()
                if text:
                    normal_text_parts.append(text)

                for img in page.get_images(full=True):
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        temp_path = Path(temp_dir) / f"image_{xref}.{image_ext}"
                        temp_path.write_bytes(image_bytes)
                        image_paths.append(str(temp_path))
                    except Exception as ex:
                        logger.warning(f"Skipping unreadable image: {ex}")
        finally:
            doc.close()

        normal_text = "\n\n".join(normal_text_parts).strip()
        vision_text = ""

        if image_paths:
            vision_text = analyze_images(image_paths)

    final_text = _combine_text(normal_text, vision_text)

    return {
        "text": final_text,
        "normal_text": normal_text,
        "vision_text": vision_text,
        "images_found": len(image_paths),
        "file_type": "pdf"
    }


def _extract_docx(path: Path) -> Dict[str, Any]:
    doc = Document(path)
    normal_text_parts = []
    image_paths = []

    with tempfile.TemporaryDirectory(prefix="docx_images_") as temp_dir:
        for para in doc.paragraphs:
            if para.text.strip():
                normal_text_parts.append(para.text.strip())

        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    image_data = rel.target_part.blob
                    image = Image.open(io.BytesIO(image_data))

                    temp_path = Path(temp_dir) / f"image_{len(image_paths)}.png"
                    image.save(str(temp_path))
                    image_paths.append(str(temp_path))
                except Exception as ex:
                    logger.warning(f"Skipping unreadable image in docx: {ex}")

        normal_text = "\n\n".join(normal_text_parts).strip()
        vision_text = ""

        if image_paths:
            vision_text = analyze_images(image_paths)

    final_text = _combine_text(normal_text, vision_text)

    return {
        "text": final_text,
        "normal_text": normal_text,
        "vision_text": vision_text,
        "images_found": len(image_paths),
        "file_type": "docx"
    }


def _extract_txt(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read().strip()

    return {
        "text": text,
        "normal_text": text,
        "vision_text": "",
        "images_found": 0,
        "file_type": "txt"
    }


def _extract_image(path: Path) -> Dict[str, Any]:
    vision_text = analyze_images([str(path)])

    return {
        "text": vision_text,
        "normal_text": "",
        "vision_text": vision_text,
        "images_found": 1,
        "file_type": "image"
    }


def _combine_text(normal_text: str, vision_text: str) -> str:
    parts = []
    if normal_text:
        parts.append(normal_text)
    if vision_text:
        parts.append("\n\n--- Content from Images ---\n\n" + vision_text)
    return "\n\n".join(parts).strip()