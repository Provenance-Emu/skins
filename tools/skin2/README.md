# Bake a format 2 skin

From the repository root, install the baker dependencies and run the CLI.

```sh
npm ci --prefix tools/skin2
node tools/skin2/bake.mjs path/to/skin.json path/to/output
```

The CLI reads assets beside the source and writes a classic archive for each
game type and selectable layout. The ES module in `docs/js/skin2/bake.js`
also exposes the baker with a caller-supplied artwork backend.

To compare against Swift, build `skinkit-bake` in SkinKit first. Both commands
below should use the same source fixture tree. The comparison requires
Poppler's `pdftocairo` and the renderer test dependencies.

```sh
npm ci --prefix tests/skin2
swift_out=$(mktemp -d)
ts_out=$(mktemp -d)
for source in "$SKINKIT/Tests/Format2Fixtures/"*/skin.json; do
  fixture=$(basename "$(dirname "$source")")
  "$SKINKIT/.build/debug/skinkit-bake" "$source" "$swift_out/$fixture"
  node tools/skin2/bake.mjs "$source" "$ts_out/$fixture"
done
node tests/skin2/bake-parity.mjs "$swift_out" "$ts_out"
```

Set `SKINKIT` to the SkinKit checkout path before running these commands.
The comparison checks archive contents, exact metadata bytes, and the §9.3
pixel tolerance for previews and PDFs rendered at 2×.
