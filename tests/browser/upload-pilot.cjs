const assert = require("node:assert/strict");
const { createServer } = require("node:http");
const { createHash } = require("node:crypto");
const { chromium, webkit, devices } = require("playwright");
const { zipSync, unzipSync, strToU8, strFromU8 } = require("fflate");

const base = process.env.BASE_URL || "http://localhost:8765";
const endpoint = "https://emuskins-uploads.skin-uploads.workers.dev/submit";
const invite = "1".repeat(64);
const hash = createHash("sha256").update(invite).digest("hex");
const skin = Buffer.from(zipSync({
  "info.json": strToU8(JSON.stringify({
    name: "Upload Test",
    gameTypeIdentifier: "com.rileytestut.delta.game.gba",
    representations: { iphone: { standard: { portrait: { assets: {} } } } },
  })),
}));

async function run(engine, options) {
  const { default: worker } = await import("../../workers/skin-uploads/worker.mjs");
  const objects = new Map();
  const env = {
    SITE_ORIGIN: new URL(base).origin,
    INVITE_EXPIRATIONS: JSON.stringify({ [hash]: Date.now() + 60000 }),
    SUBMISSIONS: {
      head: async key => objects.get(key),
      put: async (key, bytes, { onlyIf, customMetadata }) => {
        assert.equal(onlyIf.get("If-None-Match"), "*");
        if (objects.has(key)) return null;
        const object = { bytes, customMetadata };
        objects.set(key, object);
        return object;
      },
    },
  };
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const result = await worker.fetch(new Request(endpoint, {
      method: request.method,
      headers: request.headers,
      body: chunks.length ? Buffer.concat(chunks) : undefined,
    }), env);
    response.writeHead(result.status, Object.fromEntries(result.headers));
    response.end(await result.text());
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await engine.launch();
  try {
    const page = await browser.newPage({ ...options, serviceWorkers: "block" });
    await page.goto(base + "/submit.html");
    await page.locator("#skin-upload-form").evaluate((form, url) => {
      form.dataset.endpoint = url;
    }, `http://127.0.0.1:${server.address().port}/submit`);
    const status = page.locator("#upload-status");
    const send = page.getByRole("button", { name: "Submit for review" });
    const picker = page.getByLabel("Skin files");
    assert.equal(await picker.getAttribute("accept"), null, "Allow Files to select custom extensions");
    await picker.setInputFiles({ name: "bad.zip", mimeType: "application/zip", buffer: skin });
    await status.filter({ hasText: "choose a .deltaskin" }).waitFor();
    assert.equal(await send.isDisabled(), true);
    await picker.setInputFiles([
      { name: "One.deltaskin", mimeType: "application/octet-stream", buffer: skin },
      { name: "Two.manicskin", mimeType: "application/octet-stream", buffer: skin },
    ]);
    await page.locator("#upload-preview li").first().waitFor();
    assert.deepEqual(await page.locator("#upload-preview li").allTextContents(),
      ["Upload Test · gba · 1 layout", "Upload Test · gba · 1 layout"]);
    await page.getByLabel("Invite code").fill("0".repeat(64));
    await page.getByLabel("Author name for the catalog").fill("Pilot Creator");
    await page.getByLabel("I made these skins").check();
    await send.click();
    await status.filter({ hasText: "invalid or expired" }).waitFor();
    assert.equal(objects.size, 0);
    await page.getByLabel("Invite code").fill(invite);
    await send.click();
    await status.filter({ hasText: "Submitted for review" }).waitFor();
    const staged = objects.get(`pending/${hash}.zip`);
    assert.match(await status.textContent(), new RegExp(staged.customMetadata.requestId));
    const entries = unzipSync(staged.bytes);
    const manifest = JSON.parse(strFromU8(entries["submission.json"]));
    assert.equal(manifest.author, "Pilot Creator");
    assert.equal(manifest.permission, true);
    assert.deepEqual(manifest.files.map(file => file.name), ["One.deltaskin", "Two.manicskin"]);
    assert.deepEqual(Buffer.from(entries["skin-2.manicskin"]), skin);

    const submit = id => worker.fetch(new Request(endpoint, {
      method: "POST",
      headers: {
        Origin: env.SITE_ORIGIN,
        Authorization: `Bearer ${invite}`,
        "Content-Type": "application/zip",
        "X-Submission-ID": id,
      },
      body: staged.bytes,
    }), env);
    assert.equal((await submit(staged.customMetadata.requestId)).status, 200);
    assert.equal((await submit("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")).status, 409);
    assert.equal(objects.size, 1);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

(async () => {
  await run(chromium, {});
  await run(webkit, devices["iPhone 13"]);
})().catch(error => { console.error(error); process.exitCode = 1; });
