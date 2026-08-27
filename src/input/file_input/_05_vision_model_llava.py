"""
vision_model.py
---------------
Vision Model Implementation using LLaVA 1.6 (Mistral 7B - 4-bit)

Purpose:
This module looks at images pulled out of financial documents (PDFs, DOCX, screenshots, charts, tables, receipts, etc.) and turns them into clean, accurate text. It is the ONLY part of the pipeline that decides whether an image is worth reading at all — everything else 
downstream (validator, main-DB, model prediction) assumes what this file hands over is either "clean financial text" or "explicitly rejected, with a reason."

Design goals (in priority order):

1.  NEVER take the whole application down with it. Not on a bad image, not on a corrupted file, not even if the underlying C++ model backend segfaults.
    This is why model inference runs in a separate worker PROCESS, not just a try/except in this process — a segfault in llama.cpp cannot be caught by Python's exception handling because it kills the process it happens in.
    By putting the model in its own process, a crash there just means we restart that process; the app calling this module never goes down.

2.  Reject anything that isn't a financial document BEFORE it reaches the model, and reject anything that IS finance-adjacent nonsense (cats, dogs, cars, random screenshots) with a clear, user-facing reason. We would rather say "skipped: this looks like a photo of a dog" 
    than silently process it or silently ignore it.

3.  Extract text/numbers/tables faithfully. Prefer "not visible" over a guess. A guess that looks confident is worse than an honest gap, because this text eventually feeds a company's financial prediction.

Why LLaVA 1.6 + llama-cpp-python?
- Runs fully offline on Apple Silicon (M1/M2/M3) using Metal.
- 4-bit quantized version is fast enough and memory efficient.
- Good balance between quality and speed for document understanding.
"""

import base64            # encodes image bytes into a data URI the model can read directly
import logging            # structured logging instead of scattered print()s
import multiprocessing as mp  # runs the model in its own process, so a crash there can't kill the app
import os                 # used for the forced exit in the quick test at the bottom
import queue               # gives us queue.Empty to detect a worker timeout
import time                 # only used to time the quick test run
import traceback           # captures full tracebacks from inside the worker process to report back
from dataclasses import dataclass, field  # lightweight structured result objects, no boilerplate
from pathlib import Path    # safer, OS-independent path handling than raw strings
from typing import List, Optional  # type hints so function signatures are self-documenting

from PIL import Image, UnidentifiedImageError  # cheap image validation before it ever reaches the model

logger = logging.getLogger(__name__)  # module-level logger, tagged with this file's name


# ============================================================
# CONFIGURATION
# ============================================================
# All the "how strict / how lenient / how much" knobs live here so you don't
# have to go hunting through the logic below to tune behaviour later.

# File-level gatekeeping (runs BEFORE any image ever touches the model).
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}  # only these file types are ever opened
MAX_FILE_SIZE_MB = 15          # reject anything bigger, no exceptions
MAX_IMAGE_DIMENSION_PX = 6000  # guards against decompression-bomb style images
MAX_IMAGES_PER_CALL = 20       # hard cap so one request can't hang forever

# Model behaviour.
MODEL_INFERENCE_TIMEOUT_SECONDS = 120   # if a single image takes longer, give up on it
WORKER_STARTUP_TIMEOUT_SECONDS = 120   # first request pays the "load the model" cost
MAX_WORKER_RESTARTS_PER_CALL = 2       # if the worker keeps dying, stop trying and fail loud


def _find_project_root() -> Path:
    """
    Walk upward from this file until we find a folder that contains 'vision_models'. This is intentionally NOT run at import time (see bottom of file) — if the vision_models folder is missing on some machine, importing this
    module should not itself crash the whole application; only actually trying to run the vision model should surface that error.
    """
    current = Path(__file__).resolve()          # absolute path to this file itself
    for parent in current.parents:               # walk upward: this file's folder, then its parent, etc
        if (parent / "vision_models").exists():         # found the folder that holds the model weights
            return parent
    raise RuntimeError("Could not find project root containing 'vision_models' folder")


# ============================================================
# RESULT TYPES
# ============================================================
# Structured results so the caller (and eventually the user-facing UI) can distinguish "here is clean financial text" from "we skipped this one, and here's why" without having to parse strings.

@dataclass
class ImageResult:
    """
    One image's outcome — whether it was accepted or rejected, and why.
    """
    image_path: str           # which file this result belongs to
    accepted: bool             # True if it was financial and got processed, False if skipped
    reason: str                 # human-readable explanation of the outcome, shown to the user
    extracted_text: str = ""    # the model's output text; only filled in when accepted is True


