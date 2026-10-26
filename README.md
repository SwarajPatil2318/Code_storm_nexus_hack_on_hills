# NEXUS

NEXUS runs bounded adversarial AI security evaluations. Separate Red and Blue
operators commit an attack suite and defence policy, approve the exact versions,
and execute Qwen through restricted Docker workloads and a Reference Monitor.
X-Ray shows authorized execution events; Proof Vault signs evaluation records
that an independent offline verifier can check.

Built for Hack in Hills — Bayora Problem 04. This is a Linux local-development
product, not a publicly exposed production installation.

## Requirements

- Ubuntu/Linux x86-64 with cgroup v2 and POSIX ACL support (`setfacl`).
- Python 3.12+, Node.js 22+ and npm.
- Docker Engine and Compose plugin, accessible as your non-root user at
  `/var/run/docker.sock`. Rootless/remote Docker and native Windows/macOS
  execution have not been qualified.
- About 16 GB host RAM recommended, several GB available during setup, and at
  least 10 GB free disk for dependencies, images, model and local database.
- Internet access for initial package, image and model downloads. No GPU or paid
  model API is required. PostgreSQL 17 runs inside Docker.

Use a short checkout path such as `$HOME/nexus`. The complete path to
`.runtime/ui-qa/control/provisioner.sock` must be shorter than 108 bytes.

Check prerequisites:

```sh
python3 --version
node --version
npm --version
docker info
docker compose version
command -v setfacl
stat -fc %T /sys/fs/cgroup
```

The last command should report `cgroup2fs`. Install missing prerequisites using
your operating system's procedures first. Do not run the launchers as root.

## Install a fresh download

