import argparse
import json
import os
import subprocess
import sys
import threading
import time
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class PipelineScheduler:
    def __init__(self, *, repo_dir: str, config_path: str, account: str, interval_seconds: int = 60):
        self.repo_dir = repo_dir
        self.config_path = config_path
        self.account = account
        self.interval_seconds = interval_seconds

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        t = threading.Thread(target=self._loop, name=f"pipeline:{self.account}", daemon=True)
        self._thread = t
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            started_at = time.time()
            self.run_once()
            elapsed = time.time() - started_at
            remaining = max(0.0, float(self.interval_seconds) - elapsed)
            if self._stop.wait(remaining):
                break

    def run_once(self) -> None:
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            cmd = [
                sys.executable,
                "run_pipeline.py",
                "--config",
                self.config_path,
                "--account",
                self.account,
            ]
            subprocess.run(cmd, cwd=self.repo_dir, check=False)
        finally:
            self._run_lock.release()


def _aes256cbc_decrypt_b64(*, b64_ciphertext: str, encrypt_key: str) -> str:
    key = encrypt_key.encode("utf-8")
    if len(key) != 32:
        raise ValueError("encrypt_key must be 32 bytes (32 chars)")
    iv = key[:16]
    ciphertext = base64.b64decode(b64_ciphertext)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def _aes256cbc_encrypt_b64(*, plaintext: str, encrypt_key: str) -> str:
    key = encrypt_key.encode("utf-8")
    if len(key) != 32:
        raise ValueError("encrypt_key must be 32 bytes (32 chars)")
    iv = key[:16]
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("utf-8")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_chunked_body(handler: BaseHTTPRequestHandler) -> bytes:
    # Minimal Transfer-Encoding: chunked reader for BaseHTTPRequestHandler.
    # Feishu validation may send chunked requests without Content-Length.
    out = bytearray()
    while True:
        line = handler.rfile.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            size = int(line.split(b";", 1)[0], 16)
        except Exception:
            raise ValueError(f"invalid_chunk_size_line: {line!r}")
        if size == 0:
            # Consume trailing headers after last chunk.
            while True:
                trailer = handler.rfile.readline()
                if not trailer or trailer in (b"\r\n", b"\n"):
                    return bytes(out)
        chunk = handler.rfile.read(size)
        out.extend(chunk)
        # Consume CRLF after each chunk.
        handler.rfile.read(2)
    return bytes(out)


def _maybe_encrypt_response(*, payload: Dict[str, Any], encrypt_key: str, use_encryption: bool) -> Dict[str, Any]:
    if not use_encryption:
        return payload
    plaintext = json.dumps(payload, ensure_ascii=False)
    return {"encrypt": _aes256cbc_encrypt_b64(plaintext=plaintext, encrypt_key=encrypt_key)}


