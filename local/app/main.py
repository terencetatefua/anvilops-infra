"""
anvil-app — minimal demo workload for the pilot.

Backend swap via AI_BACKEND env var:
    AI_BACKEND=ollama   -> OLLAMA_URL (default http://host.docker.internal:11434)
    AI_BACKEND=bedrock  -> uses boto3 + BEDROCK_MODEL_ID
"""
import os
import json
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

AI_BACKEND   = os.getenv("AI_BACKEND", "ollama").lower()
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

INDEX_HTML = Path(__file__).parent.joinpath("index.html").read_text(encoding="utf-8")


def ask_ollama(messages: list) -> str:
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("message", {}).get("content", "").strip()


def ask_bedrock(messages: list) -> str:
    import boto3
    client = boto3.client("bedrock-runtime")
    bedrock_messages = [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in messages
    ]
    resp = client.converse(modelId=BEDROCK_MODEL_ID, messages=bedrock_messages)
    return resp["output"]["message"]["content"][0]["text"].strip()


def ask(prompt: str, history: list) -> str:
    messages = list(history) + [{"role": "user", "content": prompt}]
    return ask_bedrock(messages) if AI_BACKEND == "bedrock" else ask_ollama(messages)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _send_html(self, code, html):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_GET(self):
        if self.path == "/healthz":
            return self._send_json(200, {"status": "ok", "backend": AI_BACKEND})
        if self.path == "/":
            return self._send_html(200, INDEX_HTML)
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            return self._send_json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            prompt = body.get("prompt", "")
            history = body.get("history", [])
            if not prompt:
                return self._send_json(400, {"error": "missing 'prompt'"})
            self._send_json(200, {"backend": AI_BACKEND, "response": ask(prompt, history)})
        except Exception as e:
            self._send_json(502, {"error": f"{AI_BACKEND} backend failed", "detail": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"anvil-app listening on :{port}  (AI_BACKEND={AI_BACKEND})", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