Extract or clone into a short path and open a terminal there. Do not copy another
installation's `.runtime`, credentials, signing keys or database volumes.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r apps/api/requirements.runtime.lock
.venv/bin/python -m pip check
npm ci --ignore-scripts --no-audit --no-fund
.venv/bin/python scripts/nexus.py prepare-model
.venv/bin/python scripts/nexus.py setup
.venv/bin/python scripts/nexus.py start
.venv/bin/python scripts/nexus.py status
```

Model preparation downloads the fixed Qwen2.5-0.5B GGUF (approximately 491 MB) and
llama.cpp backend, verifies their pinned SHA-256 and sizes, and saves them under
`.runtime`. Weights are excluded from source. Review upstream licenses before
redistributing downloaded Qwen or llama.cpp artifacts.

Setup provisions an owned PostgreSQL volume, Alembic migrations, distinct database
identities, restricted images, fresh signing custody, random local account
passwords and a frontend build. No historical records or archives are imported.

Open **http://127.0.0.1:3000**. API readiness:
**http://127.0.0.1:8000/ready**. PostgreSQL binds to loopback port **55432**.
Do not expose these development defaults publicly.

### Accounts

| Role | Email | Purpose |
|---|---|---|
| Red | `red@nexus.local` | Author attacks and start approved evaluations |
| Blue | `blue@nexus.local` | Publish policies and approve exact commitments |
| Auditor | `auditor@nexus.local` | Inspect authorized records |
| Admin | `admin@nexus.local` | Manage identities; no confidential-content bypass |

Open `.runtime/ui-qa/credentials.env` privately for your generated passwords.
They are unique to this installation. The initializer also creates a synthetic
local test identity. Never publish private configuration or credentials.

### Alternative ports

Choose an unused instance name and three distinct unused ports. Repeat the same
options for **every** setup/start/status/stop command:

```sh
.venv/bin/python scripts/nexus.py setup --instance mydemo --web-port 3050 --api-port 8050 --database-port 55450
.venv/bin/python scripts/nexus.py start --instance mydemo --web-port 3050 --api-port 8050 --database-port 55450
```

An instance's source path and ownership are pinned. Do not move an initialized
directory or adopt another installation's resources.

## First evaluation

1. Sign in as Red in a normal browser and Blue in an Incognito window.
2. In Blue's Defence Vault, publish a policy and share its version reference with
   `red@nexus.local`. Input/output actions support ALLOW, TRANSFORM and BLOCK.
3. In Red's Attack Lab, author synthetic cases, choose a curated suite, or click
   **Load final four-case judge suite**. That button loads exact JSONL in
   **Advanced Campaign Setup**; click **Import immutable corpus** to save it.
4. Select the shared defence. For real advanced execution choose local Qwen,
   isolated Docker and STANDARD. Explicit MOCK mode does not run Qwen.
5. Create the campaign and commit its versions. Blue refreshes the approval inbox
   and approves the exact commitment. Sharing a policy alone is not approval.
6. Red seals and explicitly starts the test. The live dashboard opens at
   `/evaluations/<id>/live`. Evaluation controls show case results and released
   model output; X-Ray shows correlated events.
7. Check cleanup and credential revocation. In Proof Vault request signing,
   verify the receipt and export the authorized bundle.

The exact four-case corpus, policy and settings are in `examples/judge-suite/`.
Use four cases, concurrency 1, 128 output tokens, temperature 0, seed 42, context
2048 and a 300-second deadline. Results are actual observations, not guaranteed
demo outcomes. Run one real evaluation at a time and use synthetic data only.

## Stop and restart

```sh
.venv/bin/python scripts/nexus.py stop
.venv/bin/python scripts/nexus.py start
```

Stop refuses active native evaluations; wait for completion and cleanup first.
Only this instance's services stop. Database history, credentials and signing
custody persist. Keep the same instance/port options. Never use global Docker
cleanup or delete retained volumes to resolve a collision.

## Independent verification

```sh
node tools/nexus-verify/verify.mjs verify /path/to/bundle.json --keyring /path/to/trusted-public-keyring.json
```

The local public keyring is `.runtime/ui-qa/trust.json`; establish trust in it
independently. Bundled keys do not establish trust. Tampered signed exports must
fail verification. A valid signature checks committed bytes, not event truth,
model safety, host integrity, latestness or full hidden-history completeness.

## Source layout

```text
apps/web/             Next.js frontend and UI
apps/api/             FastAPI backend, migrations and dependency locks
services/orchestrator Trusted host provisioner and runtime controls
services/runtime/     Restricted workload and API image inputs
services/signing/     Restricted signing and custody components
infrastructure/       Isolated PostgreSQL Compose configuration
scripts/              Required setup, build and lifecycle helpers
packages/contracts/   OpenAPI snapshot and synthetic case library
examples/judge-suite/ Exact synthetic corpus, policy and settings
tools/nexus-verify/   Independent offline verifier
product-files.txt     Exact product-package source file allowlist
```

Internal initializer filenames remain because the supported launcher imports
them; they are setup dependencies, not bundled test suites. The product package
excludes tests, reports, recordings, local environments, keys, weights and backups.
Only this root README is included as Markdown.

## Security scope and troubleshooting

The API and tenant workloads receive no Docker socket. The trusted host
provisioner controls restricted workers. Docker shares a kernel; host
administrators, the provisioner, database and signer remain trusted. Managed CPU
separation does not establish exclusive-host ownership or eliminate timing
channels. Physical memory erasure and universal confidentiality are unproven.

A fresh installation has no historical experiment archives. Empty dedicated
assurance-study lists do not mean Qwen is unavailable. Inspect your evaluation's
dashboard, runtime, X-Ray and Proof Vault. Never seed historical successes.

- **Qwen unavailable:** finish preparation/setup and inspect the reason in the UI
  and private `.runtime/ui-qa` logs; do not silently substitute MOCK.
- **No Blue request:** commit in Red, use a policy owned by that Blue identity,
  and refresh the approval inbox.
- **Occupied port/namespace:** use a fresh instance and unused ports.
- **Socket path too long:** use a shorter fresh checkout before setup.
- **Missing evidence:** leave it visibly unavailable; signing does not create tests.

Same-host installation checks do not establish independent-host or production
qualification. Keep logs and private configuration off public issue reports.
