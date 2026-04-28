import { compactArray, truncateText, DEFAULT_POLICY } from "./policy.js";

const EDUCATION_LEVELS = ["博士", "硕士", "本科", "大专", "高中", "中专"];
const STATUS_HINTS = ["在职", "离职", "考虑机会", "月内到岗", "随时到岗", "暂不考虑", "应届"];
const ACTIVE_STATUS_RE = /刚刚活跃|今日活跃|昨日活跃|本周活跃|本月活跃|\d+日内活跃|\d+周内活跃|\d+月内活跃/;

export function normalizeText(text) {
  return String(text || "")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
}

export function parseCandidateCardText(rawText, policy = DEFAULT_POLICY) {
  const text = normalizeText(rawText);
  const lines = text.split("\n");
  const joined = lines.join(" | ");
  const firstLine = lines[0] || "";

  const salary = matchFirst(joined, /\b\d{1,3}(?:-\d{1,3})?K(?:·\d{1,2}薪)?\b|面议/i);
  const ageText = matchFirst(joined, /(\d{2})岁/);
  const age = ageText ? Number(ageText.replace("岁", "")) : null;
  const yearsExperience = matchFirst(joined, /(?:\d{2}年应届生|\d{2}年毕业|\d+年(?:以上)?|经验不限|应届)/);
  const educationLevel = EDUCATION_LEVELS.find((level) => joined.includes(level)) || null;
  const jobStatus = STATUS_HINTS.find((hint) => joined.includes(hint)) || null;
  const activeStatus = matchFirst(joined, ACTIVE_STATUS_RE) || "2月以上未活跃";
  const maskedName = parseMaskedName(firstLine);
  const tags = parseTags(lines);
  const expectation = parseExpectationLine(lines, salary, text);
  const school = parseSchool(lines, text);
  const shortSummary = parseSummary(lines, policy.maxSummaryChars, { salary, educationLevel, jobStatus });

  return {
    masked_name: maskedName,
    age,
    years_experience: yearsExperience,
    education_level: educationLevel,
    expected_city: expectation.city,
    expected_position: expectation.position,
    expected_salary: salary,
    job_status: jobStatus,
    active_status: activeStatus,
    school,
    short_summary: shortSummary,
    tags_json: tags,
    parsed_confidence: scoreCardParse({ maskedName, age, yearsExperience, educationLevel, salary, shortSummary })
  };
}

export function inferLastSeenAt(activeStatus, collectedAt = new Date()) {
  const date = new Date(collectedAt);
  const status = activeStatus || "";

  if (status === "刚刚活跃") return date.toISOString();
  if (status === "今日活跃") return startOfDay(date).toISOString();
  if (status === "昨日活跃") return startOfDay(addDays(date, -1)).toISOString();
  if (status === "本周活跃") return startOfWeek(date).toISOString();
  if (status === "本月活跃") return new Date(date.getFullYear(), date.getMonth(), 1).toISOString();

  const dayMatch = status.match(/^(\d+)日内活跃$/);
  if (dayMatch) return addDays(date, -Number(dayMatch[1])).toISOString();

  const weekMatch = status.match(/^(\d+)周内活跃$/);
  if (weekMatch) return addDays(date, -Number(weekMatch[1]) * 7).toISOString();

  const monthMatch = status.match(/^(\d+)月内活跃$/);
  if (monthMatch) {
    const inferred = new Date(date);
    inferred.setMonth(inferred.getMonth() - Number(monthMatch[1]));
    return inferred.toISOString();
  }

  if (status === "2月以上未活跃") {
    const inferred = new Date(date);
    inferred.setMonth(inferred.getMonth() - 2);
    return inferred.toISOString();
  }

  const fallback = new Date(date);
  fallback.setMonth(fallback.getMonth() - 2);
  return fallback.toISOString();
}

export function parseDetailText(rawText, policy = DEFAULT_POLICY) {
  const text = normalizeText(rawText);
  const lines = text.split("\n");
  const tags = parseTags(lines, 16);
  const schools = findSchoolCandidates(lines);
  const companies = findCompanyCandidates(lines);
  const positions = findPositionCandidates(lines);
  const summary = pickDetailSummary(lines, policy.maxDetailSummaryChars);

  return {
    detail_summary: summary,
    detail_tags_json: tags,
    detail_schools_json: schools,
    detail_companies_json: companies,
    detail_positions_json: positions
  };
}

function parseMaskedName(firstLine) {
  const match = firstLine.match(/[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z*＊]{1,12}/);
  if (!match) return null;
  return match[0].replace(/＊/g, "*");
}

