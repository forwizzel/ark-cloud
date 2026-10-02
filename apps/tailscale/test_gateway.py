import http.client
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import controller
import runtime

TEMPLATE = Path(__file__).with_name("nginx.conf")
if not TEMPLATE.exists():
    TEMPLATE = Path("/etc/nginx/nginx.conf")
TOKEN = "test_only_remote_proof_-123"


class GatewayTests(unittest.TestCase):
    def test_render_rejects_directive_injection_and_keeps_secret_private(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "nginx.conf"
            with (
                patch.object(runtime, "GATEWAY_CONFIG", config),
                patch.object(runtime, "GATEWAY_TEMPLATE", TEMPLATE),
            ):
                for invalid in ("", "token; return 200;", "token\n", 'token"', "$host"):
                    with self.assertRaises(ValueError):
                        runtime.render_gateway(invalid)
                    self.assertFalse(config.exists())
                runtime.render_gateway(TOKEN)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("__ARK_REMOTE_TOKEN__", config.read_text())
                runtime.render_gateway("rotated_token")
                self.assertNotIn(TOKEN, config.read_text())
                self.assertEqual(list(Path(temp).iterdir()), [config])

    def test_nginx_output_cannot_leak_rendered_credentials(self):
        with patch.object(runtime.subprocess, "Popen") as popen:
            runtime.start_gateway()
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn(TOKEN, str(popen.call_args))

    def test_shared_token_validation_matches_gateway(self):
        with patch.object(controller, "TOKEN") as token_file:
            for invalid in ("token;directive", "$host", "a b", "a" * 4097):
                token_file.read_text.return_value = invalid
                with self.assertRaises(controller.ControllerError):
                    controller.read_token()
            token_file.read_text.return_value = TOKEN + "\n"
            self.assertEqual(controller.read_token(), TOKEN)

    @unittest.skipUnless(shutil.which("nginx"), "requires the controller image's nginx")
    def test_real_gateway_overrides_proof_and_host_blocks_callbacks_and_streams(self):
        received = []

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(dict(self.headers))
                if self.headers.get("Upgrade") == "websocket":
                    self.send_response(101)
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.end_headers()
                    return
                body = json.dumps({"path": self.path}).encode()
                self.send_response(200)
                # Even an upstream accidentally echoing the proof header must
                # not expose it as a response header to the browser.
                self.send_header("X-Ark-Remote-Access", self.headers["X-Ark-Remote-Access"])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                received.append(dict(self.headers))
                body = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                template = TEMPLATE.read_text().replace("127.0.0.1:8080", f"127.0.0.1:{port}")
                template = template.replace(
                    "http://web:5173", f"http://127.0.0.1:{upstream.server_port}"
                )
                template = template.replace("/tmp/", temp + "/")
                source = root / "template.conf"
                source.write_text(template)
                config = root / "nginx.conf"
                with (
                    patch.object(runtime, "GATEWAY_CONFIG", config),
                    patch.object(runtime, "GATEWAY_TEMPLATE", source),
                ):
                    runtime.render_gateway(TOKEN)
                nginx = subprocess.Popen(
                    ["nginx", "-c", str(config), "-e", "/dev/null", "-g", "daemon off;"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    for _ in range(50):
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                                break
                        except OSError:
                            time.sleep(0.05)
                    headers = {
                        "Host": "arkcloud.example.ts.net:443",
                        "X-Ark-Remote-Access": "client_forgery",
                        "X-Forwarded-Host": "evil.example",
                        "X-Forwarded-Proto": "http",
                    }

                    def request(path, method="GET", body=None, extra=None):
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                        try:
                            connection.request(method, path, body, {**headers, **(extra or {})})
                            response = connection.getresponse()
                            return response.status, dict(response.headers), response.read()
                        finally:
                            connection.close()

                    status, response_headers, body = request("/api/health?example=1")
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)["path"], "/api/health?example=1")
                    self.assertNotIn("X-Ark-Remote-Access", response_headers)
                    self.assertNotIn(TOKEN.encode(), body)
                    self.assertEqual(received[-1]["Host"], "localhost:5173")
                    self.assertEqual(received[-1]["X-Ark-Remote-Access"], TOKEN)
                    self.assertEqual(received[-1]["X-Forwarded-Host"], "arkcloud.example.ts.net")
                    self.assertEqual(received[-1]["X-Forwarded-Proto"], "https")
                    for path in (
                        "/api/admin/tailscale/controller",
                        "/api/admin/tailscale/controller/work?needs_auth=true",
                        "/api/admin/tailscale/controller/report",
                    ):
                        self.assertEqual(request(path)[0], 404)
                    self.assertEqual(request("/", extra={"Host": "evil.example"})[0], 404)
                    self.assertEqual(len(received), 1)
                    upload = b"streamed upload" * 100000
                    self.assertEqual(request("/upload", "POST", upload)[2], upload)
                    websocket_status = request(
                        "/socket", extra={"Upgrade": "websocket", "Connection": "Upgrade"}
                    )
                    self.assertEqual(websocket_status[0], 101)
                finally:
                    nginx.terminate()
                    output, errors = nginx.communicate(timeout=5)
                    self.assertNotIn(TOKEN.encode(), output + errors)
                    self.assertEqual(output + errors, b"")
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
