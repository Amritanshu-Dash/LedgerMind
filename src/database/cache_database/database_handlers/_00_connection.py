"""
_00_connection.py
------------------
Database connection handling for the cache DB.

Location: src/database/cache_database/database_handlers/_00_connection.py

Required .env variables:
    CACHE_DB_HOST=localhost
    CACHE_DB_PORT=5432
    CACHE_DB_NAME=cache_db
    CACHE_DB_USER=ledgermind_admin
    CACHE_DB_PASSWORD=<password>
    CACHE_DB_ADMIN_PASSWORD=<admin password for protected operations>

Design goals, in priority order:
1. Every piece of configuration is checked BEFORE we ever attempt to connect — a typo in .env should produce one clear error message, not a confusing crash somewhere unrelated.
2. Every realistic connection failure — can't connect at all, OR connection drops partway through being used — is caught and turned into our own clear exception type, never a raw psycopg error leaking out to code that doesn't know what psycopg is.
3. autocommit=True, not manual commit()/rollback() — see the long explanation on get_connection() below for exactly why, and the rule every future function using this module must follow.
"""

from __future__ import annotations  # lets type hints like tuple[int, int] work on older Python versions too

import logging      # Python's standard logging system — used instead of print() so messages carry a timestamp, a severity level (INFO/DEBUG/ERROR), and which file they came from
import os            # used to read values out of environment variables (os.environ.get(...))

from contextlib import contextmanager  # the decorator that turns the get_connection() generator function below into something usable in a `with` block — see the long explanation right on get_connection() itself for exactly how
from pathlib import Path  # object-oriented file path handling — used in _load_env() to search folders

from typing import Iterator  # a type hint meaning "this function yields values one at a time"
import psycopg  # the actual Postgres driver — the library that does the real work of talking to the database

from psycopg.rows import dict_row  # explain below paragraph.
"""
a "row factory" — controls what shape query results come back in. Without this, a row is a plain tuple (row[0], row[1], ...) and you have to remember column order by position. dict_row makes every row come back as a dict instead (row["company_name"]) — safer, since it 
can't silently break if a column ever gets added or reordered.
"""

from dotenv import load_dotenv  # reads a .env file's contents into the environment, so os.environ.get() can see values that were only ever written to that file, not exported as real shell environment variables

logger = logging.getLogger(__name__)  # creates a logger tagged with this file's own module name


class CacheDatabaseConnectionError(Exception):
    """
    Raised when a connection to the cache database cannot be used at all — either it never connected in the first place (wrong credentials, Postgres not running, network unreachable, timeout), OR it was working fine and then dropped partway through being used
    (network blip, Postgres restarted, etc). Either way, this means we can't be sure any pending work reached the database.

    Deliberately distinct from the business-rule errors raised in _01_cache_repository.py (MissingReviewerError, InvalidStatusError, etc.) — those mean "we reached the database and it said no for a specific reason." This one means "we couldn't reach it, or lost it,
    full stop." Reusable by any future module (e.g. main_database) that needs the same clear distinction.

    Also we are writing just pass here because this class has no extra behavior of its own — it exists purely as a distinct, nameable TYPE of exception, so code elsewhere can write `except CacheDatabaseConnectionError:` specifically.
    """
    pass  



class CacheDatabaseConfigError(Exception):
    """
    Raised when the .env configuration itself is missing or invalid — an empty host/name/user, a missing password, an out-of-range port, a non-numeric timeout. Distinct from CacheDatabaseConnectionError: this means we never even TRIED to connect, because the configuration
    needed to do so isn't valid in the first place.
    """
    pass  # same idea as above — an empty class body, used only for its distinct name/type


