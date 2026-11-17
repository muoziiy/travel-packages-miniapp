import json, os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8740"))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(BASE, "static"), **kw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/packages":
            with open(os.path.join(BASE, "packages.json"), "rb") as f:
                self._json(f.read())
        elif path == "/health":
            self._json(b'{"ok":true}')
        else:
            super().do_GET()

    def _json(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

print("listening on", PORT, flush=True)
HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
