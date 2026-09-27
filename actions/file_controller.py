import os
import re
import shutil
import platform
from pathlib import Path
from datetime import datetime

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

from core.undo import push_undo
from typing import Dict, Any, Optional
from core.tool import AgentTool

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

# Undo keeps a file's previous contents in memory so `write` can be reversed.
# Above this size it does not — a 200 MB log would sit in RAM for the rest of
# the session to protect an edit nobody is going to take back.
_UNDO_CONTENT_LIMIT = 1_000_000


def _undo_move(src: Path, dst: Path):
    """Reverse of a move: put it back where it came from."""
    def _fn():
        if not dst.exists():
            return f"'{dst.name}' is no longer there — nothing moved back."
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        return f"'{src.name}' is back in {src.parent.name}/."
    return _fn


def _undo_create(target: Path):
    """Reverse of a create: remove what we made — and only if we still made it.

    Deliberately refuses to touch a directory that has since been filled: the
    undo for 'create a folder' is not 'delete whatever ended up in it'."""
    def _fn():
        if not target.exists():
            return f"'{target.name}' is already gone."
        if target.is_dir():
            if any(target.iterdir()):
                return (f"'{target.name}' is not empty any more — "
                        f"leaving it alone rather than deleting your files.")
            target.rmdir()
        else:
            target.unlink()
        return f"Removed '{target.name}'."
    return _fn


def _undo_write(target: Path, previous: str | None):
    """Reverse of a write: restore the old contents, or remove a file that did
    not exist before the write created it."""
    def _fn():
        if previous is None:
            if target.exists():
                target.unlink()
                return f"Removed '{target.name}' — it did not exist before."
            return f"'{target.name}' is already gone."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(previous, encoding="utf-8")
        return f"Restored the previous contents of '{target.name}'."
    return _fn


def _restore_from_trash(original: Path) -> str:
    """Best-effort undelete.

    delete_file uses send2trash, which is the right call: the file lands in the
    Recycle Bin / Trash where the person can also find it themselves. Getting it
    back out again is shell work and only reliable on Windows, where pywin32 is
    already a dependency. Everywhere else this says where the file is instead of
    pretending it failed — the file is not lost either way."""
    if _OS == "Windows":
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            bin_folder = shell.NameSpace(10)      # ssfBITBUCKET
            for item in bin_folder.Items():
                if str(bin_folder.GetDetailsOf(item, 1)).strip().lower() == \
                        str(original.parent).strip().lower():
                    if str(item.Name).strip().lower() == original.name.strip().lower():
                        item.InvokeVerb("UNDELETE")
                        return f"'{original.name}' restored from the Recycle Bin."
        except Exception as e:
            print(f"[file] Recycle Bin restore failed: {e}")
    return (f"'{original.name}' is in the Recycle Bin — I could not pull it back "
            f"automatically, but it is there and can be restored by hand.")


_SAFE_ROOTS: list[Path] = [
    Path.home(),
    Path.cwd(),
]

def _is_safe_path(target: Path) -> bool:
    """Is the given path inside _SAFE_ROOTS? If not, reject the operation."""
    try:
        resolved = target.resolve()
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _SAFE_ROOTS
        )
    except Exception:
        return False

def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Downloads"

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
    }
    raw   = raw.strip().strip('"').strip("'")
    lower = raw.lower()
    if lower in shortcuts:
        return shortcuts[lower]

    # "desktop/notes/a.md", "pictures/camera_capture_retake.png" — shortcut + sub-path
    normalized = raw.replace("\\", "/")
    head, sep, rest = normalized.partition("/")
    if sep and head.lower() in shortcuts:
        rest = rest.strip("/")
        return shortcuts[head.lower()] / rest if rest else shortcuts[head.lower()]

    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return expanded

    cwd_cand = Path.cwd() / raw
    if cwd_cand.exists():
        return cwd_cand

    cap_cand = Path.cwd() / "data" / "captures" / raw
    if cap_cand.exists():
        return cap_cand

    # Check relative to standard user folders if candidate exists
    for folder in shortcuts.values():
        cand = folder / raw
        if cand.exists():
            return cand

    return expanded

