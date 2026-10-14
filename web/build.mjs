// Copies the assets Tailwind does not compile into ./dist so the whole app can
// be served from a single directory by the FastAPI backend.
import { cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const assets = ["index.html", "app.js"];

mkdirSync(resolve(root, "dist"), { recursive: true });

for (const asset of assets) {
  cpSync(resolve(root, "src", asset), resolve(root, "dist", asset));
  console.log(`copied  src/${asset} -> dist/${asset}`);
}
