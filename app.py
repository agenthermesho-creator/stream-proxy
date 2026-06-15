"""Stream proxy — generic URL proxy for HLS streams"""
import os
import re
import requests
from functools import wraps
from flask import Flask, request, Response, send_from_directory
from datetime import datetime
from urllib.parse import quote, unquote

app = Flask(__name__, static_folder="static", static_url_path="")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
# The playlist server requires this specific Referer
REFERER = "https://gooz.aapmains.net/"
ORIGIN = "https://gooz.aapmains.net"
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


@app.route("/proxy")
@require_auth
def proxy():
    """Generic proxy: /proxy?url=<encoded_url>

    Fetches any URL with proper headers and rewrites m3u8 playlists
    so all segment URLs route back through this proxy.
    """
    target_url = request.args.get("url")
    if not target_url:
        return Response("Missing url param", 400)

    target_url = unquote(target_url)

    headers = {
        "User-Agent": UA,
        "Referer": REFERER,
        "Origin": ORIGIN,
    }

    try:
        resp = requests.get(target_url, headers=headers, stream=True, timeout=30)
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        body = resp.content

        # Rewrite m3u8 playlists to route segments through proxy
        is_playlist = (
            "mpegurl" in content_type
            or target_url.endswith(".m3u8")
            or body[:30].strip().startswith(b"#EXTM3U")
        )

        if is_playlist:
            text = body.decode("utf-8", errors="replace")

            def rewrite_url(match):
                url = match.group(0)
                # Don't double-proxy our own URLs
                if "stream-proxy" in url or "localhost" in url:
                    return url
                return f"/proxy?url={quote(url, safe='')}"

            text = re.sub(r"https?://[^\s\r\n]+", rewrite_url, text)
            body = text.encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
