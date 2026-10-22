"""TEST FIXTURE server: serves tests/fixtures/vhosts/<Host>/ for local end-to-end tests only."""
import http.server
import os
import sys
from functools import partial

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vhosts")


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host.startswith("www."):
            host = host[4:]
        base = os.path.join(ROOT, host)
        path = path.split("?", 1)[0].split("#", 1)[0]
        full = os.path.normpath(os.path.join(base, path.lstrip("/")))
        if not full.startswith(base):
            return os.path.join(base, "__nope__")
        return full

    def guess_type(self, path):
        if path.endswith("ads.txt"):
            return "text/plain"
        if "/" in path and "." not in os.path.basename(path):
            return "text/html"
        return super().guess_type(path)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
