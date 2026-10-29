// Fails if any source file outside the design-token stylesheet hard-codes a hex colour.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
const ALLOWED = new Set(["styles/tokens.css", "types/api.ts", "types/openapi.json"]);
const HEX = /#(?:[0-9a-fA-F]{3}){1,2}\b(?![-\w])/g;
const offenders = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(tsx?|css)$/.test(name)) {
      const rel = path.slice(ROOT.length + 1);
      if (ALLOWED.has(rel)) continue;
      readFileSync(path, "utf8").split("\n").forEach((line, i) => {
        const hits = line.match(HEX)?.filter((h) => !/^#\d+$/.test(h) || h.length > 4);
        if (hits?.length) offenders.push(`${rel}:${i + 1}: ${hits.join(", ")}`);
      });
    }
  }
}

walk(ROOT);
if (offenders.length) {
  console.error("Hard-coded colours found (use DESIGN.md tokens from styles/tokens.css):");
  console.error(offenders.join("\n"));
  process.exit(1);
}
console.log("Design tokens check passed.");
