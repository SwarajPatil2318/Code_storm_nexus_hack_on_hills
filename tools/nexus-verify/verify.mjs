#!/usr/bin/env node
// Independent implementation. Imports only Node standard libraries; no NEXUS code.
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { createHash, createPublicKey, verify as verifySignature } from "node:crypto";
const MAX = 8 * 1024 * 1024,
  LIMIT = 8192;
const NAMES = ["manifest.json", "events.json", "artifacts.json", "results.json"];
const HEX = /^[a-f0-9]{64}$/,
  UUID = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/;
const PROFILE = ["INTERNAL", "RED_OPERATOR", "BLUE_OPERATOR", "AUDITOR"];
function requireThat(test) {
  if (!test) throw Error("REJECTED");
}
function object(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}
function keys(v, names) {
  requireThat(object(v) && Object.keys(v).sort().join("\0") === [...names].sort().join("\0"));
}
function text(v, max = MAX) {
  requireThat(typeof v === "string" && v.length <= max);
  for (const c of v) {
    const cp = c.codePointAt(0);
    requireThat(cp < 0xd800 || cp > 0xdfff);
  }
}
function timestamp(v) {
  text(v, 27);
  requireThat(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v) && Number(v.slice(0, 4)) > 0);
  requireThat(new Date(v).toISOString() === v.slice(0, 23) + "Z");
}
export function canonical(v, depth = 0) {
  requireThat(depth <= 32);
  if (v === null || typeof v === "boolean") return JSON.stringify(v);
  if (typeof v === "string") {
    text(v);
    return JSON.stringify(v);
  }
  if (typeof v === "number") {
    requireThat(Number.isSafeInteger(v));
    return String(v);
  }
  if (Array.isArray(v)) return "[" + v.map((x) => canonical(x, depth + 1)).join(",") + "]";
  requireThat(object(v));
  return (
    "{" +
    Object.keys(v)
      .sort()
      .map((k) => canonical(k, depth + 1) + ":" + canonical(v[k], depth + 1))
      .join(",") +
    "}"
  );
}
const bytes = (v) => Buffer.from(canonical(v), "utf8");
const sha = (v) => createHash("sha256").update(v).digest("hex");
export const digest = (kind, v) =>
  sha(Buffer.concat([Buffer.from("NEXUS-PROOF-V1\0" + kind + "\0", "ascii"), bytes(v)]));
