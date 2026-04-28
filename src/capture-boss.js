#!/usr/bin/env node
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { mkdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { inferLastSeenAt, parseCandidateCardText, parseDetailText } from "./parse.js";
import { DEFAULT_POLICY } from "./policy.js";
import { createCandidateFingerprint } from "./fingerprint.js";
import { appendJsonl, writeRunOutput } from "./store-jsonl.js";
import { extractLikelyDialogText, extractVisibleCandidateCards } from "./page-extractors.js";

const DEFAULT_START_URL = "https://www.zhipin.com/web/chat/search";

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const runId = new Date().toISOString().replace(/[:.]/g, "-");
  const outputDir = resolve(options.outputDir);
  const userDataDir = resolve(options.userDataDir);

  await mkdir(outputDir, { recursive: true });

  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: process.env.BOSS_BROWSER_EXECUTABLE ? undefined : "chrome",
    executablePath: process.env.BOSS_BROWSER_EXECUTABLE || undefined,
    headless: options.headless,
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN"
  });

  const page = context.pages()[0] || (await context.newPage());
  page.setDefaultTimeout(8000);
  await page.goto(options.startUrl, { waitUntil: "domcontentloaded" });

  console.log("浏览器已打开。请手动登录 BOSS、设置搜索条件，并确保候选人列表可见。");
  await waitForEnter("准备好后按回车开始读取当前页面...");

  await page.waitForLoadState("networkidle").catch(() => {});
  const cards = await extractVisibleCandidateCards(page, options.limit);

  if (!cards.length) {
    console.log("没有识别到候选人卡片。请确认页面已登录、列表可见，或把 --limit 调小后重试。");
    await context.close();
    return;
  }

  const candidates = [];
  const observations = [];
  const collectedAt = new Date();

  for (const card of cards) {
    const cardIndex = parseCandidateCardText(card.text, options.policy);
    const detailIndex = options.includeDetails ? await captureDetailForCard(page, card, options.policy) : {};
    const candidate = {
      source_platform: "boss_zhipin",
      ...cardIndex,
      ...mergeDetailIndex(detailIndex),
      source_url: page.url(),
      last_seen_at: inferLastSeenAt(cardIndex.active_status, collectedAt)
    };

    candidate.source_fingerprint = createCandidateFingerprint(candidate);
    candidates.push(candidate);
    observations.push({
      source_platform: "boss_zhipin",
      source_fingerprint: candidate.source_fingerprint,
      observed_at: new Date().toISOString(),
      source_url: page.url(),
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
        tags_json: candidate.tags_json
      },
      parsed_confidence: candidate.parsed_confidence
    });

    console.log(`已读取 ${candidates.length}/${cards.length}: ${candidate.masked_name || "未知"} ${candidate.expected_position || ""} ${candidate.expected_salary || ""}`);
  }

  await appendJsonl(join(outputDir, "candidates.ndjson"), candidates);
  await appendJsonl(join(outputDir, "observations.ndjson"), observations);
  const runFile = await writeRunOutput(outputDir, runId, { runId, count: candidates.length, candidates, observations });

  console.log(`完成：${candidates.length} 条候选人索引。`);
  console.log(`单次运行结果：${runFile}`);
  await context.close();
}

async function captureDetailForCard(page, card, policy) {
  await page.mouse.click(card.rect.x + Math.min(80, card.rect.width / 2), card.rect.y + Math.min(40, card.rect.height / 2));
  await page.waitForTimeout(900);

  const dialog = await extractLikelyDialogText(page);
  if (!dialog) return {};

  const detail = parseDetailText(dialog.text, policy);
  await closeLikelyDialog(page, dialog.rect);
  await page.waitForTimeout(350);
  return detail;
}

async function closeLikelyDialog(page, rect) {
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(150);

  const stillOpen = await extractLikelyDialogText(page);
  if (!stillOpen) return;

  await page.mouse.click(rect.x + rect.width - 28, rect.y + 28).catch(() => {});
}

function mergeDetailIndex(detail) {
  if (!detail || !Object.keys(detail).length) return {};

  return {
    detail_summary: detail.detail_summary || null,
    detail_tags_json: detail.detail_tags_json || [],
    detail_schools_json: detail.detail_schools_json || [],
    detail_companies_json: detail.detail_companies_json || [],
    detail_positions_json: detail.detail_positions_json || []
  };
}

function parseArgs(args) {
  const options = {
    startUrl: DEFAULT_START_URL,
    limit: 20,
    includeDetails: true,
    headless: false,
    userDataDir: ".browser-profile",
    outputDir: "data",
    policy: DEFAULT_POLICY
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--limit") options.limit = Number(args[++index]);
    else if (arg === "--start-url") options.startUrl = args[++index];
    else if (arg === "--user-data-dir") options.userDataDir = args[++index];
    else if (arg === "--output-dir") options.outputDir = args[++index];
    else if (arg === "--details") options.includeDetails = true;
    else if (arg === "--no-details") options.includeDetails = false;
    else if (arg === "--headless") options.headless = true;
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
  npm run capture -- [options]

Options:
  --limit <n>             最多读取候选人数量，默认 20
  --details               点开详情弹窗并抽取轻量索引，默认开启
  --no-details            只读取列表页
  --start-url <url>       起始 URL
  --user-data-dir <dir>   浏览器登录态目录，默认 .browser-profile
  --output-dir <dir>      输出目录，默认 data
  --headless              无头模式
`);
}

async function waitForEnter(message) {
  const rl = createInterface({ input, output });
  await rl.question(`${message}\n`);
  rl.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
