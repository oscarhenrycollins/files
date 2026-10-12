# Files tools: work directly in the shared Files folder (the same folder File Browser shows).
# Every path is relative to that folder. Nothing outside it can be reached, hidden (dot) files are
# off limits like in File Browser, and there is no delete: removing things stays a human action.

ROOT = os.path.realpath(os.environ.get("FILES_ROOT", "/srv"))
MAX_READ = 1 << 20       # text returned per read
MAX_WRITE = 1 << 20      # text accepted per write
MAX_LIST = 500
MAX_SCAN = 20000         # entries visited per search
os.umask(0o002)          # same sharing as File Browser (files 0664, folders 0775)


def _box_only():
    """Files tools answer only to apps on this box (e.g. the agent through the Wizard hub), never to a request
    that came in through Tailscale Serve, a tunnel or the App Manager's proxy: those reach File Browser itself,
    behind its own login when one is set."""
    h = REQUEST.get()
    if any(h.get(k) for k in ("tailscale-user-login", "x-forwarded-for", "forwarded", "cf-connecting-ip",
                              "cf-access-jwt-assertion", "x-real-ip")):
        raise PermissionError("the Files tools are only for apps on this box")


def _safe(path, must_exist=True):
    _box_only()
    rel = str(path or "").strip().replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." or p.startswith(".") for p in parts):
        raise ValueError("paths stay inside Files and can't name hidden files")
    full = os.path.realpath(os.path.join(ROOT, *parts))
    if full != ROOT and not full.startswith(ROOT + os.sep):
        raise ValueError("that path leads outside the Files folder")
    if must_exist and not os.path.exists(full):
        raise FileNotFoundError("nothing at '%s' in Files" % "/".join(parts))
    return full, "/".join(parts)


def _entry(full, rel):
    st = os.stat(full)
    is_dir = os.path.isdir(full)
    out = {"path": rel or "/", "name": os.path.basename(full) if rel else "Files",
           "type": "folder" if is_dir else "file",
           "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))}
    if not is_dir:
        out["size"] = st.st_size
    return out


@tool("files_list", "List a folder in the owner's Files (the shared folder every app uses). "
      "Paths are relative to Files, e.g. '' for the top, 'Videos' or 'Documents/Taxes'.",
      {"path": {"type": "string", "description": "Folder inside Files; empty for the top"},
       "limit": {"type": "integer", "description": "Max entries, default 200, up to 500"}})
def files_list(path="", limit=200):
    full, rel = _safe(path)
    if not os.path.isdir(full):
        raise NotADirectoryError("'%s' is a file, not a folder" % rel)
    names = sorted((n for n in os.listdir(full) if not n.startswith(".")), key=str.lower)
    cap = max(1, min(int(limit or 200), MAX_LIST))
    items = []
    for n in names[:cap]:
        try:
            items.append(_entry(os.path.join(full, n), (rel + "/" + n) if rel else n))
        except OSError:
            continue
    return {"folder": rel or "/", "count": len(names), "shown": len(items), "items": items}


@tool("files_find", "Find files or folders in Files whose name contains some text (not case sensitive).",
      {"query": {"type": "string", "description": "Part of the name, e.g. 'invoice' or '.mp4'"},
       "path": {"type": "string", "description": "Folder to search in; empty for all of Files"},
       "limit": {"type": "integer", "description": "Max results, default 50"}},
      ["query"])
def files_find(query, path="", limit=50):
    q = str(query or "").strip().lower()
    if not q:
        raise ValueError("say what to look for")
    full, rel = _safe(path)
    cap = max(1, min(int(limit or 50), MAX_LIST))
    found, seen = [], 0
    for top, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        base = os.path.relpath(top, ROOT)
        base = "" if base == "." else base.replace(os.sep, "/")
        for n in dirs + sorted(f for f in files if not f.startswith(".")):
            seen += 1
            if q in n.lower():
                try:
                    found.append(_entry(os.path.join(top, n), (base + "/" + n) if base else n))
                except OSError:
                    pass
                if len(found) >= cap:
                    return {"query": q, "results": found, "complete": False}
            if seen >= MAX_SCAN:
                return {"query": q, "results": found, "complete": False}
    return {"query": q, "results": found, "complete": True}


@tool("files_read", "Read a text file from Files (notes, markdown, CSV, JSON, subtitles...). "
      "Binary files such as videos or PDFs are described, not returned.",
      {"path": {"type": "string", "description": "File inside Files, e.g. 'Documents/notes.md'"}},
      ["path"])
def files_read(path):
    full, rel = _safe(path)
    if os.path.isdir(full):
        raise IsADirectoryError("'%s' is a folder; use files_list" % rel)
    info = _entry(full, rel)
    with open(full, "rb") as fh:
        data = fh.read(MAX_READ + 1)
    if b"\x00" in data[:8192]:
        info["text"] = None
        info["note"] = "binary file; pass its path to the app that handles it, or open it in the Files app"
        return info
    try:
        text = data[:MAX_READ].decode("utf-8")
    except UnicodeDecodeError:
        text = data[:MAX_READ].decode("utf-8", "replace")
    info["text"] = text
    info["truncated"] = len(data) > MAX_READ
    return info


@tool("files_write", "Save a text file in Files so the owner can open it in the Files app. "
      "Won't replace an existing file unless overwrite is true. Never deletes anything.",
      {"path": {"type": "string", "description": "Where to save, e.g. 'Documents/summary.md'"},
       "text": {"type": "string", "description": "The file's full text"},
       "overwrite": {"type": "boolean", "description": "Replace the file if it already exists (default false)"},
       "make_folders": {"type": "boolean", "description": "Create missing folders on the way (default true)"}},
      ["path", "text"])
def files_write(path, text, overwrite=False, make_folders=True):
    full, rel = _safe(path, must_exist=False)
    if not rel:
        raise ValueError("give a file name")
    body = str(text if text is not None else "").encode("utf-8")
    if len(body) > MAX_WRITE:
        raise ValueError("text is over 1 MB; split it into several files")
    if os.path.isdir(full):
        raise IsADirectoryError("'%s' is a folder" % rel)
    if os.path.exists(full) and not overwrite:
        raise FileExistsError("'%s' already exists; set overwrite to replace it" % rel)
    parent = os.path.dirname(full)
    if not os.path.isdir(parent):
        if not make_folders:
            raise FileNotFoundError("folder for '%s' doesn't exist" % rel)
        _safe(os.path.relpath(parent, ROOT), must_exist=False)
        os.makedirs(parent, mode=0o775, exist_ok=True)
    tmp = os.path.join(parent, ".files-write-%d.tmp" % os.getpid())
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, full)
    return {"saved": _entry(full, rel)}


@tool("files_new_folder", "Create a folder in Files (and any missing folders above it).",
      {"path": {"type": "string", "description": "e.g. 'Documents/Receipts/2026'"}}, ["path"])
def files_new_folder(path):
    full, rel = _safe(path, must_exist=False)
    if not rel:
        raise ValueError("give a folder name")
    if os.path.exists(full) and not os.path.isdir(full):
        raise FileExistsError("'%s' is a file" % rel)
    os.makedirs(full, mode=0o775, exist_ok=True)
    return {"folder": _entry(full, rel)}
