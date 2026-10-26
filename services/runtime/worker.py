"""Fixed deterministic network workloads; no uploaded code or arbitrary command dispatch."""

import errno
import hashlib
import http.client
import json
import os
import pathlib
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/runtime")
from providers import ProviderError
from wire import LIMIT, canonical, fields, frame, sign, text, validate

ROLE = os.environ["NEXUS_WORKLOAD_ROLE"]
CONFIG = json.loads(sys.stdin.buffer.readline(LIMIT + 1))
if set(CONFIG) - {"execution"} != {
    "evaluation_id",
    "expires_at",
    "key_in",
    "key_out",
    "artifact",
    "digest",
    "broker",
}:
    raise SystemExit("CONFIGURATION_REJECTED")
if hashlib.sha256(canonical(CONFIG["artifact"])).hexdigest() != CONFIG["digest"]:
    raise SystemExit("DIGEST_REJECTED")
SEEN = set()
LOCK = threading.Lock()
MODEL_LOCK = threading.Lock()
JOBS = {}
PROVIDER = None
if ROLE == "model" and CONFIG["artifact"].get("schema_version") == "model-manifest-v1":
    from providers import DeterministicMockProvider, LocalModelProvider

    PROVIDER = (
        LocalModelProvider
        if CONFIG["artifact"]["provider"] == "local"
        else DeterministicMockProvider
    )(CONFIG["artifact"])
SAFE = "Mock response: request handled."
WITHHELD = "Response withheld."
if ROLE == "blue":
    pathlib.Path("/tmp/blue-only-secret").write_text("SYNTHETIC_BLUE_ONLY_CANARY")
    os.chmod("/tmp/blue-only-secret", 0o600)