@dataclass
class VisionAnalysisResult:
    """
    The full outcome of one analyze_images() call across every image passed in.
    """
    accepted: List[ImageResult] = field(default_factory=list)  # every image that was financial content
    rejected: List[ImageResult] = field(default_factory=list)  # every image skipped, with a reason each

    def combined_text(self) -> str:
        """
        Convenience: just the extracted text from accepted images, for callers (like the Analyser stage) that only care about the content and not the per-image bookkeeping.
        """
        return "\n\n".join(r.extracted_text for r in self.accepted if r.extracted_text)


# ============================================================
# STAGE 1 — PRE-MODEL VALIDATION
# ============================================================
# This is the cheap, fast, non-negotiable gate. Nothing reaches the model unless it passes here. Note: your architecture already has a separate malicious-file scanner earlier in the pipeline, so this function is NOT trying to catch malware — its job is narrower: "is this a real, readable,
# reasonably-sized image file, or will it break / hang the model?"

def _validate_image(path: Path) -> Optional[str]:
    """
    Returns None if the image is safe to hand to the model.
    Returns a human-readable rejection reason (string) otherwise.
    """
    if not path.exists() or not path.is_file():
        return "File does not exist or is not a regular file."

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:  # block anything that isn't a known image type
        return f"Unsupported file type '{path.suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}."

    size_mb = path.stat().st_size / (1024 * 1024)  # convert bytes to megabytes for the size check
    if size_mb > MAX_FILE_SIZE_MB:
        return f"File too large ({size_mb:.1f}MB, limit is {MAX_FILE_SIZE_MB}MB)."

    try:
        # img.verify() checks the file's internal structure is not corrupt WITHOUT fully decoding pixel data — cheap and catches most malformed/truncated/weird files before we spend real work on them.
        with Image.open(path) as img:
            img.verify()
        # verify() leaves the file object unusable, so we must reopen to
        # check dimensions.
        with Image.open(path) as img:
            width, height = img.size                          # actual pixel dimensions of the image
            if max(width, height) > MAX_IMAGE_DIMENSION_PX:    # reject unreasonably huge images
                return f"Image dimensions too large ({width}x{height})."
    except UnidentifiedImageError:
        return "File is not a valid, readable image (bad or corrupt signature)."
    except Exception as e:
        # Any other Pillow-level failure — treat as "unsafe to process"
        # rather than letting it propagate into the model.
        return f"Could not read image safely: {e}"

    return None  # passed all checks


def _image_to_data_uri(path: Path) -> str:
    """
    Encode the image as a base64 data URI. We deliberately do NOT pass a file:// path to the model — depending on the llama-cpp-python version, the LLaVA chat handler's image loader may silently fail to fetch file:// URIs, which produces the "model answers as if no image was
    given" symptom (near-empty or generic output with very low prompt token counts). A data URI guarantees the exact bytes we validated above are what the model actually sees.
    """
    ext = path.suffix.lower().lstrip(".")            # file extension without the leading dot
    mime = "jpeg" if ext == "jpg" else ext              # "jpg" isn't a valid MIME subtype, "jpeg" is
    with open(path, "rb") as f:                          # read raw bytes, not text
        encoded = base64.b64encode(f.read()).decode("utf-8")  # bytes -> base64 -> plain string
    return f"data:image/{mime};base64,{encoded}"


# ============================================================
# STAGE 2 — THE PROMPT
# ============================================================
# Rebalanced from the previous version. The old prompt stacked FOUR separate "do not invent / do not guess / be honest / accuracy over completeness" instructions on top of each other. On a small quantized model that pressure tends to produce near-empty output, because the
# safest possible completion under that much warning is to say very little. The fix here is to give the model one specific safe fallback per field ("write 'not visible' if unsure") instead of a vague, repeated threat about honesty in general — that gives it permission to still
# produce a full, structured answer while keeping the same anti-hallucination guarantee.

VISION_SYSTEM_PROMPT = (  # sets the model's overall behaviour for every request, before the user prompt
    "You are a careful financial-document reading assistant. You transcribe "
    "exactly what is visible in an image. When any detail is unclear or "
    "not shown, you write 'not visible' for that detail instead of "
    "guessing."
)

