import logging
from typing import List, Optional
from pathlib import Path
from PIL import Image
import torch

logger = logging.getLogger(__name__)


class VisionModelError(Exception):
    """Raised when vision model fails."""
    pass


# Global model (loaded only once)
_model = None
_tokenizer = None


def _load_model():
    """Load MiniCPM-V model only once."""
    global _model, _tokenizer

    if _model is not None:
        return _model, _tokenizer

    try:
        from transformers import AutoModel, AutoTokenizer

        logger.info("Loading MiniCPM-V model... (this may take some time on first run)")

        model_name = "openbmb/MiniCPM-V-2_6"

        _tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True
        )

        _model = AutoModel.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            device_map="mps"          # Apple Silicon
        )
        _model.eval()

        logger.info("MiniCPM-V loaded successfully.")
        return _model, _tokenizer

    except Exception as e:
        logger.error(f"Failed to load MiniCPM-V: {e}")
        raise VisionModelError(f"Could not load vision model: {str(e)}")


def analyze_images(image_paths: List[str], prompt: Optional[str] = None) -> str:
    """
    Analyze one or more images using MiniCPM-V and return extracted text.
    """
    if not image_paths:
        return ""

    valid_paths = []
    for path in image_paths:
        p = Path(path)
        if p.exists() and p.is_file():
            valid_paths.append(str(p))
        else:
            logger.warning(f"Image not found, skipping: {path}")

    if not valid_paths:
        return ""

    if prompt is None:
        prompt = (
            "Extract all important text, numbers, tables, and key information from this image. "
            "If it contains a chart or graph, describe the main insights clearly. "
            "Be accurate and structured."
        )

    logger.info(f"Analyzing {len(valid_paths)} image(s) with MiniCPM-V...")

    try:
        model, tokenizer = _load_model()
        results = []

        for img_path in valid_paths:
            image = Image.open(img_path).convert("RGB")
            msgs = [{'role': 'user', 'content': prompt}]

            result = model.chat(
                image=image,
                msgs=msgs,
                tokenizer=tokenizer
            )

            if result and result.strip():
                results.append(result.strip())

        return "\n\n".join(results)

    except Exception as e:
        logger.error(f"Vision model failed: {e}")
        raise VisionModelError(f"Failed to analyze images: {str(e)}")