def request_broker(payload):
    value = frame(CONFIG, ROLE, "submit", payload)
    connection = http.client.HTTPConnection(CONFIG["broker"], 8080, timeout=2)
    try:
        connection.request(
            "POST",
            "/submit",
            canonical(value),
            {
                "X-Nexus-Signature": sign(CONFIG["key_out"], value),
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("BROKER_REJECTED")
        # Authenticate the reply with the inbound-only broker credential.
        data = json.loads(response.read(LIMIT + 1))
        if data["frame"].get("reply_to") != value["nonce"]:
            raise ValueError("RESPONSE_SCOPE_REJECTED")
        validate(
            CONFIG,
            data["frame"],
            data["signature"],
            CONFIG["key_in"],
            "broker",
            {"submit"},
            SEEN,
        )
    finally:
        connection.close()


def health():
    status = pathlib.Path("/proc/self/status").read_text().splitlines()
    cgroups = {}
    for name in ("memory.max", "pids.max", "cpu.max", "cpu.stat", "memory.events"):
        path = pathlib.Path("/sys/fs/cgroup") / name
        cgroups[name] = path.read_text().strip() if path.exists() else "UNSUPPORTED"
    return {
        "ready": not PROVIDER
        or not hasattr(PROVIDER, "process")
        or PROVIDER.process.poll() is None,
        "uid": os.getuid(),
        "security": [
            s for s in status if s.startswith(("NoNewPrivs:", "CapEff:", "Seccomp:"))
        ],
        "cgroups": cgroups,
        "default_route": any(
            line.split()[1] == "00000000"
            for line in pathlib.Path("/proc/net/route").read_text().splitlines()[1:]
        ),
        **(
            {
                "provider": PROVIDER.label,
                "load_duration_ms": PROVIDER.load_duration_ms,
                "readiness_tokens": getattr(PROVIDER, "readiness_tokens", None),
            }
            if PROVIDER
            else {}
        ),
    }


def inference_job(job_id, payload):
    from providers import ProviderError, validate_messages

    started = time.monotonic()
    acquired = False
    try:
        validate_messages(payload["messages"])
        acquired = MODEL_LOCK.acquire(timeout=payload["timeout_ms"] / 1000)
        remaining = payload["timeout_ms"] - int((time.monotonic() - started) * 1000)
        if not acquired or remaining < 20:
            raise TimeoutError("MODEL_TIMEOUT")
        with LOCK:
            JOBS[job_id] = {"done": False, "started": True}
        result = PROVIDER.infer(payload["messages"], remaining)
    except TimeoutError:
        result = {"error": "MODEL_TIMEOUT"}
    except ProviderError as error:
        result = {"error": str(error)}
    except Exception:  # noqa: BLE001 - sanitize worker-thread failures without disclosing payloads
        result = {"error": "MODEL_EXECUTION_ERROR"}
    finally:
        if acquired:
            MODEL_LOCK.release()
    with LOCK:
        JOBS[job_id] = {"done": True, "result": result}


def probe(payload):
    fields(payload, {"kind", "target", "port"})
    if payload["kind"] == "tcp":
        # Trusted gateway supplies only discovered controlled test targets; no public probe endpoint.
        socket.inet_aton(payload["target"])
        if type(payload["port"]) is not int or not 1 <= payload["port"] <= 65535:
            raise ValueError("PROBE_REJECTED")
        with socket.socket() as client:
            client.settimeout(0.35)
            try:
                result = client.connect_ex((payload["target"], payload["port"]))
            except TimeoutError:
                result = errno.ETIMEDOUT
        return {"errno": result, "connected": result == 0}
    if payload["kind"] == "socket":
        return {
            "present": any(
                pathlib.Path(p).exists()
                for p in ("/var/run/docker.sock", "/run/docker.sock")
            )
        }
    if payload["kind"] == "file":
        return {"present": pathlib.Path("/tmp/blue-only-secret").exists()}
    if payload["kind"] == "cpu":

        def throttles():
            lines = pathlib.Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines()
            return int(
                next(
                    line.split()[1]
                    for line in lines
                    if line.startswith("nr_throttled ")
                )
            )

        before = throttles()
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            hashlib.sha256(b"controlled-cpu-probe" * 100).digest()
        return {"throttled_periods": throttles() - before}
    if payload["kind"] == "resource":
        children, exhausted = [], False
        try:
            for _ in range(40):
                try:
                    pid = os.fork()
                except OSError as error:
                    exhausted = error.errno == errno.EAGAIN
                    break
                if pid == 0:
                    time.sleep(3)
                    os._exit(0)
                children.append(pid)
        finally:
            for pid in children:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
                os.waitpid(pid, 0)
        return {"pids_eagain": exhausted, "cgroups": health()["cgroups"]}
    raise ValueError("PROBE_REJECTED")


def dispatch(action, payload):
    if action == "health":
        fields(payload, set())
        return health()
    if action == "probe":
        return probe(payload)
    if ROLE == "red" and action == "next":
        fields(payload, {"index", "correlation_id"})
        if type(payload["index"]) is not int or not 0 <= payload["index"] < len(
            CONFIG["artifact"]["cases"]
        ):
            raise ValueError("INDEX_REJECTED")
        case = CONFIG["artifact"]["cases"][payload["index"]]
        request_broker(
            {
                "case": case,
                "index": payload["index"],
                "correlation_id": payload["correlation_id"],
            }
        )
        return case
    if ROLE == "red" and action == "deliver":
        fields(payload, {"kind", "outcome", "response"})
        if payload["kind"] == "campaign_release":
            if payload["outcome"] not in {"released", "withheld"}:
                raise ValueError("RELEASE_REJECTED")
            text(payload["response"])
            if payload["outcome"] == "withheld" and payload["response"] != WITHHELD:
                raise ValueError("RELEASE_REJECTED")
            return {"received": True}
        if payload["kind"] != "release" or (
            payload["outcome"],
            payload["response"],
        ) not in {("released", SAFE), ("withheld", WITHHELD)}:
            raise ValueError("RELEASE_REJECTED")
        return {"received": True}
    if ROLE == "blue" and action in {"input", "output"}:
        fields(payload, {"text", "input_approved"})
        value = text(payload["text"])
        if type(payload["input_approved"]) is not bool:
            raise ValueError("GUARD_REJECTED")
        if CONFIG["artifact"].get("schema_version") == "blue-policy-v1":
            from evaluation_rules import guard_input, guard_output

            arm = CONFIG.get("execution", {}).get("arm", "defended")
            return (guard_input if action == "input" else guard_output)(
                value, CONFIG["artifact"], arm
            )
        terms = CONFIG["artifact"]["blocked_terms"]
        approved = not any(t.casefold() in value.casefold() for t in terms)
        approved = approved and (
            not CONFIG["artifact"]["block_input"]
            if action == "input"
            else payload["input_approved"] and value == SAFE
        )
        return {
            "approved": approved,
            "text": value if approved else ("" if action == "input" else WITHHELD),
        }
    if ROLE == "model" and action == "infer_start" and PROVIDER:
        fields(payload, {"job_id", "messages", "timeout_ms"})
        job_id = str(uuid.UUID(payload["job_id"]))
        from providers import validate_messages

        validate_messages(payload["messages"])
        if (
            type(payload["timeout_ms"]) is not int
            or not 20 <= payload["timeout_ms"] <= 60000
        ):
            raise ValueError("TIMEOUT_REJECTED")
        with LOCK:
            if job_id in JOBS or len(JOBS) >= 2:
                raise ValueError("INFERENCE_CAPACITY")
            JOBS[job_id] = {"done": False}
        threading.Thread(
            target=inference_job, args=(job_id, payload), daemon=True
        ).start()
        return {"accepted": True}
    if ROLE == "model" and action == "infer_poll" and PROVIDER:
        fields(payload, {"job_id"})
        with LOCK:
            job = JOBS.get(str(uuid.UUID(payload["job_id"])))
            if job is None:
                raise ValueError("UNKNOWN_JOB")
            if job["done"]:
                JOBS.pop(str(uuid.UUID(payload["job_id"])))
            return job
    if ROLE == "model" and action == "infer" and not PROVIDER:
        fields(payload, {"text", "timeout_ms"})
        text(payload["text"])
        if (
            type(payload["timeout_ms"]) is not int
            or not 20 <= payload["timeout_ms"] <= 1000
        ):
            raise ValueError("TIMEOUT_REJECTED")
        mode = CONFIG["artifact"]["mode"]
        if mode == "error":
            return {"error": "MOCK_MODEL_ERROR"}
        if mode == "timeout":
            time.sleep(payload["timeout_ms"] / 1000)
            return {"error": "MOCK_MODEL_TIMEOUT"}
        return {"text": "CANARY_PRIVATE" if mode == "canary" else SAFE}
    raise ValueError("ACTION_REJECTED")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= LIMIT:
                raise ValueError("MESSAGE_BOUND")
            value = json.loads(self.rfile.read(length))
            with LOCK:
                payload = validate(
                    CONFIG,
                    value,
                    self.headers.get("X-Nexus-Signature", ""),
                    CONFIG["key_in"],
                    "broker",
                    {
                        "health",
                        "probe",
                        *(
                            {"next", "deliver"}
                            if ROLE == "red"
                            else {"input", "output"}
                            if ROLE == "blue"
                            else {"infer", "infer_start", "infer_poll"}
                        ),
                    },
                    SEEN,
                )
            if self.path != "/" + value["action"]:
                raise ValueError("PATH_REJECTED")
            result = dispatch(value["action"], payload)
            reply = frame(
                CONFIG, ROLE, value["action"], result, reply_to=value["nonce"]
            )
            body = canonical(
                {"frame": reply, "signature": sign(CONFIG["key_out"], reply)}
            )
            self.send_response(200)
        except (ValueError, KeyError, TypeError, OSError, ProviderError):
            body = b'{"error":"REQUEST_REJECTED"}'
            self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
