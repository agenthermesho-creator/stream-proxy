"""Stream proxy - FWC TV World Cup 2026"""
import os
import re
import requests
from functools import wraps
from flask import Flask, request, Response, send_from_directory
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="")

TARGET = "https://fifaworldcup.cfd"
R2_BASE = "https://pub-e58dbb8fb8d744a1a664e49157be4c1b.r2.dev"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
PASSWORD = os.environ.get("PASSWORD", "")
AUTH_ENABLED = bool(PASSWORD)


def check_auth():
    if not AUTH_ENABLED:
        return True
    auth = request.authorization
    return auth and auth.password == PASSWORD


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_auth():
            return Response(
                "Unauthorized", 401,
                {"WWW-Authenticate": 'Basic realm="Stream"'}
            )
        return f(*args, **kwargs)
    return decorated


@app.route("/")
@require_auth
def index():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


@app.route("/proxy/api/stream")
@require_auth
def proxy_stream():
    """Fetch the HLS playlist from FWC API and rewrite R2 segment URLs."""
    quality = request.args.get("q", "4k")
    target_url = f"{TARGET}/api/stream?q={quality}"

    headers = {
        "User-Agent": UA,
        "Referer": f"{TARGET}/watch",
        "Origin": TARGET,
    }

    try:
        resp = requests.get(target_url, headers=headers, stream=True, timeout=30)
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        body = resp.content

        if resp.status_code != 200:
            return Response(body, status=resp.status_code,
                           content_type=content_type)

        # Rewrite R2 absolute URLs to stay within proxy
        text = body.decode("utf-8", errors="replace")
        text = text.replace(R2_BASE, "/proxy/r2")
        body = text.encode("utf-8")

        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        response_headers["Access-Control-Allow-Origin"] = "*"
        response_headers["Cache-Control"] = "no-cache"

        return Response(body, status=resp.status_code,
                       headers=response_headers, content_type=content_type)

    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)


@app.route("/proxy/r2/<path:subpath>")
@require_auth
def proxy_r2(subpath):
    """Proxy TS segments from Cloudflare R2."""
    target_url = f"{R2_BASE}/{subpath}"
    qs = request.query_string.decode()
    if qs:
        target_url += f"?{qs}"

    headers = {
        "User-Agent": UA,
        "Referer": TARGET,
    }

    try:
        resp = requests.get(target_url, headers=headers, stream=True, timeout=30)
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        body = resp.content

        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        response_headers["Access-Control-Allow-Origin"] = "*"
        response_headers["Cache-Control"] = "public, max-age=31536000"

        return Response(body, status=resp.status_code,
                       headers=response_headers, content_type=content_type)

    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