function parse(raw) {
  requireThat(raw.length <= MAX);
  const string = new TextDecoder("utf-8", { fatal: true }).decode(raw);
  const value = JSON.parse(string);
  requireThat(canonical(value) === string);
  return value;
}
function binary(s) {
  text(s, MAX);
  requireThat(
    s.length % 4 === 0 &&
      /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(s),
  );
  const b = Buffer.from(s, "base64");
  requireThat(b.toString("base64") === s);
  return b;
}
export function keyId(pem) {
  text(pem, 160);
  requireThat(pem.startsWith("-----BEGIN PUBLIC KEY-----\n"));
  const key = createPublicKey(pem);
  requireThat(key.asymmetricKeyType === "ed25519");
  return sha(key.export({ type: "spki", format: "der" }));
}
function chain(c) {
  keys(c, ["genesis", "terminal", "count", "first", "last", "source_sequences"]);
  requireThat(
    HEX.test(c.genesis) &&
      HEX.test(c.terminal) &&
      Number.isSafeInteger(c.count) &&
      c.count >= 0 &&
      c.count <= LIMIT &&
      c.first === (c.count ? 1 : 0) &&
      c.last === c.count &&
      Array.isArray(c.source_sequences) &&
      c.source_sequences.length === c.count,
  );
}
function scoped(p) {
  for (const k of ["evaluation_id", "snapshot_id"]) requireThat(UUID.test(p[k]));
  requireThat(
    PROFILE.includes(p.profile) &&
      ["COMPLETED", "FAILED", "CANCELLED", "DESTROYED"].includes(p.terminal_status) &&
      ["VERIFIED", "FAILED", "PENDING", "NOT_STARTED", "IN_PROCESS_ONLY"].includes(p.cleanup),
  );
  requireThat(typeof p.retrospective === "boolean");
  const internal = p.profile === "INTERNAL";
  requireThat(
    p.coverage === (internal ? "FULL_INTERNAL_SNAPSHOT" : "AUTHORIZED_PROJECTION_ONLY") &&
      (internal ? p.subject_id === null : UUID.test(p.subject_id)),
  );
  chain(p.chain);
}
export function verifyBundle(raw, trust = {}) {
  let category = "FORMAT",
    signatureValid = false;
  try {
    const b = parse(raw);
    if (!object(b) || b.format !== "nexus-proof-bundle-v1")
      return {
        status: "UNSUPPORTED_FORMAT",
        category: "FORMAT",
        signature_valid: false,
        signer_trusted: false,
      };
    keys(b, ["format", "receipt", "files"]);
    keys(b.receipt, ["payload", "signature", "public_key"]);
    const p = b.receipt.payload;
    if (p?.format !== "nexus-receipt-v1")
      return {
        status: "UNSUPPORTED_FORMAT",
        category: "FORMAT",
        signature_valid: false,
        signer_trusted: false,
      };
    keys(p, [
      "format",
      "key_id",
      "signed_at",
      "snapshot_id",
      "evaluation_id",
      "profile",
      "subject_id",
      "manifest_digest",
      "chain",
      "files",
      "terminal_status",
      "cleanup",
      "retrospective",
      "coverage",
    ]);
    scoped(p);
    timestamp(p.signed_at);
    requireThat(HEX.test(p.key_id) && HEX.test(p.manifest_digest));
    if (!Array.isArray(b.files) || b.files.length < 4)
      return {
        status: "INCOMPLETE",
        category: "FILES",
        signature_valid: false,
        signer_trusted: false,
      };
    requireThat(b.files.length === 4 && Array.isArray(p.files) && p.files.length === 4);
    for (let i = 0; i < 4; i++) {
      keys(b.files[i], ["name", "content"]);
      keys(p.files[i], ["name", "sha256", "size"]);
      requireThat(
        b.files[i].name === NAMES[i] &&
          p.files[i].name === NAMES[i] &&
          HEX.test(p.files[i].sha256) &&
          Number.isSafeInteger(p.files[i].size) &&
          p.files[i].size >= 0 &&
          p.files[i].size <= MAX,
      );
    }
    category = "SIGNATURE";
    requireThat(keyId(b.receipt.public_key) === p.key_id);
    const sig = binary(b.receipt.signature);
    requireThat(
      sig.length === 64 &&
        verifySignature(
          null,
          Buffer.concat([Buffer.from("NEXUS-ED25519-RECEIPT-V1\0"), bytes(p)]),
          createPublicKey(b.receipt.public_key),
          sig,
        ),
    );
    signatureValid = true;
    category = "FILE_INTEGRITY";
    const values = b.files.map((f, i) => {
      const content = binary(f.content);
      requireThat(content.length === p.files[i].size && sha(content) === p.files[i].sha256);
      return parse(content);
    });
    const [m, events, artifacts, results] = values;
    category = "MANIFEST";
    if (m?.format !== "nexus-manifest-v1")
      return {
        status: "UNSUPPORTED_FORMAT",
        category: "MANIFEST",
        signature_valid: true,
        signer_trusted: false,
      };
    keys(m, [
      "format",
      "snapshot_id",
      "evaluation_id",
      "profile",
      "subject_id",
      "frozen_at",
      "source_watermark",
      "source_count",
      "chain",
      "terminal_status",
      "cleanup",
      "retrospective",
      "coverage",
      "supersedes",
      "internal_commitment",
      "configuration",
      "artifact_commitments",
      "disclosed_artifacts",
      "limitations",
    ]);
    scoped(m);
    timestamp(m.frozen_at);
    requireThat(p.signed_at >= m.frozen_at);
    requireThat(
      digest("manifest", m) === p.manifest_digest &&
        Number.isSafeInteger(m.source_watermark) &&
        m.source_watermark >= 0 &&
        m.source_watermark <= LIMIT &&
        m.source_count === m.source_watermark &&
        HEX.test(m.internal_commitment) &&
        (m.supersedes === null || UUID.test(m.supersedes)) &&
        object(m.configuration) &&
        Array.isArray(m.limitations) &&
        m.limitations.length > 0 &&
        m.limitations.length <= 12,
    );
    for (const k of [
      "evaluation_id",
      "snapshot_id",
      "profile",
      "subject_id",
      "chain",
      "terminal_status",
      "cleanup",
      "retrospective",
      "coverage",
    ])
      requireThat(canonical(m[k]) === canonical(p[k]));
    category = "CHAIN";
    requireThat(Array.isArray(events) && events.length === m.chain.count);
    const context = {
      evaluation_id: m.evaluation_id,
      snapshot_id: m.snapshot_id,
      profile: m.profile,
      subject_id: m.subject_id,
      source_watermark: m.source_watermark,
    };
    let previous = digest("genesis", context);
    requireThat(previous === m.chain.genesis);
    let lastSource = 0;
    const ids = new Set();
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      keys(e, [
        "format",
        "evaluation_id",
        "snapshot_id",
        "event_id",
        "sequence",
        "source_sequence",
        "event_type",
        "source",
        "destination",
        "timestamp",
        "correlation_id",
        "visibility",
        "payload",
        "payload_digest",
        "previous_hash",
        "hash",
      ]);
      requireThat(
        e.format === "nexus-event-v1" &&
          e.evaluation_id === m.evaluation_id &&
          e.snapshot_id === m.snapshot_id &&
          UUID.test(e.event_id) &&
          UUID.test(e.correlation_id) &&
          !ids.has(e.event_id),
      );
      ids.add(e.event_id);
      timestamp(e.timestamp);
      for (const k of ["event_type", "source", "destination", "visibility"]) {
        text(e[k], k === "event_type" ? 80 : 40);
        requireThat(/^[A-Za-z0-9_.:-]+$/.test(e[k]));
      }
      requireThat(
        Number.isSafeInteger(e.sequence) &&
          e.sequence === i + 1 &&
          Number.isSafeInteger(e.source_sequence) &&
          e.source_sequence > lastSource &&
          e.source_sequence <= m.source_watermark &&
          e.source_sequence === m.chain.source_sequences[i],
      );
      lastSource = e.source_sequence;
      requireThat(
        object(e.payload) &&
          digest("payload", e.payload) === e.payload_digest &&
          e.previous_hash === previous,
      );
      const { hash, ...withoutHash } = e;
      requireThat(digest("event", withoutHash) === hash);
      previous = hash;
    }
    requireThat(previous === m.chain.terminal);
    if (m.profile === "INTERNAL")
      requireThat(
        events.length === m.source_watermark && events.every((e, i) => e.source_sequence === i + 1),
      );
    category = "ARTIFACT";
    requireThat(
      Array.isArray(artifacts) &&
        artifacts.length === 4 &&
        Array.isArray(m.artifact_commitments) &&
        m.artifact_commitments.length === 4,
    );
    const kinds = ["attack", "defence", "model", "flow_policy"];
    const opened = artifacts.filter((a) => a.opening !== null).map((a) => a.kind);
    const allowed = {
      INTERNAL: kinds,
      RED_OPERATOR: ["attack", "model", "flow_policy"],
      BLUE_OPERATOR: ["defence", "model", "flow_policy"],
      AUDITOR: ["model", "flow_policy"],
    }[m.profile];
    requireThat(
      canonical(opened) === canonical(m.disclosed_artifacts) &&
        ["model", "flow_policy"].every((k) => opened.includes(k)) &&
        opened.every((k) => allowed.includes(k)),
    );
    const legacy = m.profile === "INTERNAL" ? m.configuration.committed_manifest : null;
    const bindings = legacy ? legacy.versions : m.configuration.visible_version_bindings;
    requireThat(Array.isArray(bindings) && bindings.length === opened.length);

    for (let i = 0; i < 4; i++) {
      const a = artifacts[i];
      keys(a, ["kind", "commitment", "opening", "data"]);
      requireThat(
        a.kind === kinds[i] && HEX.test(a.commitment) && a.commitment === m.artifact_commitments[i],
      );
      if (a.opening === null) {
        requireThat(a.data === null && m.profile !== "INTERNAL");
        continue;
      }
      const o = a.opening;
      keys(o, ["nonce", "version_id", "kind", "sha256", "byte_size"]);
      requireThat(
        HEX.test(o.nonce) &&
          UUID.test(o.version_id) &&
          o.kind === a.kind &&
          HEX.test(o.sha256) &&
          Number.isSafeInteger(o.byte_size) &&
          o.byte_size > 0 &&
          o.byte_size <= 65536 &&
          digest("artifact", o) === a.commitment,
      );
      const binding = {
        kind: o.kind,
        version_id: o.version_id,
        sha256: o.sha256,
        byte_size: o.byte_size,
      };
      requireThat(bindings.some((b) => canonical(b) === canonical(binding)));
      const blob = binary(a.data);
      requireThat(blob.length === o.byte_size && sha(blob) === o.sha256);
    }
    const model = legacy ? legacy.model : m.configuration.model;
    if (model !== undefined)
      requireThat(
        canonical(
          JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(binary(artifacts[2].data))),
        ) === canonical(model),
      );
    category = "RESULT";
    requireThat(
      object(results) &&
        results.evaluation_id === m.evaluation_id &&
        results.terminal_status === m.terminal_status,
    );
    if (m.profile === "INTERNAL")
      requireThat(
        digest("internal", {
          nonce: m.configuration.opening,
          configuration: m.configuration.committed_manifest,
          events,
          artifacts,
          results,
        }) === m.internal_commitment,
      );
    category = "TRUST";
    const entry = trust[p.key_id];
    let trusted = !!entry && keyId(entry.public_key) === p.key_id;
    if (entry?.activated_at) {
      timestamp(entry.activated_at);
      trusted &&= p.signed_at >= entry.activated_at;
    }
    if (entry?.retired_at) {
      timestamp(entry.retired_at);
      trusted &&= p.signed_at < entry.retired_at;
    }
    return {
      status: trusted ? "VALID" : "UNTRUSTED_SIGNER",
      category: trusted ? "COMPLETE" : "TRUST",
      signature_valid: true,
      signer_trusted: trusted,
      evaluation_id: m.evaluation_id,
      snapshot_id: m.snapshot_id,
      coverage: m.coverage,
      full_internal_evidence_verified: m.profile === "INTERNAL" && trusted,
      terminal_status: m.terminal_status,
      cleanup: m.cleanup,
    };
  } catch {
    return { status: "INVALID", category, signature_valid: signatureValid, signer_trusted: false };
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try {
    const args = process.argv.slice(2);
    requireThat(args.shift() === "verify");
    const file = args.shift();
    requireThat(file && fs.statSync(file).isFile() && fs.statSync(file).size <= MAX);
    const trust = {};
    let expectedEvaluation = null,
      expectedSnapshot = null,
      requireInternal = false;
    while (args.length) {
      const option = args.shift();
      if (option === "--require-internal") {
        requireInternal = true;
        continue;
      }
      const name = args.shift();
      if (option === "--expect-evaluation") {
        requireThat(UUID.test(name));
        expectedEvaluation = name;
        continue;
      }
      if (option === "--expect-snapshot") {
        requireThat(UUID.test(name));
        expectedSnapshot = name;
        continue;
      }
      requireThat(name && fs.statSync(name).isFile() && fs.statSync(name).size <= 65536);
      if (option === "--trust-key") {
        const pem = fs.readFileSync(name, "utf8");
        trust[keyId(pem)] = { public_key: pem };
      } else if (option === "--keyring") {
        const ring = JSON.parse(fs.readFileSync(name, "utf8"));
        requireThat(object(ring));
        for (const [id, entry] of Object.entries(ring)) {
          requireThat(keyId(entry.public_key) === id);
          trust[id] = entry;
        }
      } else throw Error("ARGUMENT");
    }
    result = verifyBundle(fs.readFileSync(file), trust);
    if (
      result.status === "VALID" &&
      ((expectedEvaluation && result.evaluation_id !== expectedEvaluation) ||
        (expectedSnapshot && result.snapshot_id !== expectedSnapshot))
    )
      result = {
        ...result,
        status: "INVALID",
        category: "SCOPE",
        full_internal_evidence_verified: false,
      };
    if (result.status === "VALID" && requireInternal && !result.full_internal_evidence_verified)
      result = { ...result, status: "INCOMPLETE", category: "COVERAGE" };
  } catch {
    result = {
      status: "INVALID",
      category: "INPUT",
      signature_valid: false,
      signer_trusted: false,
    };
  }
  console.log(JSON.stringify(result));
  process.exitCode = {
    VALID: 0,
    INVALID: 1,
    INCOMPLETE: 2,
    UNTRUSTED_SIGNER: 3,
    UNSUPPORTED_FORMAT: 4,
  }[result.status];
}
