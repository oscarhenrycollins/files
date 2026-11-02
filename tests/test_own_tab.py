"""Browser boundary, approved separate-origin exception (wizard-os #385, Files decision 2 Nov 2026): with
WIZARD_BROWSER_BOUNDARY=1 File Browser opens only as its own tab on its own origin. The real front process refuses
frame, opaque/foreign-Origin and cross-/same-site requests before File Browser sees them, refuses an old owner-origin
route when WIZARD_OWN_HOSTS is set, and marks every reply DENY for framing. Off, nothing changes. Synthetic data,
stub File Browser that records each request."""
import http.client, http.server, socket, tempfile, threading, unittest

from test_owner_gate import Engine, Front, HITS

OWN = "box.example.ts.net:8794"        # Files' own origin (its own HTTPS port)
SHELL = "box.example.ts.net:8444"      # the Wizard (owner) origin on the same host: same-site, different origin
FRAME = [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "navigate"), ("Sec-Fetch-Dest", "iframe")]
OPAQUE_FETCH = [("Origin", "null"), ("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty")]
SAME_SITE_FETCH = [("Origin", "https://" + SHELL), ("Sec-Fetch-Site", "same-site"), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty"),
                   ("Cookie", "auth=synthetic-jwt")]
SAME_SITE_NAV = [("Sec-Fetch-Site", "same-site"), ("Sec-Fetch-Mode", "navigate"), ("Sec-Fetch-Dest", "document"), ("Sec-Fetch-User", "?1")]
OWN_PAGE = [("Origin", "https://" + OWN), ("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty"),
            ("Cookie", "auth=synthetic-jwt")]


def serve():
    return [("X-Forwarded-For", "100.64.0.7"), ("X-Forwarded-Proto", "https"), ("Tailscale-User-Login", "owner@example.com")]


def req(front, method, path, headers=(), host=OWN, body=None):
    c = http.client.HTTPConnection("127.0.0.1", front.port, timeout=10)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    for k, v in headers:
        c.putheader(k, v)
    if body is not None:
        c.putheader("Content-Length", str(len(body)))
    c.endheaders(body)
    r = c.getresponse()
    data = r.read()
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, data)
    c.close()
    return out


class OwnTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Engine)
        threading.Thread(target=cls.engine.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        up = cls.engine.server_address[1]
        logins = dict(WIZARD_OWNER_LOGINS="owner@example.com")
        cls.off = Front(cls.tmp.name, up, **logins)
        cls.on = Front(cls.tmp.name, up, WIZARD_BROWSER_BOUNDARY="1", **logins)
        cls.pinned = Front(cls.tmp.name, up, WIZARD_BROWSER_BOUNDARY="1", WIZARD_OWN_HOSTS=OWN, **logins)

    @classmethod
    def tearDownClass(cls):
        for f in (cls.off, cls.on, cls.pinned):
            f.stop()
        cls.engine.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        HITS.clear()

    def test_off_is_unchanged(self):
        status, headers, _ = req(self.off, "GET", "/files/api/resources/", serve() + FRAME)
        self.assertEqual(status, 200)
        self.assertNotIn("x-frame-options", headers)
        self.assertEqual(HITS, [("GET", "/files/api/resources/")])

    def test_frames_refused_before_file_browser(self):
        for front in (self.on, self.pinned):
            HITS.clear()
            status, headers, body = req(front, "GET", "/files/", serve() + FRAME)
            self.assertEqual(status, 403)
            self.assertIn(b"never opens inside another page", body)
            self.assertEqual(headers.get("x-frame-options"), "DENY")
            self.assertEqual(HITS, [])

    def test_opaque_frame_fetch_and_simple_post_refused(self):
        for method, path, body in (("GET", "/files/api/resources/", None), ("POST", "/files/api/login", b"{}"),
                                   ("DELETE", "/files/api/resources/Documents/synthetic.txt", None)):
            status, _, _ = req(self.on, method, path, serve() + OPAQUE_FETCH, body=body)
            self.assertEqual(status, 403, (method, path))
        # A no-cors image load from the frame: no Origin, but cross-site.
        status, _, _ = req(self.on, "GET", "/files/api/raw/Documents/synthetic.txt", serve() + [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "no-cors"), ("Sec-Fetch-Dest", "image")])
        self.assertEqual(status, 403)
        self.assertEqual(HITS, [])

    def test_other_wizard_origin_on_same_host_refused_even_with_cookie(self):
        # A same-origin app page on the Wizard address is same-site to Files' own port; SameSite=Strict still sends
        # File Browser's cookie, so the front must refuse it itself.
        status, _, _ = req(self.on, "GET", "/files/api/resources/", serve() + SAME_SITE_FETCH)
        self.assertEqual(status, 403)
        status, _, _ = req(self.on, "POST", "/files/api/login", serve() + SAME_SITE_FETCH, body=b"{}")
        self.assertEqual(status, 403)
        self.assertEqual(HITS, [])

    def test_shell_opening_the_tab_is_a_plain_navigation(self):
        status, headers, _ = req(self.pinned, "GET", "/files/", serve() + SAME_SITE_NAV)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        self.assertEqual(headers.get("content-security-policy"), "frame-ancestors 'none'")
        self.assertEqual(headers.get("cross-origin-opener-policy"), "same-origin")
        self.assertEqual(headers.get("cross-origin-resource-policy"), "same-origin")
        # A cross-site POST navigation (CSRF form) is not a plain navigation.
        status, _, _ = req(self.pinned, "POST", "/files/api/resources/x", serve() + SAME_SITE_NAV, body=b"x")
        self.assertEqual(status, 403)
        self.assertEqual(HITS, [("GET", "/files/")])

    def test_own_page_keeps_working_including_uploads(self):
        status, headers, _ = req(self.pinned, "GET", "/files/api/resources/", serve() + OWN_PAGE)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        status, _, _ = req(self.pinned, "POST", "/files/api/tus/Documents/new.txt", serve() + OWN_PAGE, body=b"x" * 200000)
        self.assertEqual(status, 200)
        self.assertEqual(HITS, [("GET", "/files/api/resources/"), ("POST", "/files/api/tus/Documents/new.txt")])

    def test_old_owner_origin_route_refused(self):
        status, _, body = req(self.pinned, "GET", "/files/api/resources/", serve() + [("Origin", "https://" + SHELL), ("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty")], host=SHELL)
        self.assertEqual(status, 403)
        self.assertIn(b"own tab", body)
        status, _, _ = req(self.pinned, "GET", "/files/", serve() + [("Sec-Fetch-Site", "none"), ("Sec-Fetch-Mode", "navigate"), ("Sec-Fetch-Dest", "document")], host=SHELL)
        self.assertEqual(status, 403)
        self.assertEqual(HITS, [])

    def test_box_apps_unchanged(self):
        status, headers, _ = req(self.pinned, "GET", "/files/api/resources/", [], host="files:8080")
        self.assertEqual(status, 200)
        self.assertEqual(HITS, [("GET", "/files/api/resources/")])

    def test_mcp_from_a_frame_refused(self):
        status, _, _ = req(self.on, "POST", "/mcp", OPAQUE_FETCH + [("Content-Type", "text/plain")], body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
