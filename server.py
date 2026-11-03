"""Northline voice demo. Run: python server.py  then open http://127.0.0.1:8787"""

import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bank

# Free Groq tier, about 1000 tokens/s. Core banking never calls it.
# https://console.groq.com/keys
MODEL = "openai/gpt-oss-20b"
HOST = "127.0.0.1"
PORT = 8787
ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
LOCK = threading.Lock()
SESSIONS = {}

SYSTEM = (
    "Northline phone agent for Alex Morgan. One spoken sentence. No markdown or lists. "
    "FACTS are the only numbers you may say. FACTS override earlier turns. "
    "You cannot transfer, freeze, or pay anyone. If they want that, tell them to say "
    "what's my balance, recent activity, move 50 dollars to savings, or freeze my card. "
    "If you don't know, say you can help with balances, recent activity, transfers "
    "between their two accounts, or freezing the card.\nFACTS: {facts}"
)
FALLBACK = "I can help with a balance, recent activity, a transfer, or freezing your card."
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


def load_key():
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"].strip().strip('"').strip("'")
    env = ROOT / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "GROQ_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def session_for(cookie_header):
    found = re.search(r"(?:^|;\s*)nl=([0-9a-f]{16})\b", cookie_header or "")
    with LOCK:
        if found and found.group(1) in SESSIONS:
            return SESSIONS[found.group(1)], None
        sid = secrets.token_hex(8)
        SESSIONS[sid] = {"bank": bank.create_bank(), "history": [], "lock": threading.Lock()}
        while len(SESSIONS) > 40:
            SESSIONS.pop(next(iter(SESSIONS)))
        return SESSIONS[sid], f"nl={sid}; Path=/; HttpOnly; SameSite=Lax"


def bundle(sess, speech, source, ms):
    return {
        "speech": speech,
        "source": source,
        "ms": ms,
        "state": bank.public_state(sess["bank"]),
        "llm": bool(load_key()),
        "model": MODEL,
    }


def _clean(text):
    text = re.sub(r"<think>[\s\S]*?</think>", " ", text, flags=re.I)
    text = re.sub(r"<think>[\s\S]*", " ", text, flags=re.I)
    text = re.sub(r"[*_#`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentence(buf, final):
    buf = _clean(buf)
    if not buf:
        return None
    shielded = re.sub(r"(\d[\d,]*)\.(\d{2})\b", r"\1·\2", buf)
    ready = [part.strip() for part in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", shielded)]
    done = [part.replace("·", ".") for part in ready if part.endswith((".", "!", "?"))]
    if done and len(done[0]) > 25:
        return done[0]
    if len(done) >= 2:
        return f"{done[0]} {done[1]}"
    if final:
        return buf[:280]
    return None


def ask_model(text, facts, history):
    key = load_key()
    if not key:
        return FALLBACK, "fallback"
    messages = [{"role": "system", "content": SYSTEM.replace("{facts}", facts[:500])}]
    messages.extend(history[-4:])
    messages.append({"role": "user", "content": text[:300]})
    body = {
        "model": MODEL,
        "temperature": 0.4,
        "max_completion_tokens": 256,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "stream": True,
        "messages": messages,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    buf = ""
    speech = None
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if not piece:
                    continue
                buf += piece
                if "<think" in buf.lower() and "</think>" not in buf.lower():
                    continue
                speech = _sentence(buf, final=False)
                if speech:
                    break
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"groq error: {exc}")
        return FALLBACK, "fallback"
    speech = speech or _sentence(buf, final=True)
    if not speech:
        return FALLBACK, "fallback"
    return bank.scrub_amounts(speech, facts), "model"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s %s" % (self.command, self.path.split("?", 1)[0]))

    def _json(self, code, obj, cookie=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _static(self, url_path):
        if url_path == "/":
            url_path = "/index.html"
        file = (PUBLIC / url_path.lstrip("/")).resolve()
        if not str(file).startswith(str(PUBLIC.resolve())) or not file.is_file():
            self.send_error(404)
            return
        data = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(file.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            sess, cookie = session_for(self.headers.get("Cookie"))
            self._json(200, bundle(sess, "", "bank", 0), cookie)
            return
        self._static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        sess, cookie = session_for(self.headers.get("Cookie"))
        if path == "/api/reset":
            with sess["lock"]:
                sess["bank"] = bank.create_bank()
                sess["history"] = []
                payload = bundle(sess, "", "bank", 0)
            self._json(200, payload, cookie)
            return
        if path != "/api/turn":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length > 8000:
            self._json(413, bundle(sess, "That was too long. Try a shorter question.", "bank", 0), cookie)
            return
        try:
            incoming = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            incoming = {}
        text = incoming.get("text", "")
        text = text.strip()[:300] if isinstance(text, str) else ""
        started = time.perf_counter()
        with sess["lock"]:
            result = bank.handle(sess["bank"], text)
            if result["hit"]:
                ms = int((time.perf_counter() - started) * 1000)
                payload = bundle(sess, result["speech"], "bank", ms)
                self._json(200, payload, cookie)
                return
            facts = bank.snapshot(sess["bank"])
            history = list(sess["history"])
        speech, source = ask_model(text, facts, history)
        ms = int((time.perf_counter() - started) * 1000)
        with sess["lock"]:
            if source == "model":
                sess["history"] = (history + [
                    {"role": "user", "content": text[:160]},
                    {"role": "assistant", "content": speech[:160]},
                ])[-4:]
            payload = bundle(sess, speech, source, ms)
        self._json(200, payload, cookie)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    key = "loaded" if load_key() else "missing (balances and transfers still work)"
    print(f"Northline voice demo  http://{HOST}:{PORT}")
    print(f"Model {MODEL}  key {key}")
    if not load_key():
        print("Free key: https://console.groq.com/keys  — save it as GROQ_API_KEY in .env")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
