// Production-bundle guard: development-only code (src/dev: canned fixtures, the swatch
// renderer, the fixture page) must not ship. These strings exist only in src/dev, so
// finding one in dist/ means it was bundled.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join } from "node:path";

const DIST = "dist";
const MARKERS = [
  "fixture_swatch", // the dev template id
  "Chart fixtures", // the fixture page heading
  "A template with no renderer", // a canned spec title
  "onerror=alert", // the canned markup-injection template id
  "res_7f3b", // the canned result id
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

let scanned = 0;
let failures = 0;
for (const path of walk(DIST)) {
  if (![".js", ".mjs", ".html", ".css"].includes(extname(path))) continue;
  scanned += 1;
  const text = readFileSync(path, "utf8");
  for (const marker of MARKERS) {
    if (text.includes(marker)) {
      failures += 1;
      console.error(`${path}: contains dev-only marker ${JSON.stringify(marker)}`);
    }
  }
}
if (scanned === 0) {
  console.error("no files scanned: run `npm run build` first");
  process.exit(1);
}
if (failures > 0) process.exit(1);
console.log(`no dev-only code in ${scanned} built files`);
