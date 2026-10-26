"""Fixed trusted data-plane gateway. No IP forwarding or caller-selected URLs."""

import http.client
import json
import os
import socket
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/runtime")
from wire import LIMIT, canonical, fields, frame, sign, validate

SOCKET = "/tmp/nexus-gateway.sock"


def client():
    data = sys.stdin.buffer.readline(LIMIT + 1)
    if len(data) > LIMIT:
        raise SystemExit("CONTROL_BOUND")
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(4)
        connection.connect(SOCKET)
        connection.sendall(data.rstrip(b"\n") + b"\n")
        result = connection.makefile("rb").readline(LIMIT + 1)
        sys.stdout.buffer.write(result)


def serve():
    config = json.loads(sys.stdin.buffer.readline(LIMIT + 1))
    seen, submissions = set(), {}
    lock = threading.Lock()

    def call(role, action, payload):
        peer = config["domains"][role]
        value = frame(config, "broker", action, payload)
        connection = http.client.HTTPConnection(peer["ip"], 8080, timeout=2)
        try:
            connection.request(
                "POST",
                "/" + action,
                canonical(value),
                {
                    "Content-Type": "application/json",
                    "X-Nexus-Signature": sign(peer["key_in"], value),
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("WORKLOAD_REJECTED")
            result = json.loads(response.read(LIMIT + 1))
            if result["frame"].get("reply_to") != value["nonce"]:
                raise ValueError("RESPONSE_SCOPE_REJECTED")
            with lock:
                return validate(
                    config,
                    result["frame"],
                    result["signature"],
                    peer["key_out"],
                    role,
                    {action},
                    seen,
                )
        finally:
            connection.close()

    class Ingress(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    self.server.domain != "red"
                    or self.path != "/submit"
                    or not 0 < length <= LIMIT
                ):
                    raise ValueError("INGRESS_REJECTED")
                value = json.loads(self.rfile.read(length))
                with lock:
                    payload = validate(
                        config,
                        value,
                        self.headers.get("X-Nexus-Signature", ""),
                        config["domains"]["red"]["key_out"],
                        "red",
                        {"submit"},
                        seen,
                    )
                    fields(payload, {"case", "index", "correlation_id"})
                    if (
                        len(submissions) >= 20
                        or payload["correlation_id"] in submissions
                    ):
                        raise ValueError("SUBMISSION_BOUND")
                    submissions[payload["correlation_id"]] = payload
                reply = frame(
                    config,
                    "broker",
                    "submit",
                    {"accepted": True},
                    reply_to=value["nonce"],
                )
                body = canonical(
                    {
                        "frame": reply,
                        "signature": sign(config["domains"]["red"]["key_in"], reply),
                    }
                )
                self.send_response(200)
            except (ValueError, KeyError, TypeError):
                body = b'{"error":"REQUEST_REJECTED"}'
                self.send_response(403)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Control(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                raw = self.rfile.readline(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError("CONTROL_BOUND")
                value = json.loads(raw)
                fields(value, {"operation", "role", "payload"})
                operation, role, payload = (
                    value["operation"],
                    value["role"],
                    value["payload"],
                )
                if operation == "auth_probe":
                    fields(payload, {"kind"})
                    variant = payload["kind"]
                    if role not in {"red", "blue", "model"} or variant not in {
                        "wrong_key",
                        "cross_scope",
                        "stale",
                        "replay",
                    }:
                        raise ValueError("PROBE_REJECTED")
                    positive = call(role, "health", {}).get("ready") is True
                    peer = config["domains"][role]
                    value = frame(config, "broker", "health", {})
                    if variant == "cross_scope":
                        value["evaluation_id"] = "00000000-0000-4000-8000-000000000000"
                    if variant == "stale":
                        value["timestamp"] -= 60
                    signature = sign(
                        "0" * 64 if variant == "wrong_key" else peer["key_in"], value
                    )

                    def attempt():
                        connection = http.client.HTTPConnection(
                            peer["ip"], 8080, timeout=2
                        )
                        try:
                            connection.request(
                                "POST",
                                "/health",
                                canonical(value),
                                {"X-Nexus-Signature": signature},
                            )
                            response = connection.getresponse()
                            response.read(LIMIT + 1)
                            return response.status
                        finally:
                            connection.close()

                    first = attempt()
                    rejected = (
                        attempt() if variant == "replay" and first == 200 else first
                    )
                    self.wfile.write(
                        canonical(
                            {
                                "ok": True,
                                "result": {
                                    "positive": positive,
                                    "rejected": rejected == 403,
                                    "status": rejected,
                                },
                            }
                        )
                        + b"\n"
                    )
                    return
                allowed = {
                    "health": {"red", "blue", "model"},
                    "probe": {"red", "blue", "model"},
                    "next": {"red"},
                    "deliver": {"red"},
                    "input": {"blue"},
                    "output": {"blue"},
                    "infer": {"model"},
                    "infer_start": {"model"},
                    "infer_poll": {"model"},
                }
                if operation not in allowed or role not in allowed[operation]:
                    raise ValueError("CONTROL_REJECTED")
                result = call(role, operation, payload)
                if operation == "next":
                    with lock:
                        accepted = submissions.pop(payload["correlation_id"], None)
                    if (
                        not accepted
                        or accepted["case"] != result
                        or accepted["index"] != payload["index"]
                    ):
                        raise ValueError("SUBMISSION_NOT_AUTHENTICATED")
                body = {"ok": True, "result": result}
            except (ValueError, KeyError, TypeError, OSError):
                body = {"ok": False, "error": "GATEWAY_REQUEST_FAILED"}
            self.wfile.write(canonical(body) + b"\n")

    for role, address in config["interfaces"].items():
        http_server = ThreadingHTTPServer((address, 8080), Ingress)
        http_server.domain = role
        threading.Thread(target=http_server.serve_forever, daemon=True).start()
    server = socketserver.ThreadingUnixStreamServer(SOCKET, Control)
    os.chmod(SOCKET, 0o600)
    server.serve_forever()


if __name__ == "__main__":
    client() if len(sys.argv) == 2 and sys.argv[1] == "control" else serve()