# -------------------------------------------------
# Load .env
# -------------------------------------------------
def _load_env() -> None:
    """
    python-dotenv's default load_dotenv() already walks upward from the current working directory looking for .env, which works fine as long as this project is always run via `python -m ...` from the project root (its established convention). This explicit fallback exists
    only for the case where it's run some other way.

    Deliberately NOT using a hardcoded parent-folder count (e.g. Path(__file__).parents[4]) to guess the project root — this file's location has already moved more than once during this project's development, and a hardcoded index silently breaks (falls through to
    a different candidate, or fails to find .env at all) the next time it moves, with no error to flag it. Walking up looking for a real marker of the project root is more robust than guessing a number.
    """
    # First, the cheap/common case: if a .env file sits directly in wherever this program was launched FROM (the current working directory), just use python-dotenv's own default search and stop.
    if Path.cwd().joinpath(".env").is_file():
        load_dotenv()  # no arguments = "search from cwd upward automatically", which will find it
        return          # done — no need to run the fallback search below at all

    # Fallback: this file's own location, walking UPWARD through every parent folder (its folder, that folder's parent, and so on, all the way up to the filesystem root), looking for a folder that looks like the real project root.
    for parent in Path(__file__).resolve().parents:
        # ".git" (every git repo has this) or "requirements.txt" (this project's dependency list) are both reliable signs "this folder is the project root" — neither depends on how deep this particular file happens to be nested right now.
        if (parent / ".git").exists() or (parent / "requirements.txt").exists():
            env_path = parent / ".env"  # build the full path to where .env WOULD be, in that root folder
            if env_path.is_file():
                load_dotenv(dotenv_path=env_path)  # explicitly tell it exactly which file to load
                logger.debug("Loaded .env from %s", env_path)
            return  # stop searching either way — we found the project root, whether or not .env was in it

    # Last resort: we walked all the way up and found neither marker. Fall back to python-dotenv's own default behavior one more time, just in case it succeeds by some path we didn't anticipate.
    load_dotenv()


_load_env()  # actually run the search above, once, the moment this module is first imported


# -------------------------------------------------
# Configuration — read as plain strings here, deliberately NOT converted or validated yet. Converting/validating eagerly at import time (e.g. int(DB_PORT) right here) means a typo in .env crashes the whole module the instant anything imports it, with a raw traceback instead of a
# clear message. All real validation happens in _validate_config(), called only when someone actually tries to connect.
# -------------------------------------------------
DB_HOST = os.environ.get("CACHE_DB_HOST", "localhost")           # falls back to "localhost" if unset
DB_PORT = os.environ.get("CACHE_DB_PORT", "5432")                 # stays a STRING here on purpose, see above
DB_NAME = os.environ.get("CACHE_DB_NAME", "cache_db")
DB_USER = os.environ.get("CACHE_DB_USER", "ledgermind_admin")
DB_PASSWORD = os.environ.get("CACHE_DB_PASSWORD")                 # no default — this one is REQUIRED, checked below
DB_ADMIN_PASSWORD = os.environ.get("CACHE_DB_ADMIN_PASSWORD")     # also required, but only when an admin action is actually attempted — see get_admin_password() further down
DB_CONNECT_TIMEOUT_RAW = os.environ.get("CACHE_DB_CONNECT_TIMEOUT", "10")  # "_RAW" suffix reminds us this is still an unvalidated string