function parseExpectationLine(lines, salary, fullText = "") {
  const result = { city: null, position: null };
  const inlineMatch = fullText.match(/期望(?:城市)?\s+([^\s]+)(?:\s+(.+?))?\s+职位\s/);
  if (inlineMatch) {
    result.city = inlineMatch[1] || null;
    result.position = inlineMatch[2]?.trim() || null;
    return result;
  }

  const explicitExpectation = lines.find((item) => /^期望\s+/.test(item));
  if (explicitExpectation) {
    const value = explicitExpectation.replace(/^期望\s*/, "").trim();
    const parts = value.split(/[·\-]/).map((item) => item.trim()).filter(Boolean);
    result.city = parts[0] || null;
    result.position = parts.slice(1).join("/") || null;
    return result;
  }

  const line = lines.find((item) => salary && item.includes(salary)) || "";
  if (!line) return result;

  const chunks = line
    .split(/[|｜]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const salaryIndex = chunks.findIndex((item) => item.includes(salary));
  const statusIndex = chunks.findIndex((item) => STATUS_HINTS.some((hint) => item.includes(hint)));

  if (statusIndex >= 0 && chunks[statusIndex + 1]) {
    const nextChunk = chunks[statusIndex + 1];
    if (!salary || !nextChunk.includes(salary)) {
      result.city = nextChunk.split(/[·\-]/)[0]?.trim() || null;
    }
  }

  if (salaryIndex > 0) {
    const beforeSalary = chunks[salaryIndex - 1];
    if (!STATUS_HINTS.some((hint) => beforeSalary.includes(hint))) {
      const parts = beforeSalary.split(/[·\-]/).map((item) => item.trim()).filter(Boolean);
      result.city ||= parts[0] || null;
      result.position = parts.slice(1).join("/") || null;
    }
  }

  return result;
}

function parseSchool(lines, fullText = "") {
  const inlineSchoolIndex = fullText.lastIndexOf("院校 ");
  if (inlineSchoolIndex >= 0) {
    return truncateText(fullText.slice(inlineSchoolIndex + "院校 ".length), 100);
  }

  const schoolLine = lines.find((line) => /院校|大学|学院|学校/.test(line));
  if (!schoolLine) return null;
  const cleaned = schoolLine.replace(/^(院校|学校)\s*/, "").trim();
  return truncateText(cleaned.split(/[|｜]/).pop() || cleaned, 80);
}

function parseSummary(lines, maxLength, context = {}) {
  if (lines.length === 1) {
    const inline = parseInlineSummary(lines[0], context);
    if (inline) return truncateText(inline, maxLength);
  }

  const candidate = lines.find((line) => {
    if (line.length < 12) return false;
    if (/\d{2}岁|\d+年|本科|大专|硕士|博士|\d{1,3}-\d{1,3}K/.test(line)) return false;
    if (/期望|职位|院校|学校/.test(line)) return false;
    return true;
  });
  return truncateText(candidate || "", maxLength);
}

function parseInlineSummary(line, context) {
  const expectationIndex = line.search(/期望(?:城市)?\s/);
  if (expectationIndex <= 0) return "";

  const beforeExpectation = line.slice(0, expectationIndex).trim();
  const anchors = [context.salary, context.jobStatus, context.educationLevel, matchFirst(line, /(?:\d{2}年应届生|\d{2}年毕业|\d+年(?:以上)?|经验不限|应届)/)]
    .filter(Boolean)
    .sort((a, b) => beforeExpectation.lastIndexOf(b) - beforeExpectation.lastIndexOf(a));

  for (const anchor of anchors) {
    const index = beforeExpectation.lastIndexOf(anchor);
    if (index >= 0) {
      return beforeExpectation.slice(index + anchor.length).replace(/^[-\s]+/, "").trim();
    }
  }

  return "";
}

function parseTags(lines, limit = 20) {
  const tagLike = [];

  for (const line of lines) {
    if (/^(期望|职位|院校|学校)\s*/.test(line)) continue;
    if (/\d{2}岁|\d+年|\d{1,3}-\d{1,3}K|在职|离职|本科|大专|硕士|博士/.test(line)) continue;
    if (/·|刚刚活跃|活跃/.test(line)) continue;

    const chunks = line.split(/\s+|,|，|、|\|/).map((item) => item.trim()).filter(Boolean);
    for (const chunk of chunks) {
      if (chunk.length < 2 || chunk.length > 24) continue;
      if (/^[\u4e00-\u9fa5A-Za-z0-9+#./-]+$/.test(chunk)) tagLike.push(chunk);
    }
  }

  return compactArray(tagLike, limit);
}

function pickDetailSummary(lines, maxLength) {
  const startIndex = lines.findIndex((line) => /岁|本科|硕士|博士|大专|在职|离职|考虑机会/.test(line));
  const candidates = lines.slice(Math.max(0, startIndex), startIndex + 8);
  const summary = candidates.find((line) => line.length >= 24 && !/工作经历|项目经验|教育经历|期望职位/.test(line));
  return truncateText(summary || "", maxLength);
}

function findSchoolCandidates(lines) {
  return compactArray(
    lines
      .filter((line) => /大学|学院|学校/.test(line))
      .map((line) => truncateText(line.replace(/^院校\s*/, ""), 100)),
    5
  );
}

function findCompanyCandidates(lines) {
  return compactArray(
    lines
      .filter((line) => /公司|集团|科技|网络|传媒|咨询|股份|有限公司/.test(line))
      .map((line) => truncateText(line, 120)),
    8
  );
}

function findPositionCandidates(lines) {
  return compactArray(
    lines
      .filter((line) => /工程师|开发|产品|运营|设计|销售|市场|经理|顾问|算法|测试|数据/.test(line))
      .map((line) => truncateText(line, 100)),
    8
  );
}

function scoreCardParse(values) {
  const keys = ["maskedName", "age", "yearsExperience", "educationLevel", "salary", "shortSummary"];
  const score = keys.reduce((sum, key) => sum + (values[key] ? 1 : 0), 0) / keys.length;
  return Number(score.toFixed(3));
}

function matchFirst(text, regex) {
  const match = text.match(regex);
  return match ? match[0] : null;
}

function addDays(date, days) {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function startOfWeek(date) {
  const result = startOfDay(date);
  const day = result.getDay() || 7;
  result.setDate(result.getDate() - day + 1);
  return result;
}
