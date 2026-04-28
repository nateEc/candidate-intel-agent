#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { join, resolve } from "node:path";
import { mkdir } from "node:fs/promises";
import { inferLastSeenAt, parseCandidateCardText } from "./parse.js";
import { createCandidateFingerprint } from "./fingerprint.js";
import { appendJsonl, writeRunOutput } from "./store-jsonl.js";

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const outputDir = resolve(options.outputDir);
  const runId = new Date().toISOString().replace(/[:.]/g, "-");

  await mkdir(outputDir, { recursive: true });

  const sourceUrl = runOsascript(["tell application \"Google Chrome\" to get URL of active tab of front window"]).trim();
  const rawOutput = runOsascript(buildAccessibilityScript(options.limit));
  const descriptions = [...new Set(rawOutput.split("\n").map((line) => line.trim()).filter(Boolean))].slice(0, options.limit);

  if (!descriptions.length) {
    console.log("没有从当前 Chrome 窗口识别到候选人卡片。请确认 BOSS 人才库列表可见，并把 Chrome 放在前台。");
    return;
  }

  const collectedAt = new Date();
  const candidates = descriptions.map((description) => {
    const cardIndex = parseCandidateCardText(description);
    const candidate = {
      source_platform: "boss_zhipin",
      ...cardIndex,
      source_url: sourceUrl,
      last_seen_at: inferLastSeenAt(cardIndex.active_status, collectedAt)
    };

    candidate.source_fingerprint = createCandidateFingerprint(candidate);
    return candidate;
  });

  const observations = candidates.map((candidate, index) => ({
    source_platform: "boss_zhipin",
    source_fingerprint: candidate.source_fingerprint,
    observed_at: new Date().toISOString(),
    source_url: sourceUrl,
    visible_card_json: {
      masked_name: candidate.masked_name,
      age: candidate.age,
      years_experience: candidate.years_experience,
      education_level: candidate.education_level,
      expected_city: candidate.expected_city,
      expected_position: candidate.expected_position,
      expected_salary: candidate.expected_salary,
      job_status: candidate.job_status,
      active_status: candidate.active_status,
      short_summary: candidate.short_summary,
      school: candidate.school,
      tags_json: candidate.tags_json
    },
    raw_card_index: index,
    parsed_confidence: candidate.parsed_confidence
  }));

  await appendJsonl(join(outputDir, "candidates.ndjson"), candidates);
  await appendJsonl(join(outputDir, "observations.ndjson"), observations);
  const runFile = await writeRunOutput(outputDir, runId, {
    runId,
    mode: "chrome_accessibility",
    count: candidates.length,
    candidates,
    observations
  });

  console.log(`完成：${candidates.length} 条候选人列表索引。`);
  console.log(`单次运行结果：${runFile}`);
}

function buildAccessibilityScript(limit) {
  return [
    "property outputText : \"\"",
    "property candidateCount : 0",
    `property candidateLimit : ${Number(limit)}`,
    "on scan(theElement)",
    "if candidateCount >= candidateLimit then return",
    "tell application \"System Events\"",
    "set d to \"\"",
    "try",
    "set d to description of theElement as text",
    "end try",
    "if (d contains \"岁\") and (d contains \"职位\") and ((d contains \"期望\") or (d contains \"期望城市\")) then",
    "set outputText to outputText & d & linefeed",
    "set candidateCount to candidateCount + 1",
    "end if",
    "try",
    "set kids to UI elements of theElement",
    "on error",
    "set kids to {}",
    "end try",
    "end tell",
    "repeat with c in kids",
    "if candidateCount >= candidateLimit then exit repeat",
    "my scan(c)",
    "end repeat",
    "end scan",
    "tell application \"System Events\"",
    "tell process \"Google Chrome\"",
    "my scan(front window)",
    "end tell",
    "end tell",
    "return outputText"
  ];
}

function runOsascript(lines) {
  const result = spawnSync("osascript", lines.flatMap((line) => ["-e", line]), {
    encoding: "utf8",
    timeout: 180000,
    maxBuffer: 1024 * 1024 * 8
  });

  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "osascript failed").trim());
  }

  return result.stdout;
}

function parseArgs(args) {
  const options = {
    limit: 15,
    outputDir: "data"
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--limit") options.limit = Number(args[++index]);
    else if (arg === "--output-dir") options.outputDir = args[++index];
    else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }

  if (!Number.isFinite(options.limit) || options.limit < 1) {
    throw new Error("--limit 必须是大于 0 的数字");
  }

  return options;
}

function printHelp() {
  console.log(`Usage:
  npm run capture:chrome-ax -- [options]

Options:
  --limit <n>             最多读取候选人数量，默认 15
  --output-dir <dir>      输出目录，默认 data
`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