VISION_USER_PROMPT = """Look at this image and do two things, in order.

STEP 1 — Classify it.
Is this image a financial document or financial content? This includes
receipts, invoices, bank statements, charts, tables, stock reports,
payment screenshots, or business documents. It does NOT include unrelated
photos (people, animals, landscapes, general objects, memes, etc).

If it is NOT financial: reply with exactly one line in this format and
stop there — do not add anything else:
REJECT: <one short sentence saying what the image actually shows>

STEP 2 — If it IS financial, extract its content.
Write out everything visible, organized like this:
- Any table -> reproduce it as a clean markdown table.
- Any chart/graph -> describe the trend and the key values shown on it.
- Any other text, numbers, dates, or labels -> list them plainly.
For any specific field you would expect on this kind of document (like a
reference number, company name, or total) that is genuinely not shown in
the image, write "not visible" for that field instead of leaving it out
or guessing a plausible-looking value. Do not add any field, number, or
name that is not visible in the image."""  # this exact string is sent to the model on every call


# ============================================================
# STAGE 3 — MODEL WORKER PROCESS (crash isolation)
# ============================================================
# This is the core of "should not crash the whole application." A segfault inside llama.cpp / the CLIP image encoder cannot be caught by a Python try/except — it kills the OS process it happens in, full stop. So instead of running inference in the same process as the rest of the app, 
# we run it in a dedicated child process. If that child process dies (crash, segfault, OOM-kill, anything), the parent process — which is what your application actually runs in — is completely unaffected. The parent just notices the worker is gone and restarts it.
#
# Communication with the worker happens over two multiprocessing Queues: one for requests going in, one for responses coming back. Every response is tagged with a request id so we always know which request a reply belongs to, even across a restart.

def _model_worker_main(request_q: "mp.Queue", response_q: "mp.Queue") -> None:
    """
    Entry point that runs INSIDE the child process. Loads the model once, then sits in a loop handling one image at a time. This function must never be called directly from the main process — only via multiprocessing.Process(target=_model_worker_main, ...).
    """
    # Imports are done here, inside the child process, so that a failure to import llama_cpp (e.g. missing native library) only breaks the worker process, not the parent.
    from llama_cpp import Llama                                   # the low-level model runner
    from llama_cpp.llama_chat_format import Llava15ChatHandler    # adds image-input support to Llama

    llm = None  # holds the loaded model once ready; stays None if load fails
    try:
        project_root = _find_project_root()                                      # locate vision_models/ folder
        model_path = project_root / "vision_models" / "llava-v1.6-mistral-7b.Q4_K_M.gguf"  # the main LLM weights
        mmproj_path = project_root / "vision_models" / "mmproj-model-f16.gguf"             # the vision projector weights

        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        if not mmproj_path.exists():
            raise FileNotFoundError(f"Multimodal projector not found: {mmproj_path}")

        chat_handler = Llava15ChatHandler(clip_model_path=str(mmproj_path), verbose=False)  # image encoder
        llm = Llama(
            model_path=str(model_path),
            chat_handler=chat_handler,
            n_ctx=6144,        # max tokens of context (prompt + image + output) the model can hold
            n_gpu_layers=-1,   # full Metal acceleration on Apple Silicon
            n_batch=512,       # tokens processed per batch during inference
            verbose=False,     # suppress llama.cpp's own console spam
            logits_all=False,  # we only need the final output, not per-token logits
        )
        # Signal to the parent that startup succeeded and we're ready for work.
        response_q.put(("__READY__", None, None))
    except Exception as e:
        # If the model can't even load, tell the parent exactly why instead of just silently hanging — the parent is waiting on __READY__.
        response_q.put(("__STARTUP_FAILED__", None, f"{e}\n{traceback.format_exc()}"))
        return

    # Main work loop. Each request is (request_id, image_data_uri).
    # A None request_id is the shutdown signal.
    while True:
        try:
            request_id, data_uri = request_q.get()   # blocks here until the parent sends work
        except (EOFError, OSError):
            break  # parent process went away

        if request_id is None:
            break  # explicit shutdown

        try:
            result = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},  # model's standing instructions
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},  # the actual image
                            {"type": "text", "text": VISION_USER_PROMPT},            # what to do with it
                        ],
                    },
                ],
                max_tokens=1024,   # hard ceiling on how long the model's answer can be
                temperature=0.15,  # small nonzero temp; temp=0.0 combined with a
                                   # heavily-constrained prompt can push a small
                                   # quantized model toward degenerate/empty output
                top_p=0.9,         # nucleus sampling cutoff, paired with the small temperature above
            )
            content = result["choices"][0]["message"]["content"].strip()  # pull the text out of the response
            response_q.put((request_id, content, None))  # (id, result, no error) back to the parent
        except Exception as e:
            # A normal Python-level failure during inference (bad response shape, OOM raised as an exception rather than a hard crash, etc). Report it back rather than letting the worker die.
            response_q.put((request_id, None, f"{e}\n{traceback.format_exc()}"))


