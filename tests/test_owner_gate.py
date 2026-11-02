"""File Browser runs with no login of its own (noauth), so before this gate anyone on the tailnet who reached Files'
Serve routes could read, write and delete every file. The real front process now lets a request that came through
Tailscale Serve or a proxy reach File Browser only as the box owner; apps on this box and share links are
unchanged. Synthetic data, stub File Browser that records each request."""
import http.client, http.server, json, os, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HITS = []


class Engine(http.server.BaseHTTPRequestHandler):
    def reply(self):
        HITS.append((self.command, self.path))
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        body = b'{"items":[{"name":"synthetic.txt"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = reply

    def log_message(self, format, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Front:
    def __init__(self, tmp, up, **env):
        self.port = free_port()
        src = (ROOT / "mcp/front.py").read_text() + "\n\n" + (ROOT / "mcp/tools.py").read_text()
        f = Path(tmp) / ("front-%d.py" % self.port)
        f.write_text(src + '\n\nif __name__ == "__main__":\n    asyncio.run(main())\n')
        (Path(tmp) / "srv").mkdir(exist_ok=True)
        e = {k: v for k, v in os.environ.items() if not k.startswith(("WIZARD_", "MCP_"))}
        e.update(WIZARD_APP="files", FRONT_PORT=str(self.port), UPSTREAM_HOST="127.0.0.1", UPSTREAM_PORT=str(up),
                 FILES_ROOT=str(Path(tmp) / "srv"), PYTHONDONTWRITEBYTECODE="1", **env)
        self.proc = subprocess.Popen([sys.executable, str(f)], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("front did not start: " + self.proc.communicate(timeout=5)[0].decode()[-500:])

    def stop(self):
        self.proc.terminate()
        self.proc.communicate(timeout=10)

    def req(self, method, path, headers=(), body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", "box.example.ts.net:8444")
        for k, v in headers:
            c.putheader(k, v)
        if body is not None:
            c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data


def serve(login=None):
    h = [("X-Forwarded-For", "100.64.0.7"), ("X-Forwarded-Host", "box.example.ts.net:8444"), ("X-Forwarded-Proto", "https")]
    return h + ([("Tailscale-User-Login", login), ("Tailscale-User-Name", "Someone")] if login else [])


DELETE = ("DELETE", "/files/api/resources/Documents/synthetic.txt")
LIST = ("GET", "/files/api/resources/")


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Engine)
        threading.Thread(target=self.engine.serve_forever, daemon=True).start()
        self.fronts = []

    def tearDown(self):
        for f in self.fronts:
            f.stop()
        self.engine.shutdown()
        self.tmp.cleanup()

    def front(self, **env):
        f = Front(self.tmp.name, self.engine.server_address[1], **env)
        self.fronts.append(f)
        return f

    def check(self, front, req, headers, code):
        before = len(HITS)
        got, data = front.req(*req, headers)
        self.assertEqual(got, code, (req, headers, data))
        self.assertEqual(len(HITS) - before, 1 if code == 200 else 0, "refused requests never reach File Browser")

    def test_only_the_owner_login_through_serve(self):
        f = self.front(WIZARD_OWNER_LOGINS="owner@example.com")
        for req in (LIST, DELETE, ("POST", "/files/api/tus/Documents/x.bin"), ("GET", "/files/api/raw/Documents/x.pdf")):
            self.check(f, req, serve("owner@example.com"), 200)
            self.check(f, req, serve("stranger@example.com"), 403)        # another tailnet member
            self.check(f, req, serve(), 403)                              # tagged device, Funnel, proxy
            self.check(f, req, serve("owner@example.com") + [("Tailscale-User-Login", "stranger@example.com")], 403)
        self.check(f, ("GET", "/"), serve("stranger@example.com"), 403)   # the app's own port too
        self.check(f, LIST, [("Forwarded", "for=100.64.0.7")], 403)
        self.check(f, LIST, [("X-Real-IP", "100.64.0.7")], 403)

    def test_without_owner_logins_a_single_tailnet_user_still_opens_files(self):
        # Installs made before the recipe declared WIZARD_OWNER_LOGINS: the owner keeps Files; no-login callers don't.
        f = self.front()
        self.check(f, LIST, serve("owner@example.com"), 200)
        self.check(f, DELETE, serve(), 403)

    def test_box_apps_and_share_links_are_unchanged(self):
        f = self.front(WIZARD_OWNER_LOGINS="owner@example.com")
        self.check(f, LIST, [], 200)                                      # an app on this box
        self.check(f, DELETE, [], 200)
        self.check(f, ("GET", "/files/share/AbCdEf12"), serve("friend@example.com"), 200)
        self.check(f, ("GET", "/files/api/public/dl/AbCdEf12/x.pdf"), serve("friend@example.com"), 200)
        self.check(f, ("GET", "/files/static/js/app.js"), serve(), 200)
        for sneaky in ("/files/share/../api/resources/", "/files/share/%2e%2e/api/resources/",
                       "/files/share//api/resources/", "/files/api/public/..%2f..%2fapi/resources/"):
            self.check(f, ("GET", sneaky), serve("friend@example.com"), 403)

    def test_mcp_handshake_is_box_only_without_a_token(self):
        f = self.front()
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        code, data = f.req("POST", "/mcp", serve("owner@example.com") + [("Content-Type", "application/json")], body)
        self.assertEqual(code, 403, data)
        code, data = f.req("POST", "/mcp", [("Content-Type", "application/json")], body)
        self.assertEqual(code, 200)
        self.assertIn("files_list", [t["name"] for t in json.loads(data)["result"]["tools"]])

    def test_recipe_asks_the_app_manager_for_the_owner_login(self):
        text = (ROOT / "runtipi/docker-compose.yml").read_text()
        self.assertIn("WIZARD_OWNER_LOGINS: ${WIZARD_OWNER_LOGINS:-}", text)
        self.assertIn("WIZARD_TRUSTED_HOSTS: ${WIZARD_TRUSTED_HOSTS:-}", text)   # wam trusted_origin_env needs both


if __name__ == "__main__":
    unittest.main()
