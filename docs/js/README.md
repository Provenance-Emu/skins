# EmuSkins renderer

An ES module preview renderer for classic Delta and Manic skin archives, SkinKit
Format 2 documents and TV bezels. The EmuSkins bezel gallery imports this same
entry point directly, so it needs no build step.

Pack from this checkout with `npm pack ./docs/js` and install the tarball in a
test project. Release tags are named `skin-renderer-v<version>` and publish that
version to GitHub Packages from a commit on `main`.

For registry installs, add `@provenance-emu:registry=https://npm.pkg.github.com`
to your npm configuration and authenticate with GitHub Packages. Then run
`npm install @provenance-emu/skin-renderer jszip`.

```js
import { renderBezel, renderSkin } from "@provenance-emu/skin-renderer";
import JSZip from "jszip";

const { canvas } = await renderSkin(await response.arrayBuffer(), {
  JSZip,
  environment: {
    size: { width: 393, height: 852 },
    device: "iphone",
    displayType: "edgeToEdge",
    orientation: "portrait",
  },
});
document.body.append(canvas);

const bezel = renderBezel(bezelDocument, {
  width: 1920,
  height: 1080,
  scale: 0.5,
  screenPlaceholders: true,
});
document.body.append(bezel.canvas);
```

Classic layouts are selected by their representation path, such as
`["iphone", "edgeToEdge", "portrait"]`. Set `alternate: true` to render the
alternate representation tree. Classic PDF art uses the same pinned PDF.js
loader as the EmuSkins editor.

Format 2 accepts `theme`, `variant`, `edits`, decoded `images` and parsed
`fonts` (supply fonts for text nodes). The bezel result reports the tube
rectangle in layout units. A custom `surface` factory supports rendering
Format 2 outside the browser. The `/core` entry exposes the resolver, validator,
and Canvas 2D renderer directly.