def build_handler(*, verification_token: str, encrypt_key: str, scheduler: PipelineScheduler):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            # Some platform validations may probe the endpoint via GET.
            _json_response(self, 200, {"ok": True})

        def do_POST(self) -> None:
            print(f"[bot] POST {self.path}", file=sys.stderr)
            try:
                te = (self.headers.get("Transfer-Encoding") or "").strip().lower()
                if te == "chunked" and not self.headers.get("Content-Length"):
                    raw = _read_chunked_body(self)
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length)

                try:
                    print(
                        f"[bot] headers content-length={self.headers.get('Content-Length')} transfer-encoding={self.headers.get('Transfer-Encoding')} content-type={self.headers.get('Content-Type')}",
                        file=sys.stderr,
                    )
                    print(f"[bot] raw_len={len(raw)}", file=sys.stderr)
                    preview = raw[:500]
                    try:
                        preview_s = preview.decode("utf-8", errors="replace")
                    except Exception:
                        preview_s = repr(preview)
                    print(f"[bot] raw_preview={preview_s}", file=sys.stderr)
                except Exception:
                    pass
                data = json.loads(raw.decode("utf-8")) if raw else {}
                try:
                    print(f"[bot] parsed={data}", file=sys.stderr)
                except Exception:
                    pass
            except Exception:
                _json_response(self, 400, {"ok": False, "error": "invalid_json"})
                return

            # If event encryption is enabled, Feishu sends {"encrypt": "..."}.
            use_encryption = False
            if encrypt_key and isinstance(data, dict) and isinstance(data.get("encrypt"), str):
                use_encryption = True
                try:
                    plain_text = _aes256cbc_decrypt_b64(b64_ciphertext=data["encrypt"], encrypt_key=encrypt_key)
                    data = json.loads(plain_text)
                except Exception as e:
                    _json_response(self, 400, {"ok": False, "error": f"decrypt_failed: {e}"})
                    return

            # Helpful for diagnosing Feishu callback verification issues.
            try:
                print(f"[bot] body={data}", file=sys.stderr)
            except Exception:
                pass

            # Feishu URL verification expects us to echo back the challenge.
            # Be tolerant here: return challenge even if token is missing/mismatched,
            # otherwise Feishu reports "Challenge code没有返回".
            if data.get("type") == "url_verification":
                ch = data.get("challenge", "")
                if use_encryption:
                    # Some Feishu validations are strict about returning a plaintext `challenge`.
                    # To maximize compatibility, return both plaintext and encrypted forms.
                    payload = {
                        "challenge": ch,
                        "encrypt": _aes256cbc_encrypt_b64(
                            plaintext=json.dumps({"challenge": ch}, ensure_ascii=False),
                            encrypt_key=encrypt_key,
                        ),
                    }
                else:
                    payload = {"challenge": ch}
                _json_response(self, 200, payload)
                return

            token = data.get("token")
            if verification_token and token != verification_token:
                payload = _maybe_encrypt_response(
                    payload={"ok": False, "error": "invalid_token"},
                    encrypt_key=encrypt_key,
                    use_encryption=use_encryption,
                )
                _json_response(self, 401, payload)
                return

            event = (data.get("event") or {})
            msg = (event.get("message") or {})
            content_raw = msg.get("content") or "{}"
            try:
                content_obj = json.loads(content_raw)
            except Exception:
                content_obj = {}
            text = (content_obj.get("text") or "").strip()

            if text == f"{scheduler.account}1":
                scheduler.start()
                payload = _maybe_encrypt_response(
                    payload={"ok": True, "running": True},
                    encrypt_key=encrypt_key,
                    use_encryption=use_encryption,
                )
                _json_response(self, 200, payload)
                return
            if text == f"{scheduler.account}2":
                scheduler.stop()
                payload = _maybe_encrypt_response(
                    payload={"ok": True, "running": False},
                    encrypt_key=encrypt_key,
                    use_encryption=use_encryption,
                )
                _json_response(self, 200, payload)
                return

            payload = _maybe_encrypt_response(
                payload={"ok": True, "ignored": True},
                encrypt_key=encrypt_key,
                use_encryption=use_encryption,
            )
            _json_response(self, 200, payload)

        def do_PUT(self) -> None:
            _json_response(self, 405, {"ok": False, "error": "method_not_allowed"})

        def do_DELETE(self) -> None:
            _json_response(self, 405, {"ok": False, "error": "method_not_allowed"})

    return Handler


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--account", default="蓝精灵")
    p.add_argument("--interval-seconds", type=int, default=60)
    args = p.parse_args()

    cfg = load_json(args.config)
    verification_token = ((cfg.get("bot") or {}).get("verification_token") or "").strip()
    encrypt_key = ((cfg.get("bot") or {}).get("encrypt_key") or "").strip()

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    scheduler = PipelineScheduler(
        repo_dir=repo_dir,
        config_path=args.config,
        account=args.account,
        interval_seconds=args.interval_seconds,
    )

    handler_cls = build_handler(verification_token=verification_token, encrypt_key=encrypt_key, scheduler=scheduler)
    httpd = HTTPServer((args.host, args.port), handler_cls)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