class _ModelWorkerManager:
    """
    Owns the lifecycle of the model worker process: starting it, sending it work, reading results back with a timeout, and restarting it if it dies (whether from a clean shutdown, an exception, or a native crash).
    This class is intentionally the ONLY thing in this file that touches multiprocessing directly — everything else just calls .run_inference().
    """

    def __init__(self) -> None:
        self._process: Optional[mp.Process] = None       # handle to the running worker OS process
        self._request_q: Optional[mp.Queue] = None         # parent -> worker: images to process
        self._response_q: Optional[mp.Queue] = None         # worker -> parent: results / errors
        self._next_request_id = 0                             # increasing id so replies can be matched up

    def _start_worker(self) -> None:
        """Spawn a fresh worker process and wait for it to report ready."""
        self._request_q = mp.Queue()    # fresh queues each time — old ones may hold stale/broken state
        self._response_q = mp.Queue()
        self._process = mp.Process(
            target=_model_worker_main,
            args=(self._request_q, self._response_q),
            daemon=True,  # dies automatically if the parent process exits
        )
        self._process.start()  # actually forks/spawns the OS process here

        try:
            tag, _content, error = self._response_q.get(timeout=WORKER_STARTUP_TIMEOUT_SECONDS)  # wait for ready signal
        except queue.Empty:
            self._kill_worker()
            raise RuntimeError(
                f"Vision model worker did not start within {WORKER_STARTUP_TIMEOUT_SECONDS}s."
            )

        if tag == "__STARTUP_FAILED__":
            self._kill_worker()
            raise RuntimeError(f"Vision model failed to load: {error}")
        # tag == "__READY__" means we're good to go.

    def _kill_worker(self) -> None:
        """
        Forcefully terminate whatever's left of a dead/misbehaving worker.
        """
        if self._process is not None and self._process.is_alive():
            self._process.terminate()      # ask the OS to stop the process
            self._process.join(timeout=5)  # wait briefly for it to actually exit
        self._process = None    # drop all references so _ensure_worker_alive knows to restart
        self._request_q = None
        self._response_q = None

    def _ensure_worker_alive(self) -> None:
        if self._process is None or not self._process.is_alive():  # no worker, or it died
            logger.info("Vision model worker not running — starting it.")
            self._start_worker()

    def run_inference(self, data_uri: str) -> str:
        """
        Runs one image through the model. Raises RuntimeError with a clear message on any failure (timeout, crash, load failure) rather than ever letting an exception from the worker process propagate in a confusing way. Restarts the worker automatically if it died.
        """
        last_error: Optional[str] = None  # keeps the most recent failure reason across retries

        for attempt in range(MAX_WORKER_RESTARTS_PER_CALL + 1):  # try once, then retry up to the limit
            try:
                self._ensure_worker_alive()
            except Exception as e:
                last_error = str(e)
                continue  # try again, up to the restart limit

            request_id = self._next_request_id    # unique id for this specific request
            self._next_request_id += 1
            self._request_q.put((request_id, data_uri))  # hand the image off to the worker

            try:
                got_id, content, error = self._response_q.get(
                    timeout=MODEL_INFERENCE_TIMEOUT_SECONDS
                )
            except queue.Empty:
                # The worker hung, or crashed hard enough that it never even put a response on the queue. Kill it and retry fresh.
                logger.warning("Vision model worker timed out — restarting it.")
                self._kill_worker()
                last_error = f"Model inference timed out after {MODEL_INFERENCE_TIMEOUT_SECONDS}s."
                continue

            if got_id != request_id:
                # Stale response from a previous attempt; ignore and retry.
                last_error = "Received mismatched response from vision worker."
                continue

            if error is not None:
                last_error = error
                # An in-process exception (not a crash) — worker is still
                # usable, so just report the error, no need to restart it.
                raise RuntimeError(f"Vision model inference failed: {error}")

            return content  # success — hand the extracted text back to the caller

        raise RuntimeError(
            f"Vision model worker failed after {MAX_WORKER_RESTARTS_PER_CALL + 1} attempts: {last_error}"
        )

    def shutdown(self) -> None:
        """
        Clean shutdown, e.g. on application exit.
        """
        if self._process is not None and self._process.is_alive():
            try:
                self._request_q.put((None, None))  # tells the worker loop to exit cleanly
                self._process.join(timeout=5)
            except Exception:
                pass
        self._kill_worker()