def _validate_config() -> tuple[int, int]:
    """
    Validates every piece of connection configuration before we ever attempt to connect. Returns (validated_port, validated_connect_timeout) as real ints — the only place either value is ever converted from its raw string form, so the rest of this module just reuses what's
    returned here instead of re-parsing DB_PORT a second time.

    Checking EVERYTHING here, in one place, before connecting, means a misconfigured .env always fails the same clear way — never as a confusing error from deep inside psycopg or Postgres itself.
    """
    # .get(key, "default") only falls back when the key is MISSING — a key that's PRESENT but blank (e.g. "CACHE_DB_HOST=" in .env) comes back as "", which is a real, easy-to-make mistake worth catching explicitly rather than silently trying to connect to an empty hostname.
    for name, value in [("CACHE_DB_HOST", DB_HOST), ("CACHE_DB_NAME", DB_NAME), ("CACHE_DB_USER", DB_USER)]:
        # "not value" catches None; "not value.strip()" catches a string that's only whitespace (e.g. a single space) — both count as "effectively empty" for our purposes.
        if not value or not value.strip():
            raise CacheDatabaseConfigError(f"{name} is empty. Check your .env file in the project root.")

    if not DB_PASSWORD:
        raise CacheDatabaseConfigError("CACHE_DB_PASSWORD is not set. Check your .env file in the project root.")

    # Try to turn the port string into a real integer. int() raises ValueError on something like "abc", or TypeError if given None — we catch both and re-raise as OUR OWN exception type with a clearer message, so the caller never has to know int() was even involved.

    try:
        port = int(DB_PORT)
    except (TypeError, ValueError) as exc:
        # "from exc" chains the original error underneath ours, so it's still visible in a full traceback for debugging, even though the exception TYPE seen by calling code is now ours.
        raise CacheDatabaseConfigError(f"CACHE_DB_PORT must be a valid integer. Got: {DB_PORT!r}") from exc
    if not (1 <= port <= 65535):  # the entire valid range for a TCP port number
        raise CacheDatabaseConfigError(f"CACHE_DB_PORT must be between 1 and 65535. Got: {port}")

    # Same pattern again for the timeout value — parse, catch, re-raise clearly.
    try:
        timeout = int(DB_CONNECT_TIMEOUT_RAW)
    except (TypeError, ValueError) as exc:
        raise CacheDatabaseConfigError(
            f"CACHE_DB_CONNECT_TIMEOUT must be a valid integer. Got: {DB_CONNECT_TIMEOUT_RAW!r}"
        ) from exc
    if timeout <= 0:  # zero or negative seconds makes no sense as a timeout
        raise CacheDatabaseConfigError(f"CACHE_DB_CONNECT_TIMEOUT must be a positive number of seconds. Got: {timeout}")

    return port, timeout  # hand both validated, converted values back to whoever called this


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """
    Opens a new connection for the duration of a `with` block, and always closes it afterward — even if an exception happens inside the block.

    What @contextmanager + yield actually does, for reference: this function isn't called normally — code writes `with get_connection() as conn:`. Everything before the `yield` line runs first (opening the connection); the `conn` value is handed to whatever's inside the
    `with` block; and everything after the `yield` (here, closing the connection) is GUARANTEED to run once that block finishes — whether it finished normally or by raising an exception. That guarantee is exactly why the connection can never be left open by accident.

    autocommit=True — every successful statement commits immediately.

    >>> RULE FOR ANY NEW CODE WRITTEN AGAINST THIS CONNECTION <<<
    
    If a function does 2+ writes that must ALL succeed or ALL fail together, it MUST wrap them in `with conn.transaction():` explicitly. Autocommit does NOT do this for you — each statement is independently durable by default. Forgetting this on a function that needs
    atomicity WILL produce partial updates on a mid-operation failure. (promote_approved_documents() in _01_cache_repository.py is the one exception: its multiple writes are DELIBERATELY independent, not wrapped, by design — not an oversight.)

    Every realistic connection failure is caught here and turned into CacheDatabaseConnectionError — both "never connected at all" (wrong credentials, Postgres not running, timeout) and "was connected, then dropped partway through" (network blip, Postgres restarted mid-use).
    Caught as psycopg.Error broadly (not just OperationalError) — that's the base of psycopg's whole exception tree, so this also covers rarer connection-establishment failures (e.g. InterfaceError) that OperationalError alone wouldn't catch. This doesn't interfere with
    the specific error handling in _01_cache_repository.py (e.g. CheckViolation for a missing reviewer) — those are caught and converted to our own exception types INSIDE that file first, before anything reaches this broader catch here.

    >>> WHY THIS FUNCTION HAS TWO SEPARATE try BLOCKS, NOT ONE <<<

    (This is the exact thing that caused confusion before — worth spelling out precisely.) Below, there's a first `try: conn = psycopg.connect(...) except ...` block, and then, as a COMPLETELY SEPARATE statement further down, a second `try: yield conn ...
    finally: conn.close()` block. They are NOT one try wrapping everything with a shared finally.

    This matters because of what happens if psycopg.connect() itself fails: its `except` clause does `raise ... from e`, which exits this whole function immediately, right there. Execution never reaches the line after it — meaning it NEVER reaches the second try/finally
    block at all. So if connecting fails, `conn.close()` in that later `finally` is never even attempted — not "attempted and it breaks," genuinely never run. The `finally` only ever executes on paths where the FIRST try block already succeeded and `conn` was assigned a real
    value. This was verified directly by testing the exact control-flow shape rather than just reasoning about it — worth doing that yourself too, next time this feels uncertain: write a tiny standalone script mirroring the structure and run it.
    """
    port, timeout = _validate_config()  # fail immediately and clearly if .env is misconfigured, before ever attempting a real network connection

    # ---- try block #1: only wraps the actual connection attempt ----
    try:
        conn = psycopg.connect(
            host=DB_HOST,
            port=port,                  # the validated int from _validate_config(), not re-parsed here
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            row_factory=dict_row,       # every row comes back as a dict — see the import comment above
            autocommit=True,            # every statement commits the instant it succeeds — see the long docstring note above for exactly why this matters
            connect_timeout=timeout,    # give up and raise instead of hanging forever if unreachable
        )
    except psycopg.Error as e:
        # If we get here, `conn` was NEVER successfully assigned — the
        # connect() call itself threw before returning anything.
        raise CacheDatabaseConnectionError(f"Could not connect to the cache database: {e}") from e
        # ^ this `raise` exits get_connection() ENTIRELY right here.
        #   The code below (the second try block) is not reached in this path.
    # ---- end of try block #1 ----

    # If we've reached this point, try block #1 completed successfully
    # and `conn` is guaranteed to hold a real, live connection object.

    # ---- try block #2: a SEPARATE statement, covers using + closing the connection ----
    try:
        yield conn  # hands the live connection to the `with` block using this function; execution PAUSES here until that `with` block finishes
    except psycopg.Error as e:
        # The connection was working fine (we got past try block #1), then something went wrong WHILE it was being used — a different moment in time than the connect() failure above, but given the same clear exception type, so callers don't need to tell the two apart.
        raise CacheDatabaseConnectionError(f"Lost connection to the cache database: {e}") from e
    finally:
        # This ALWAYS runs once the `with` block using this connection finishes — whether it finished normally, or by raising any exception (including the one just above). This is what guarantees the connection is never left open by accident.
        try:
            conn.close()  # safe to reach here: `conn` was already confirmed to exist, back in try block #1
        except Exception as close_error:
            # The connection may already be broken (that's often WHY we're here) — a failure while closing an already-dead connection is not worth hiding the real error behind, just log it and move on rather than letting a secondary error during cleanup mask the original problem.
            logger.debug(f"Error while closing connection (likely already broken): {close_error}")
    # ---- end of try block #2 ----


def get_admin_password() -> str:
    """
    Returns the admin password used for protected operations (status changes, deletes, promotion to main DB). Single source of truth — _01_cache_repository.py calls this instead of reading the environment variable itself.
    """
    if not DB_ADMIN_PASSWORD:  # only checked here, lazily, when an admin action is actually attempted — NOT at import time, since most usage of this module is read-only and doesn't need the admin password configured at all
        raise CacheDatabaseConfigError(
            "CACHE_DB_ADMIN_PASSWORD is not set. This password is required for protected operations."
        )
    return DB_ADMIN_PASSWORD


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    print("=" * 60)
    print("Testing cache DB connection...")
    print("=" * 60)
    try:
        with get_connection() as conn:              # opens a connection, runs the block below, always closes it
            with conn.cursor() as cur:               # a "cursor" is what actually executes SQL and reads results
                cur.execute("SELECT version() AS version;")  # ask Postgres for its own version string
                row = cur.fetchone()                 # pull back the one row this query returns, as a dict
                print(f"✅ Connected. Postgres version: {row['version']}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")