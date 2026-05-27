"""
anvil-app — minimal demo workload for the pilot.

The point of this file is the AI ABSTRACTION: the app talks to one interface,
and the backend is chosen by env var. Locally that's Ollama; on AWS you flip
AI_BACKEND=bedrock and the rest of the app is untouched.

    AI_BACKEND=ollama   -> OLLAMA_URL (default http://host.docker.internal:11434)
    AI_BACKEND=bedrock  -> uses boto3 + BEDROCK_MODEL_ID (wired on the AWS move)
"""
import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

AI_BACKEND   = os.getenv("AI_BACKEND", "ollama").lower()
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")


def ask_ollama(prompt: str) -> str:
    body = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("response", "").strip()


def ask_bedrock(prompt: str) -> str:
    # Imported lazily so the local image needs no AWS deps.
    import boto3
    client = boto3.client("bedrock-runtime")
    resp = client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


def ask(prompt: str) -> str:
    return ask_bedrock(prompt) if AI_BACKEND == "bedrock" else ask_ollama(prompt)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {"status": "ok", "backend": AI_BACKEND})
        if self.path == "/":
            return self._send(200, {"app": "anvil-app", "backend": AI_BACKEND,
                                    "try": "POST /chat {\"prompt\": \"hello\"}"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            prompt = json.loads(self.rfile.read(length) or b"{}").get("prompt", "")
            if not prompt:
                return self._send(400, {"error": "missing 'prompt'"})
            self._send(200, {"backend": AI_BACKEND, "response": ask(prompt)})
        except Exception as e:  # noqa: BLE001 - surface backend errors to caller
            self._send(502, {"error": f"{AI_BACKEND} backend failed", "detail": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"anvil-app listening on :{port}  (AI_BACKEND={AI_BACKEND})", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