# Single, module-level manager — the worker process (and the model inside
# it) is created lazily on first use and reused across calls.
_worker_manager = _ModelWorkerManager()


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def analyze_images(image_paths: List[str]) -> VisionAnalysisResult:
    """
    Main function. Takes a list of image file paths and returns a
    VisionAnalysisResult that clearly separates:
      - .accepted  -> images that were financial content, with extracted text
      - .rejected  -> images that were skipped, with a human-readable reason

    This function is designed to never raise for "expected" bad input (bad files, non-financial images, one image failing among many). It can still raise RuntimeError if the model itself is fundamentally unusable (e.g. model files missing) — that is treated as a setup problem worth
    surfacing loudly rather than silently swallowing, since it means EVERY image in the batch would fail the same way.
    """
    result = VisionAnalysisResult()  # empty accepted/rejected lists to fill in below

    if not image_paths:
        return result  # nothing to do

    if len(image_paths) > MAX_IMAGES_PER_CALL:  # protect against an unbounded batch size
        logger.warning(
            "Received %d images, capping to %d to avoid an unbounded run.",
            len(image_paths), MAX_IMAGES_PER_CALL,
        )
        image_paths = image_paths[:MAX_IMAGES_PER_CALL]

    for raw_path in image_paths:  # process one image at a time so one failure can't take down the batch
        path = Path(raw_path)  # normalize the string path into a Path object

        # --- Stage 1: cheap pre-model validation ---
        rejection_reason = _validate_image(path)
        if rejection_reason is not None:  # failed validation, never reaches the model
            result.rejected.append(
                ImageResult(image_path=str(path), accepted=False, reason=rejection_reason)
            )
            continue

        # --- Stage 2/3: model classification + extraction ---
        try:
            data_uri = _image_to_data_uri(path)               # encode bytes for the model
            raw_output = _worker_manager.run_inference(data_uri)  # send to the worker process, wait for result
        except Exception as e:
            # Model-level failure for THIS image only — log it, record it as a rejection with the error as the reason, and keep going with the rest of the batch. One bad image must never stop the others from being processed.
            logger.error("Vision model failed on %s: %s", path.name, e)
            result.rejected.append(
                ImageResult(
                    image_path=str(path),
                    accepted=False,
                    reason=f"Vision model error: {e}",
                )
            )
            continue

        # The model itself rejects non-financial images per the prompt's
        # STEP 1 contract: a single line starting with "REJECT:".
        if raw_output.strip().upper().startswith("REJECT:"):
            explanation = raw_output.split(":", 1)[1].strip() if ":" in raw_output else raw_output  # text after "REJECT:"
            result.rejected.append(
                ImageResult(
                    image_path=str(path),
                    accepted=False,
                    reason=f"Not a financial document — {explanation}",
                )
            )
            continue

        result.accepted.append(  # image passed both validation and the model's financial-content check
            ImageResult(
                image_path=str(path),
                accepted=True,
                reason="Financial content detected and extracted.",
                extracted_text=raw_output,
            )
        )

    return result


def shutdown_vision_model() -> None:
    """
    Call this on application shutdown to cleanly stop the worker process.
    """
    _worker_manager.shutdown()


# ============================================================
# QUICK TEST
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Change this to a folder of test images, or a single path.
    test_images = [
        "/Users/amritanshudash/Desktop/LedgerMind/PHOTO-2026-02-15-13-14-11.jpg",
    ]

    print("\n" + "=" * 60)
    print("Testing Vision Model...")
    print("=" * 60)

    start = time.time()                       # mark start time to measure total run duration
    outcome = analyze_images(test_images)      # run the full pipeline on the test images

    print(f"\nAccepted ({len(outcome.accepted)}):")
    for r in outcome.accepted:
        print(f"  {r.image_path}\n{r.extracted_text}\n")

    print(f"Rejected ({len(outcome.rejected)}):")
    for r in outcome.rejected:
        print(f"  {r.image_path} -> {r.reason}")

    print(f"\nTotal time: {time.time() - start:.1f}s")

    shutdown_vision_model()  # stop the worker process cleanly before exiting
    os._exit(0)              # force exit to avoid Metal backend GGML_ASSERT crash on interpreter teardown