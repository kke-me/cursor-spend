import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import HTTPServer
from io import StringIO
from pathlib import Path
from unittest import mock

import refresh

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "payload.json").read_text(encoding="utf-8")
)


def fake_api(method, url, token, body=None):
    if url == refresh.AUTH_PROFILE:
        return {"teamId": 1}
    if url == refresh.USAGE:
        return FIXTURE["usage"]
    if url == refresh.PLAN:
        return FIXTURE["plan"]
    if url == refresh.EVENTS:
        return {"usageEventsDisplay": FIXTURE["events"] if body["page"] == 1 else []}
    raise AssertionError(url)


def broken_token():
    raise RuntimeError("no token")


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.snapshot = Path(tmp.name) / "snapshot.js"
        for target, value in (("SNAPSHOT_PATH", self.snapshot), ("api_json", fake_api)):
            patcher = mock.patch.object(refresh, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def written(self):
        return json.loads(self.snapshot.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))

    def serve(self):
        httpd = HTTPServer(("127.0.0.1", 0), refresh.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_port}"

    def get(self, url):
        try:
            with urllib.request.urlopen(url) as resp:
                return resp.status, resp.headers["Content-Type"], resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers["Content-Type"], e.read()

    def run_main(self):
        with mock.patch("sys.argv", ["refresh.py"]), redirect_stdout(StringIO()) as out:
            code = refresh.main()
        return code, out.getvalue().splitlines()

    def test_main_writes_snapshot_and_prints_on_demand_total(self):
        with mock.patch.object(refresh, "read_token", lambda: "t"):
            code, lines = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["17.12", str(self.snapshot)])
        self.assertIsNone(self.written()["error"])
        self.assertEqual(self.written()["spend"]["onDemandUsd"], 17.12)

    def test_main_failure_writes_error_snapshot(self):
        with mock.patch.object(refresh, "read_token", broken_token):
            code, lines = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["0", str(self.snapshot)])
        self.assertEqual(self.written()["error"], "no token")

    def test_refresh_endpoint_returns_snapshot(self):
        base = self.serve()
        with mock.patch.object(refresh, "read_token", lambda: "t"):
            status, ctype, body = self.get(base + "/refresh")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json; charset=utf-8")
        self.assertEqual(json.loads(body)["spend"]["onDemandUsd"], 17.12)
        self.assertEqual(json.loads(body), self.written())

    def test_refresh_endpoint_failure_returns_error_snapshot(self):
        base = self.serve()
        with mock.patch.object(refresh, "read_token", broken_token):
            status, _, body = self.get(base + "/refresh?x=1")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body)["error"], "no token")

    def test_serves_dashboard_and_snapshot(self):
        base = self.serve()
        status, ctype, body = self.get(base + "/")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b'<script src="snapshot.js">', body)
        status, ctype, body = self.get(base + "/snapshot.js")
        self.assertEqual((status, ctype), (200, "application/javascript; charset=utf-8"))
        self.assertTrue(body.startswith(b"window.SNAPSHOT = "))

    def test_unknown_path_is_404(self):
        self.assertEqual(self.get(self.serve() + "/nope.html")[0], 404)


if __name__ == "__main__":
    unittest.main()
