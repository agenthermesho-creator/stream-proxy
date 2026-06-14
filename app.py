"""Stream proxy - FWC TV World Cup 2026"""
import os
import re
import requests
from functools import wraps
from flask import Flask, request, Response, send_from_directory
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="")

TARGET = "https://fifaworldcup.cfd"
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


@app.route("/proxy/<path:subpath>")
@require_auth
def proxy(subpath):
    target_url = f"{TARGET}/{subpath}"
    qs = request.query_string.decode()
    if qs:
        target_url += f"?{qs}"

    headers = {
        "User-Agent": UA,
        "Referer": f"{TARGET}/",
        "Origin": f"{TARGET}",
    }

    try:
        resp = requests.get(target_url, headers=headers, stream=True, timeout=30)
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        body = resp.content

        # Rewrite absolute segment paths inside .m3u8 to stay within /proxy/
        if "mpegurl" in content_type or subpath.endswith(".m3u8"):
            text = body.decode("utf-8", errors="replace")
            text = re.sub(
                r"^(/[a-z]+/.*\.\w+)$",
                r"/proxy\1",
                text, flags=re.MULTILINE
            )
            body = text.encode("utf-8")

        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        response_headers["Access-Control-Allow-Origin"] = "*"
        response_headers["Cache-Control"] = resp.headers.get(
            "Cache-Control", "no-cache"
        )

        return Response(body, status=resp.status_code,
                       headers=response_headers, content_type=content_type)

    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
