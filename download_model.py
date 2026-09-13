"""
Reads requirements.models.txt and downloads each GGUF with huggingface_hub.
Skip a file if it is already on disk.
"""
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent
LIST_FILE = ROOT / "requirements.models.txt"


def parse_list():
    rows = []
    for raw in LIST_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            raise ValueError(f"Bad line (need 4 columns): {raw}")
        job, folder, repo, filename = parts
        rows.append((job, folder, repo, filename))
    return rows


def main():
    if not LIST_FILE.exists():
        raise SystemExit(f"Missing {LIST_FILE}")

    for job, folder, repo, filename in parse_list():
        dest_dir = ROOT / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        if dest.exists():
            print(f"SKIP already have [{job}] {dest}")
            continue
        print(f"GET  [{job}] {filename} -> {dest_dir}")
        hf_hub_download(
            repo_id=repo,
            filename=filename,
            local_dir=str(dest_dir),
        )
        print(f"OK   {dest}")


if __name__ == "__main__":
    main()