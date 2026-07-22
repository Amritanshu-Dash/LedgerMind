"""
vision_model.py – LLaVA 1.6 Mistral 7B (4-bit) via llama-cpp-python.
Implements analyze_images(image_paths) -> str
"""

import atexit
import logging
from typing import List
from pathlib import Path

from llama_cpp import Llama, llama_cpp
from llama_cpp.llama_chat_format import Llava15ChatHandler

import os
# Point to the Metal shader files bundled with llama-cpp-python
os.environ["GGML_METAL_PATH_RESOURCES"] = "/path/to/llama.cpp/ggml/src/ggml-metal/metal"

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION – paths to your downloaded model files
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent   # now LedgerMind root

MODEL_PATH = PROJECT_ROOT / "models" / "llava-v1.6-mistral-7b.Q4_K_M.gguf"
MMPROJ_PATH = PROJECT_ROOT / "models" / "mmproj-model-f16.gguf"

# Lazy-load model once at module level
_llm = None
_chat_handler = None


def _load_model():
    global _llm, _chat_handler
    if _llm is not None:
        return

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")
    if not MMPROJ_PATH.exists():
        raise FileNotFoundError(f"mmproj not found: {MMPROJ_PATH}")

    logger.info("Loading LLaVA 1.6 model …")

    _chat_handler = Llava15ChatHandler(
        clip_model_path=str(MMPROJ_PATH),
        verbose=False
    )

    _llm = Llama(
        model_path=str(MODEL_PATH),
        chat_handler=_chat_handler,
        n_ctx=4096,          # context window for the LLM (image + prompt)
        n_gpu_layers=-1,     # offload all layers to Metal (M1 GPU)
        n_batch=512,          # faster image encoding
        verbose=False,
        logits_all=False,
    )
    logger.info("LLaVA 1.6 model loaded successfully.")

    # Register cleanup on exit to avoid Metal crash
    atexit.register(_cleanup_model)

def _cleanup_model():
    global _llm, _chat_handler
    if _llm is not None:
        logger.debug("Cleaning up model and Metal backend...")
        _llm = None
        _chat_handler = None
        #Force garbage collection to free GPU memory and backend resources
        try:
            llama_cpp.llama_backend_free()
        except Exception as e:
            logger.warning(f"Error during backend cleanup: {e}")
            pass

def analyze_images(image_paths: List[str]) -> str:
    """
    Accepts a list of image file paths, runs the VLM on each,
    and returns concatenated descriptions.
    """
    _load_model()

    descriptions = []

    for img_path in image_paths:
        img_path = Path(img_path)
        if not img_path.exists():
            logger.warning(f"Image not found: {img_path}, skipping.")
            continue

        logger.info(f"Analyzing image: {img_path.name}")

        # --- Customise this prompt to match your extraction needs ---
        prompt = (
            "Describe this image in detail. Include all visible text, numbers, "
            "tables, charts, or diagrams. If there is a table, reproduce it as markdown."
        )

        try:
            response = _llm.create_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts all information from images."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"file://{img_path.absolute()}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                max_tokens=512,      # increase if you need longer descriptions
                temperature=0.0,     # deterministic output
            )
            desc = response["choices"][0]["message"]["content"].strip()
            descriptions.append(f"[Image: {img_path.name}]\n{desc}")
        except Exception as e:
            logger.error(f"Failed to analyze {img_path}: {e}")
            descriptions.append(f"[Image: {img_path.name}]\nError: {e}")

    return "\n\n".join(descriptions)



""" ejndfcdjnfk """
print(analyze_images(["/Users/amritanshudash/Desktop/LedgerMind/PHOTO-2026-02-15-13-14-11.jpg"]))