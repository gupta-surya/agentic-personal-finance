// Drift guard: src/api/schema.d.ts must equal what openapi-typescript generates from
// contracts/charts.openapi.json. Run `npm run types` to refresh it.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "schema-"));
const generated = join(dir, "schema.d.ts");
try {
  execFileSync("npx", ["openapi-typescript", "../contracts/charts.openapi.json", "-o", generated], {
    stdio: "ignore",
  });
  const fresh = readFileSync(generated, "utf8");
  const committed = readFileSync("src/api/schema.d.ts", "utf8");
  if (fresh !== committed) {
    console.error("src/api/schema.d.ts is stale: run `npm run types`");
    process.exit(1);
  }
  console.log("src/api/schema.d.ts matches contracts/charts.openapi.json");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
