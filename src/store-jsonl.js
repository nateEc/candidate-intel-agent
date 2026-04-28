import { mkdir, appendFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export async function appendJsonl(filePath, rows) {
  if (!rows.length) return;
  await mkdir(dirname(filePath), { recursive: true });
  const payload = rows.map((row) => JSON.stringify(row)).join("\n") + "\n";
  await appendFile(filePath, payload, "utf8");
}

export async function writeRunOutput(outputDir, runId, payload) {
  const runDir = join(outputDir, "runs");
  await mkdir(runDir, { recursive: true });
  const filePath = join(runDir, `run-${runId}.json`);
  await writeFile(filePath, JSON.stringify(payload, null, 2), "utf8");
  return filePath;
}
