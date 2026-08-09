"""
Applying the community Tavern patch (themoddingtavern.dll -> Root.Township.dll)
-- shared by both apps since either one can be the first to patch a given
game install, and the other should correctly see it as already done.
"""
import os
import shutil

from tavern_shared.paths import _app_dir, _sha256_file
from tavern_shared.mod_install import _download_with_progress

PATCH_DOWNLOAD_URL = "https://github.com/ModdingTavern/TavernDefaults/releases/latest/download/themoddingtavern.dll"


PATCH_SOURCE_FILENAME = "themoddingtavern.dll"


PATCH_TARGET_SUBDIR   = os.path.join("A Township Tale_Data", "Managed")


PATCH_TARGET_FILENAME = "Root.Township.dll"


def _patch_source_path():
    """Full path to themoddingtavern.dll in the Patch/ folder next to the launcher."""
    return os.path.join(_app_dir(), "Patch", PATCH_SOURCE_FILENAME)


def _patch_target_path(game_exe):
    """Full path where Root.Township.dll lives in the game's Managed folder."""
    game_dir = os.path.dirname(game_exe)
    return os.path.join(game_dir, PATCH_TARGET_SUBDIR, PATCH_TARGET_FILENAME)


def _patch_is_applied(game_exe):
    """True if the installed Root.Township.dll's content exactly matches the
    local Patch/themoddingtavern.dll. This is a real on-disk comparison, not
    a remembered "I clicked this before" flag — so if the client launcher
    already patched a given game install, the server launcher (or vice
    versa) correctly sees it as already done too, as long as they're both
    pointed at the same game folder. No re-patching, no re-flashing."""
    src = _patch_source_path()
    dst = _patch_target_path(game_exe)
    try:
        if not (os.path.isfile(src) and os.path.isfile(dst)):
            return False
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        return _sha256_file(src) == _sha256_file(dst)
    except OSError:
        return False


def apply_patch(game_exe, on_progress=None):
    """Installs themoddingtavern.dll as Root.Township.dll. Tries GitHub
    first, falls back to the bundled Patch/ copy if unreachable. Skips
    the write if already up to date.

    Returns "downloaded", "bundled", or "current".
    Raises RuntimeError on failure (including a silent Controlled Folder
    Access block, caught by reading the file back and comparing)."""
    if on_progress is None:
        on_progress = lambda msg: None

    dst = _patch_target_path(game_exe)
    managed_dir = os.path.dirname(dst)
    if not os.path.isdir(managed_dir):
        raise RuntimeError(
            f"Game Managed folder not found:\n{managed_dir}\n\n"
            "Double-check the game exe path at the top of the launcher.")

    tmp_dest = dst + ".download"
    try:
        try:
            on_progress("Checking for the latest patch…")
            _download_with_progress(PATCH_DOWNLOAD_URL, tmp_dest, on_progress,
                                     connect_timeout=8, max_total_seconds=20)
            source = "downloaded"
        except Exception:
            local_src = _patch_source_path()
            if not os.path.isfile(local_src):
                raise RuntimeError(
                    "Couldn't reach GitHub to check for the latest patch, and no "
                    f"bundled copy was found in Patch/ either.\n\nExpected at:\n{local_src}")
            on_progress("Couldn't reach GitHub — using the version bundled with this launcher…")
            shutil.copy2(local_src, tmp_dest)
            source = "bundled"

        new_hash = _sha256_file(tmp_dest)
        if os.path.isfile(dst) and _sha256_file(dst) == new_hash:
            # Already exactly what we'd install — skip the write entirely
            # rather than rewriting (and re-triggering AV scanning of) a
            # file that's already correct.
            return "current"

        os.replace(tmp_dest, dst)  # atomic on Windows — always a full swap, never a partial one
        if not os.path.isfile(dst) or _sha256_file(dst) != new_hash:
            raise RuntimeError(
                "The file was written without any error, but checking it afterward "
                "shows it doesn't match what was just installed. This usually means "
                "something on this PC silently blocked the write — most commonly "
                "Windows' Controlled Folder Access, or antivirus real-time protection. "
                "Try adding an exclusion for the game's install folder in Windows "
                "Security (or your antivirus), or temporarily disabling Controlled "
                "Folder Access, then try again.")
        return source
    finally:
        try:
            if os.path.isfile(tmp_dest):
                os.remove(tmp_dest)
        except Exception:
            pass

