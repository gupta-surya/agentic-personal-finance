// CDN guard: the product has no web access, so the built app must not load anything
// from another origin. Fails on any absolute URL used to load an asset in dist/.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join } from "node:path";

const DIST = "dist";
const TEXT = new Set([".html", ".css", ".js", ".mjs", ".svg"]);

// Loading forms: src/href attributes, CSS url()/@import, dynamic import(), fetch(),
// XHR/WebSocket/EventSource constructors, sendBeacon, and importScripts.
const LOADERS = [
  /\b(?:src|href|srcset|poster|action)\s*=\s*["']?\s*(?:https?:)?\/\//i,
  /url\(\s*["']?\s*(?:https?:)?\/\//i,
  /@import\s+(?:url\()?\s*["']\s*(?:https?:)?\/\//i,
  /\bimport\(\s*["'`]https?:/i,
  /\bfetch\(\s*["'`]https?:/i,
  /\b(?:WebSocket|EventSource)\(\s*["'`](?:https?|wss?):/i,
  /\.(?:open\([^)]*|sendBeacon\()\s*["'`]https?:/i,
  /\bimportScripts\(\s*["'`]https?:/i,
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

let failures = 0;
let scanned = 0;
for (const path of walk(DIST)) {
  if (!TEXT.has(extname(path))) continue;
  scanned += 1;
  const text = readFileSync(path, "utf8");
  for (const pattern of LOADERS) {
    const match = pattern.exec(text);
    if (match) {
      failures += 1;
      const around = text.slice(Math.max(0, match.index - 20), match.index + 80).replace(/\s+/g, " ");
      console.error(`${path}: external load matches ${pattern}: …${around}…`);
    }
  }
}
if (scanned === 0) {
  console.error("no files scanned: run `npm run build` first");
  process.exit(1);
}
if (failures > 0) process.exit(1);
console.log(`no external asset loads in ${scanned} built files`);
