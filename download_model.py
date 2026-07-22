from huggingface_hub import hf_hub_download
from pathlib import Path

# Create models directory
models_dir = Path(__file__).resolve().parent / "models"
models_dir.mkdir(exist_ok=True)

repo_id = "cjpais/llava-1.6-mistral-7b-gguf"

files = [
    "llava-v1.6-mistral-7b.Q4_K_M.gguf",
    "mmproj-llava-v1.6-mistral-7b-f16.gguf"
]

for filename in files:
    print(f"Downloading {filename} ...")
    local_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=models_dir,
        local_dir_use_symlinks=False
    )
    print(f"Saved to {local_path}")

print("✅ All files downloaded.")