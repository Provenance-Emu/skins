# Invite-only skin uploads

The static submission page sends one ZIP bundle directly to the Worker. The
Worker stages it in private R2. Creators pick files from iPhone Files and need
only an invite code. Maintainers review and publish approved skins through the
existing catalog process.

## Enable the pilot

1. Use Workers Free and create a **private R2 Standard** bucket named
   `emuskins-upload-pilot`. Leave its public URL and public custom domains
   disabled. Add a lifecycle rule to expire objects under `pending/` after
   14 days. R2 usage beyond the included allowance can incur charges.
2. From this directory, use Wrangler with an authorized Cloudflare account.
   Run `wrangler deploy` to publish the Worker at
   `https://emuskins-uploads.skin-uploads.workers.dev`. The Worker only accepts the production site's origin and has no public read route.
3. Generate a separate code per creator with the command below. Send only the
   code and the submission page link to the creator. Keep the hash, creator,
   and expiration in a private operator record. Maintain at most 20 active
   invitations, each expiring within 7 days.
4. Set `INVITE_EXPIRATIONS` with `wrangler secret put INVITE_EXPIRATIONS`.
   Paste a JSON object mapping each active hash to its numeric expiration in
   Unix milliseconds. Update the complete map on each change. Never commit
   codes or the map. A missing map disables uploads.

```sh
python3 - <<'PY'
import hashlib, secrets, time
code = secrets.token_hex(32)
print("Send to creator:", code)
print("Hash:", hashlib.sha256(code.encode()).hexdigest())
print("Expires:", int((time.time() + 7 * 86400) * 1000))
PY
```

Each invite accepts one batch. The browser limits it to five files and 15 MiB
of archive data. The Worker caps the bundle at 16 MiB and uses an atomic R2
conditional write, so parallel submissions cannot overwrite the first batch.
The receipt identifies the upload in the R2 object's `requestId` metadata.
Remove used codes from the map before deleting their objects. Keep production
requests and raw invite codes out of logs.

## Review and publish

1. Find `pending/<invite-hash>.zip` in the private bucket and check the receipt
   against the object's metadata. Download it with the authenticated R2
   dashboard or `wrangler r2 object get` using remote storage.
2. Run `python3 scripts/review_skin_upload.py BUNDLE.zip NEW_OUTPUT_DIRECTORY`
   from the repo root. This extracts only expected entries with bounded sizes.
   Read `submission.json` for the author, source and permission. Confirm
   ownership with the inviter and look for an existing listing to update.
   Treat the bundle, nested archives, and links as untrusted.
3. Inspect and validate each approved skin with the existing skin tooling.
   Upload the original skin files as uniquely named assets to the repo's
   `mirror` release. Use their asset URLs with `scripts/process_submission.py`
   or the existing submission bot. Set author credit and update existing
   metadata where appropriate, then open the catalog PR for review.
   The submission manifest is private and does not belong in the PR.
4. Reply to the creator via the channel used for the invitation. Remove the
   invite from the secret map and delete the staged bundle after review.

For the first live test, use Safari on an iPhone with a test invite and two
small skins in Files. Confirm the receipt matches R2, then verify a second
submission with the same code is rejected. The Pages site and Worker deploy
separately. Deploy and verify the Worker before publicizing the pilot.