def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        previous = None
        if existed:
            try:
                previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                previous = None
        target.write_text(content, encoding="utf-8")
        if not target.exists():
            return f"Failed to confirm file creation for '{target.name}'."
        push_undo(f"created {target.name}",
                  _undo_write(target, previous) if existed else _undo_create(target))
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        already = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        # Only offer to undo a folder we actually made. "mkdir -p" on something
        # that was already there is not a change, and undoing it would delete a
        # directory the user has had for years.
        if not already:
            push_undo(f"created folder {target.name}", _undo_create(target))
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Safe-directory check — protect critical user folders
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        original = target.resolve()

        def _execute():
            try:
                result = _safe_trash(original)
                if result.startswith("Moved to Trash"):
                    push_undo(f"deleted {original.name}",
                              lambda p=original: _restore_from_trash(p))
                return result
            except Exception as err:
                return f"Could not delete: {err}"

        from core import confirm
        if confirm.pending_title():
            return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

        return confirm.request(
            key="delete_file",
            title=f"Delete File: {original.name}",
            detail=f"Move to Trash: {original}\nLocation: {original.parent}",
            run=_execute,
        )

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)
        origin = src.resolve()
        shutil.move(str(src), str(dst))
        push_undo(f"moved {origin.name} to {dst.parent.name}/",
                  _undo_move(origin, dst.resolve()))
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        # The undo for a copy is deleting the copy — never the original.
        _copy = dst.resolve()
        def _undo_copy():
            if not _copy.exists():
                return f"The copy '{_copy.name}' is already gone."
            if _copy.is_dir():
                shutil.rmtree(_copy)
            else:
                _copy.unlink()
            return f"Removed the copy in {_copy.parent.name}/."
        push_undo(f"copied {src.name} to {dst.parent.name}/", _undo_copy)

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        old_path = target.resolve()
        target.rename(new_path)
        push_undo(f"renamed {old_path.name} to {new_name}",
                  _undo_move(old_path, new_path.resolve()))
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)

        # Snapshot before writing. None means "did not exist", which is a
        # different undo (delete it) from "existed and had this in it".
        previous: str | None = None
        undoable = True
        if target.exists():
            try:
                if target.stat().st_size > _UNDO_CONTENT_LIMIT:
                    undoable = False       # too large to hold in memory
                else:
                    previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                undoable = False           # binary, locked, unreadable

        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)

        if not target.exists():
            return f"Failed to confirm file write for '{target.name}'."

        action = "Appended to" if append else "Written to"
        if undoable:
            push_undo(f"wrote to {target.name}", _undo_write(target, previous))
            return f"{action}: {target.name}"
        return (f"{action}: {target.name}. "
                f"(Too large to keep a copy of the old contents, so this one "
                f"cannot be undone.)")
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500  # performance + safety limit

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def _parse_organize_task(text: str) -> tuple[str, str, str]:
    """Parse natural language organization task into (source, file_type, destination)."""
    text = text.strip()
    m = re.search(
        r"(?:put|move|organize|transfer|place)\s+(?:all\s+)?(?:my\s+)?(.+?)\s+from\s+(.+?)\s+(?:in|into|to)\s+(?:a\s+folder\s+(?:called|named)\s+|folder\s+)?['\"]?([^'\"]+?)['\"]?$",
        text,
        re.IGNORECASE,
    )
    if m:
        filter_str = m.group(1).strip()
        source_str = m.group(2).strip()
        dest_str = m.group(3).strip().rstrip(".!?,")
        return source_str, filter_str, dest_str
    return "", "", ""


