const MAX_BYTES = 16 * 1024 * 1024;
const INVITE_PATTERN = /^[0-9a-f]{64}$/;
const REQUEST_ID_PATTERN = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;

async function readBundle(request) {
  const reader = request.body?.getReader();
  if (!reader) return null;
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin");
    const allowed = origin && origin === env.SITE_ORIGIN;
    const headers = { "Cache-Control": "no-store", Vary: "Origin" };
    if (allowed) headers["Access-Control-Allow-Origin"] = origin;
    const respond = (status, data) => Response.json(data, { status, headers });

    if (new URL(request.url).pathname !== "/submit") return respond(404, { error: "Not found." });
    if (!allowed) return respond(403, { error: "Origin not allowed." });
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: {
        ...headers,
        "Access-Control-Allow-Methods": "POST",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Submission-ID",
      } });
    }
    if (request.method !== "POST") return respond(405, { error: "Use POST." });

    const invite = request.headers.get("Authorization")?.slice(7) || "";
    if (!request.headers.get("Authorization")?.startsWith("Bearer ") || !INVITE_PATTERN.test(invite)) {
      return respond(401, { error: "Enter your invite code." });
    }
    const requestId = request.headers.get("X-Submission-ID") || "";
    if (!REQUEST_ID_PATTERN.test(requestId)) return respond(400, { error: "Missing submission ID." });

    try {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(invite));
      const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      const expires = JSON.parse(env.INVITE_EXPIRATIONS || "{}")[hash];
      if (!Number.isFinite(expires) || expires <= Date.now()) {
        return respond(401, { error: "This invite is invalid or expired." });
      }
      if (request.headers.get("Content-Type") !== "application/zip") {
        return respond(415, { error: "Expected a ZIP bundle." });
      }
      if (Number(request.headers.get("Content-Length")) > MAX_BYTES) {
        return respond(413, { error: "The upload exceeds 16 MiB." });
      }

      const key = `pending/${hash}.zip`;
      const existing = await env.SUBMISSIONS.head(key);
      const receipt = existing => existing.customMetadata?.requestId === requestId
        ? respond(200, { receipt: requestId })
        : respond(409, { error: "This invite has already been used." });
      if (existing) return receipt(existing);

      const bytes = await readBundle(request);
      if (!bytes) return respond(413, { error: "The upload is empty or exceeds 16 MiB." });
      if (bytes[0] !== 0x50 || bytes[1] !== 0x4b || bytes[2] !== 3 || bytes[3] !== 4) {
        return respond(400, { error: "The upload is not a ZIP bundle." });
      }
      const saved = await env.SUBMISSIONS.put(key, bytes, {
        onlyIf: new Headers({ "If-None-Match": "*" }),
        httpMetadata: { contentType: "application/zip" },
        customMetadata: { requestId },
      });
      if (saved) return respond(201, { receipt: requestId });
      const winner = await env.SUBMISSIONS.head(key);
      if (winner) return receipt(winner);
      return respond(503, { error: "Please retry the upload." });
    } catch {
      return respond(503, { error: "Uploads are temporarily unavailable. Please try again." });
    }
  },
};
