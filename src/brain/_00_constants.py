"""
Shared knobs for the brain. Paths to GGUFs live here so workers
do not hardcode repo names in five files.
"""
from pathlib import Path

def project_root() -> Path:
    here = Path(__file__).resolve()
    for folder in here.parents:
        if (folder / "requirements.models.txt").exists():
            return folder
    raise RuntimeError("Could not find project root (no requirements.models.txt)")


ROOT = project_root()

# Must match the brain line in requirements.models.txt
QWEN_GGUF = ROOT / "text_models" / "Qwen3.5-9B-Q4_K_M.gguf"

# How much of the filing we stuff into the prompt (tokens, not pages)
QWEN_CONTEXT_TOKENS = 4096
QWEN_MAX_ANSWER_TOKENS = 512