def _resolve_type_filter(filter_str: str) -> tuple[set[str], str]:
    """Resolve file type or natural language category into file extensions."""
    clean = filter_str.lower().strip()
    clean = re.sub(r"\b(files|file|documents|items)\b", "", clean).strip()

    category_map = {
        "pdf": {".pdf"},
        "pdfs": {".pdf"},
        "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "photo": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "photos": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "picture": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "video": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "videos": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "movie": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "movies": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "song": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "songs": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "document": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "zip": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "zips": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    if clean in category_map:
        return category_map[clean], filter_str

    exts = set()
    for part in re.split(r"[,;\s]+", clean):
        part = part.strip().lstrip("*")
        if not part:
            continue
        if not part.startswith("."):
            part = f".{part}"
        exts.add(part.lower())

    if exts:
        return exts, filter_str

    return set(), filter_str


def organize_files(params: dict) -> str:
    """Natural-language multi-step file organization.
    Parses source directory, file-type filter, and destination folder.
    Pre-plans matching files, gates behind confirm.request(), executes on confirm,
    and supports undo via core/undo.py.
    """
    task = str(params.get("task") or params.get("description") or params.get("query") or "").strip()
    source_arg = params.get("source") or params.get("path") or ""
    dest_arg = params.get("destination") or params.get("folder") or params.get("target") or ""
    filter_arg = params.get("file_type") or params.get("extension") or params.get("filter") or ""

    parsed_src, parsed_flt, parsed_dst = _parse_organize_task(task) if task else ("", "", "")

    source = source_arg or parsed_src or "downloads"
    destination = dest_arg or parsed_dst or ""
    filter_str = filter_arg or parsed_flt or ""

    if not destination:
        return "No destination folder specified for organization."

    src_dir = _resolve_path(source)
    if not _is_safe_path(src_dir):
        return f"Access denied (source): {src_dir}"
    if not src_dir.exists():
        return f"Source directory not found: {source}"
    if not src_dir.is_dir():
        return f"Source is not a directory: {source}"

    dest_norm = destination.replace("\\", "/").strip()
    if "/" in dest_norm:
        dst_dir = _resolve_path(destination)
    elif dest_norm.lower() in ("desktop", "downloads", "documents", "pictures", "music", "videos", "home"):
        dst_dir = _resolve_path(destination)
    else:
        dst_dir = src_dir / destination

    if not _is_safe_path(dst_dir):
        return f"Access denied (destination): {dst_dir}"

    target_extensions, filter_desc = _resolve_type_filter(filter_str)

    plan: list[tuple[Path, Path]] = []
    skipped: list[str] = []

    for item in sorted(src_dir.iterdir()):
        if item.is_dir() or item.name.startswith("."):
            continue
        if dst_dir.exists() and item.resolve() == dst_dir.resolve():
            continue
        ext = item.suffix.lower()
        if target_extensions and ext not in target_extensions:
            continue
        target_file = dst_dir / item.name
        if target_file.exists():
            skipped.append(item.name)
            continue
        plan.append((item, target_file))

    if not plan:
        desc = filter_desc if filter_desc.lower().endswith("s") else f"{filter_desc}s"
        msg = f"No matching {desc} found in {src_dir.name}/ to organize." if filter_desc else f"No matching files found in {src_dir.name}/ to organize."
        if skipped:
            msg += f" ({len(skipped)} file(s) already exist in '{dst_dir.name}' and were skipped)."
        return msg

    from core import confirm
    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    preview_lines = [f"• {src.name} → {dst_dir.name}/" for src, dst in plan[:10]]
    if len(plan) > 10:
        preview_lines.append(f"... and {len(plan) - 10} more.")

    detail = (
        f"Source folder: {src_dir}\n"
        f"Destination folder: {dst_dir}\n"
        f"Filter: {filter_desc or 'All matching files'}\n"
        f"Total files to move: {len(plan)}\n\n"
        f"Planned moves:\n" + "\n".join(preview_lines)
    )
    if skipped:
        detail += f"\n\nSkipped (conflict in destination): {len(skipped)} file(s)"

    title = f"Organize Files: Move {len(plan)} file(s) to '{dst_dir.name}'"

    def _execute():
        dst_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        journal: list[tuple[Path, Path]] = []
        for src, dst in plan:
            try:
                if src.exists():
                    origin = src.resolve()
                    shutil.move(str(src), str(dst))
                    if dst.exists():
                        moved += 1
                        journal.append((origin, dst.resolve()))
            except Exception as e:
                print(f"[file_controller] organize error moving {src.name}: {e}")

        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for orig_src, moved_dst in entries:
                    try:
                        if moved_dst.exists():
                            orig_src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_dst), str(orig_src))
                            restored += 1
                    except Exception as err:
                        print(f"[file_controller] undo organize error: {err}")
                try:
                    if dst_dir.exists() and dst_dir.is_dir() and not any(dst_dir.iterdir()):
                        dst_dir.rmdir()
                except Exception:
                    pass
                return f"Restored {restored} file(s) back to {src_dir.name}/."

            push_undo(f"organize files into {dst_dir.name} ({len(journal)} files)", _undo_organize)

        res = f"Organized {moved} file(s) from '{src_dir.name}' into '{dst_dir.name}'."
        if skipped:
            res += f" ({len(skipped)} file(s) skipped due to name conflicts)."
        return res

    return confirm.request(
        key="file_organize",
        title=title,
        detail=detail,
        run=_execute,
    )


