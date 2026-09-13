"""
Loads Qwen 9B once and answers with text only.
Do not run this at the same time as the LLaVA worker — one GGUF in RAM.
"""
import logging
from typing import List, Dict

from src.brain._00_constants import (
    QWEN_GGUF,
    QWEN_CONTEXT_TOKENS,
    QWEN_MAX_ANSWER_TOKENS,
)

logger = logging.getLogger(__name__)

_llm = None


def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    if not QWEN_GGUF.exists():
        raise FileNotFoundError(
            f"Qwen file missing: {QWEN_GGUF}\nRun: python download_models.py"
        )
    from llama_cpp import Llama

    logger.info(f"Loading Qwen from {QWEN_GGUF}")
    _llm = Llama(
        model_path=str(QWEN_GGUF),
        n_ctx=QWEN_CONTEXT_TOKENS,
        n_gpu_layers=-1,
        verbose=False,
    )
    return _llm


def generate(messages: List[Dict[str, str]]) -> str:
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=QWEN_MAX_ANSWER_TOKENS,
        temperature=0.2,
    )
    return out["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    text = generate([
        {"role": "system", "content": "You are LedgerMind. Be short and factual."},
        {"role": "user", "content": "Say one sentence: you are the text brain and you do not invent stock prices."},
    ])
    print(text)