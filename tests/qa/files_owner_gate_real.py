"""Base vs candidate Files front over a real File Browser v2.63.23 scratch container (noauth, as the recipe sets it).
Serve-like headers stand in for Tailscale Serve. Synthetic files only; the container is removed afterwards."""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]); BASE = sys.argv[2]
FB = "filebrowser/filebrowser:v2.63.23@sha256:a469ea076d4a1b4b1d86a41d130f2f536cd9da996a2b1fb39c0d7635f9d89b9a"


def free():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def wait(port):
    for _ in range(150):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close(); return
        except OSError:
            time.sleep(0.1)
    raise SystemExit("port %d never opened" % port)


def source(rev):
    get = (lambda f: subprocess.check_output(["git", "-C", str(REPO), "show", "%s:mcp/%s" % (rev, f)], text=True)) if rev else \
          (lambda f: (REPO / "mcp" / f).read_text())
    return get("front.py") + "\n\n" + get("tools.py") + '\n\nif __name__ == "__main__":\n    asyncio.run(main())\n'


def call(port, method, path, headers, body=None):
    h = {"Host": "box.example.ts.net:8444", **headers}
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def serve(login=None):
    h = {"X-Forwarded-For": "100.64.0.7", "X-Forwarded-Host": "box.example.ts.net:8444", "X-Forwarded-Proto": "https"}
    return {**h, "Tailscale-User-Login": login} if login else h


fp_ = free()
srv = Path(tempfile.mkdtemp(prefix="fb-srv-")); os.chmod(srv, 0o777)
(srv / "Documents").mkdir(); (srv / "Documents" / "synthetic.txt").write_text("synthetic owner file\n"); os.chmod(srv / "Documents", 0o777)
name = "fb-bt386-%d" % fp_
script = ("filebrowser -d /tmp/fb.db config init --root /srv --address 127.0.0.1 --port %d --baseurl /files --auth.method noauth >/dev/null && "
          "filebrowser -d /tmp/fb.db users add admin $(head -c 24 /dev/urandom | base64) --perm.create --perm.delete --perm.modify >/dev/null && "
          "exec filebrowser -d /tmp/fb.db") % fp_
subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--network", "host", "--user", "0:0", "--entrypoint", "/bin/sh",
                "-v", "%s:/srv" % srv, FB, "-c", script], check=True, stdout=subprocess.DEVNULL)
rows = []
try:
    wait(fp_)
    for label, rev, env in (("base " + BASE[:8], BASE, {}), ("candidate", None, {"WIZARD_OWNER_LOGINS": "owner@example.com"}),
                            ("candidate (no owner logins)", None, {})):
        with tempfile.TemporaryDirectory() as tmp:
            port = free(); f = Path(tmp) / "front.py"; f.write_text(source(rev))
            e = {**{k: v for k, v in os.environ.items() if not k.startswith(("WIZARD_", "MCP_"))}, "WIZARD_APP": "files",
                 "FRONT_PORT": str(port), "UPSTREAM_HOST": "127.0.0.1", "UPSTREAM_PORT": str(fp_), "FILES_ROOT": str(srv), **env}
            proc = subprocess.Popen([sys.executable, str(f)], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(port)
                out = {}
                for who, h in (("owner", serve("owner@example.com")), ("stranger", serve("stranger@example.com")), ("no-login", serve()), ("box", {})):
                    code, tok = call(port, "POST", "/files/api/login", {**h, "Content-Type": "application/json"}, b'{"username":"","password":"","recaptcha":""}')
                    listed = call(port, "GET", "/files/api/resources/Documents/", {**h, "X-Auth": tok})[0] if code == 200 else None
                    page = call(port, "GET", "/files/", h)[0]
                    out[who] = {"page": page, "login": code, "list": listed}
                # The destructive case: a stranger deletes the owner's file (only if they got a token).
                code, tok = call(port, "POST", "/files/api/login", {**serve("stranger@example.com"), "Content-Type": "application/json"}, b"{}")
                out["stranger_delete"] = call(port, "DELETE", "/files/api/resources/Documents/synthetic.txt", {**serve("stranger@example.com"), "X-Auth": tok})[0] if code == 200 else code
                out["file_still_there"] = (srv / "Documents" / "synthetic.txt").exists()
                print(label, json.dumps(out))
                (srv / "Documents" / "synthetic.txt").write_text("synthetic owner file\n")
            finally:
                proc.terminate(); proc.wait(10)
finally:
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