def bulk_move(params: dict) -> str:
    """Move multiple files matching a list or pattern from source to destination."""
    source = params.get("source") or params.get("path") or "desktop"
    destination = params.get("destination") or params.get("folder")
    if not destination:
        return "No destination specified for bulk move."

    src_dir = _resolve_path(source)
    dst_dir = _resolve_path(destination)
    if not _is_safe_path(src_dir):
        return f"Access denied (source): {src_dir}"
    if not _is_safe_path(dst_dir):
        return f"Access denied (destination): {dst_dir}"
    if not src_dir.exists() or not src_dir.is_dir():
        return f"Source directory not found: {source}"

    files_list = params.get("files") or []
    pattern = params.get("pattern") or params.get("extension") or ""

    candidates = []
    if files_list:
        for fname in files_list:
            fpath = src_dir / fname
            if fpath.exists() and fpath.is_file():
                candidates.append(fpath)
    elif pattern:
        glob_pat = pattern if any(c in pattern for c in "*?[]") else f"*.{pattern.lstrip('.')}"
        for fpath in sorted(src_dir.glob(glob_pat)):
            if fpath.is_file() and not fpath.name.startswith("."):
                candidates.append(fpath)
    else:
        return "No files or pattern specified for bulk move."

    plan: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    for item in candidates:
        target = dst_dir / item.name
        if target.exists():
            skipped.append(item.name)
            continue
        plan.append((item, target))

    if not plan:
        return f"No files available to move in {src_dir.name}/."

    from core import confirm
    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    preview_lines = [f"• {src.name} → {dst_dir.name}/" for src, dst in plan[:10]]
    if len(plan) > 10:
        preview_lines.append(f"... and {len(plan) - 10} more.")

    detail = (
        f"Source: {src_dir}\n"
        f"Destination: {dst_dir}\n"
        f"Total files: {len(plan)}\n\n"
        f"Planned moves:\n" + "\n".join(preview_lines)
    )

    title = f"Bulk Move: {len(plan)} file(s) to '{dst_dir.name}'"

    def _execute():
        dst_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        journal: list[tuple[Path, Path]] = []
        for src, dst in plan:
            try:
                origin = src.resolve()
                shutil.move(str(src), str(dst))
                if dst.exists():
                    moved += 1
                    journal.append((origin, dst.resolve()))
            except Exception as e:
                print(f"[file_controller] bulk move error: {e}")

        if journal:
            def _undo_bulk_move(entries=tuple(journal)):
                restored = 0
                for orig_src, moved_dst in entries:
                    try:
                        if moved_dst.exists():
                            orig_src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_dst), str(orig_src))
                            restored += 1
                    except Exception as e:
                        print(f"[file_controller] undo bulk move error: {e}")
                return f"Restored {restored} file(s) back to {src_dir.name}/."

            push_undo(f"bulk move ({len(journal)} files)", _undo_bulk_move)

        return f"Bulk move complete: {moved} file(s) moved to '{dst_dir.name}'."

    return confirm.request(
        key="file_bulk_move",
        title=title,
        detail=detail,
        run=_execute,
    )


def bulk_rename(params: dict) -> str:
    """Bulk rename files in a directory using pattern replacement or prefix/suffix."""
    path = params.get("path") or "desktop"
    target_dir = _resolve_path(path)
    if not _is_safe_path(target_dir):
        return f"Access denied: {target_dir}"
    if not target_dir.exists() or not target_dir.is_dir():
        return f"Directory not found: {path}"

    find_str = params.get("find") or params.get("pattern") or ""
    replace_str = params.get("replace") or params.get("replacement") or ""
    prefix = params.get("prefix", "")
    suffix = params.get("suffix", "")
    extension = params.get("extension", "")

    plan: list[tuple[Path, Path]] = []
    skipped: list[str] = []

    for item in sorted(target_dir.iterdir()):
        if item.is_dir() or item.name.startswith("."):
            continue
        if extension and item.suffix.lower() != (extension if extension.startswith(".") else f".{extension}").lower():
            continue

        stem = item.stem
        ext = item.suffix
        new_stem = stem

        if find_str:
            if find_str not in stem:
                continue
            new_stem = stem.replace(find_str, replace_str)

        if prefix:
            new_stem = f"{prefix}{new_stem}"
        if suffix:
            new_stem = f"{new_stem}{suffix}"

        new_name = f"{new_stem}{ext}"
        if new_name == item.name:
            continue

        new_path = target_dir / new_name
        if new_path.exists():
            skipped.append(item.name)
            continue

        plan.append((item, new_path))

    if not plan:
        return f"No files matched the rename pattern in {target_dir.name}/."

    from core import confirm
    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    preview_lines = [f"• {src.name} → {dst.name}" for src, dst in plan[:10]]
    if len(plan) > 10:
        preview_lines.append(f"... and {len(plan) - 10} more.")

    detail = (
        f"Directory: {target_dir}\n"
        f"Total files to rename: {len(plan)}\n\n"
        f"Planned renames:\n" + "\n".join(preview_lines)
    )

    title = f"Bulk Rename: {len(plan)} file(s) in '{target_dir.name}'"

    def _execute():
        renamed = 0
        journal: list[tuple[Path, Path]] = []
        for src, dst in plan:
            try:
                origin = src.resolve()
                src.rename(dst)
                if dst.exists():
                    renamed += 1
                    journal.append((origin, dst.resolve()))
            except Exception as e:
                print(f"[file_controller] bulk rename error: {e}")

        if journal:
            def _undo_bulk_rename(entries=tuple(journal)):
                restored = 0
                for orig_src, renamed_dst in entries:
                    try:
                        if renamed_dst.exists():
                            renamed_dst.rename(orig_src)
                            restored += 1
                    except Exception as e:
                        print(f"[file_controller] undo bulk rename error: {e}")
                return f"Reverted {restored} renamed file(s) in {target_dir.name}/."

            push_undo(f"bulk rename ({len(journal)} files)", _undo_bulk_rename)

        return f"Bulk rename complete: {renamed} file(s) renamed in '{target_dir.name}'."

    return confirm.request(
        key="file_bulk_rename",
        title=title,
        detail=detail,
        run=_execute,
    )


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    plan: list[tuple[Path, Path]] = []
    skipped: list[str] = []

    for item in sorted(desktop.iterdir()):
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.name in type_map:
            continue

        ext = item.suffix.lower()
        target_dir = desktop / "Others"
        for folder, exts in type_map.items():
            if ext in exts:
                target_dir = desktop / folder
                break

        new_path = target_dir / item.name
        if new_path.exists():
            skipped.append(item.name)
            continue
        plan.append((item, new_path))

    if not plan:
        return "Desktop is already organized. No files to move."

    from core import confirm
    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    preview_lines = [f"• {src.name} → {dst.parent.name}/" for src, dst in plan[:8]]
    if len(plan) > 8:
        preview_lines.append(f"... and {len(plan) - 8} more.")

    detail = (
        f"Total files to move: {len(plan)}\n"
        f"Desktop path: {desktop}\n\n"
        f"Planned moves:\n" + "\n".join(preview_lines)
    )

    title = f"Organize Desktop: Move {len(plan)} file(s)"

    def _execute():
        moved = 0
        journal: list[tuple[Path, Path]] = []
        for src, dst in plan:
            try:
                dst.parent.mkdir(exist_ok=True)
                origin = src.resolve()
                shutil.move(str(src), str(dst))
                if dst.exists():
                    moved += 1
                    journal.append((origin, dst.resolve()))
            except Exception as e:
                print(f"[file_controller] organize error: {e}")

        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for origin, moved_to in entries:
                    try:
                        if moved_to.exists():
                            origin.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_to), str(origin))
                            restored += 1
                    except Exception as e:
                        print(f"[file] undo organize: {moved_to.name}: {e}")
                for folder in {m.parent for _o, m in entries}:
                    try:
                        if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                    except Exception:
                        pass
                return f"{restored} file(s) put back on the desktop."
            push_undo(f"organized the desktop ({len(journal)} files)", _undo_organize)

        result = f"Desktop organized: {moved} files moved."
        if skipped:
            result += f" ({len(skipped)} file(s) skipped due to name conflicts)."
        return result

    return confirm.request(
        key="file_organize_desktop",
        title=title,
        detail=detail,
        run=_execute,
    )


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    path   = params.get("path", "desktop")
    name   = params.get("name", "")

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            return create_file(path, name=name, content=params.get("content", ""))

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize" or action == "organize_files":
            return organize_files(params)

        elif action == "bulk_move":
            return bulk_move(params)

        elif action == "bulk_rename":
            return bulk_rename(params)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        elif params.get("task") or params.get("description"):
            task_str = params.get("task") or params.get("description")
            src_str, flt_str, dst_str = _parse_organize_task(task_str)
            if src_str and dst_str:
                return organize_files(params)
            return f"Unknown task: '{task_str}'"

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class FileControllerTool(AgentTool):
    @property
    def name(self) -> str:
        return "file_controller"

    @property
    def description(self) -> str:
        return "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage, organize."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "list | create_file | create_folder | delete | move | bulk_move | copy | rename | bulk_rename | read | write | find | largest | disk_usage | organize | organize_desktop | info"
                },
                "path": {
                    "type": "STRING",
                    "description": "File/folder path or shortcut: desktop, downloads, documents, home"
                },
                "destination": {
                    "type": "STRING",
                    "description": "Destination path for move/copy/organize"
                },
                "new_name": {
                    "type": "STRING",
                    "description": "New name for rename"
                },
                "content": {
                    "type": "STRING",
                    "description": "Content for create_file/write"
                },
                "name": {
                    "type": "STRING",
                    "description": "File name to search for"
                },
                "extension": {
                    "type": "STRING",
                    "description": "File extension to search or filter (e.g. .pdf)"
                },
                "count": {
                    "type": "INTEGER",
                    "description": "Number of results for largest"
                },
                "task": {
                    "type": "STRING",
                    "description": "Natural language task (e.g. 'put all my PDFs from Downloads into a folder called College')"
                }
            },
            "required": [
                "action"
            ]
        }

    def execute(self, parameters: Optional[Dict[str, Any]] = None, **context) -> Any:
        return file_controller(
            parameters=parameters,
            response=context.get("response"),
            player=context.get("player"),
            session_memory=context.get("session_memory"),
        )


ACTION = FileControllerTool()
TOOL = ACTION.to_tool_dict()
