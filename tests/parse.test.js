import test from "node:test";
import assert from "node:assert/strict";
import { inferLastSeenAt, parseCandidateCardText, parseDetailText } from "../src/parse.js";
import { createCandidateFingerprint } from "../src/fingerprint.js";

test("parses visible candidate card text into lightweight index fields", () => {
  const text = `
王** 刚刚活跃
29岁 | 6年 | 本科 | 在职-月内到岗 | 20-30K
3d角色,高模,unity,次世代,bodypaint,虚幻引擎,低模,贴图,pbr,3d max,手绘,zbrush
期望 北京 · 游戏角色
职位 哔哩哔哩 · 3D设计师
院校 四川音乐学院成都学院 · 动画
maya photoshop painter 3d max u3d
`;

  const candidate = parseCandidateCardText(text);

  assert.equal(candidate.masked_name, "王**");
  assert.equal(candidate.age, 29);
  assert.equal(candidate.years_experience, "6年");
  assert.equal(candidate.education_level, "本科");
  assert.equal(candidate.expected_salary, "20-30K");
  assert.equal(candidate.job_status, "在职");
  assert.equal(candidate.active_status, "刚刚活跃");
  assert.ok(candidate.short_summary.includes("3d角色"));
  assert.ok(candidate.tags_json.includes("maya"));
});

test("parses detail text without preserving full resume content", () => {
  const detail = parseDetailText(`
伊** 30岁 6年 本科 在职-考虑机会
3年市场营销策划工作经验，熟悉新品上市营销、内容种草营销、电商营销。
工作经历
北京唱吧科技股份有限公司 | 市场营销 · 市场部
2020.12 - 2023.07
项目经验
双十一大促节企业品牌推广 | 营销经理
教育经历
吉林外国语大学 | 英语(英德双语) | 本科
活动策划 市场策划 内容营销
`);

  assert.ok(detail.detail_summary.includes("市场营销"));
  assert.ok(detail.detail_companies_json.some((item) => item.includes("北京唱吧")));
  assert.ok(detail.detail_schools_json.some((item) => item.includes("吉林外国语大学")));
  assert.ok(detail.detail_tags_json.includes("活动策划"));
});

test("builds stable compact fingerprint", () => {
  const candidate = parseCandidateCardText(`
伊** 30岁 | 6年 | 本科 | 在职-考虑机会 | 18-25K
3年市场营销策划工作经验
院校 吉林外国语大学 · 英语
`);

  const fingerprint = createCandidateFingerprint(candidate);
  assert.equal(fingerprint.length, 24);
});

test("parses one-line Chrome accessibility candidate card text", () => {
  const text = " 黄** 25岁 3年 本科 在职-考虑机会 15-25K 23年7月在大模型独角兽公司minimax开始实习 24年成功转正 211院校 技术岗招聘 社会招聘 校园招聘 期望 北京 HRBP 职位 MiniMax 招聘 院校 北京化工大学 人工智能";
  const candidate = parseCandidateCardText(text);

  assert.equal(candidate.masked_name, "黄**");
  assert.equal(candidate.age, 25);
  assert.equal(candidate.expected_city, "北京");
  assert.equal(candidate.expected_position, "HRBP");
  assert.equal(candidate.school, "北京化工大学 人工智能");
  assert.ok(candidate.short_summary.includes("大模型独角兽公司"));
});

test("keeps graduate year status from being parsed as work years", () => {
  const text = " 赛** 刚刚活跃 20岁 27年应届生 本科 在校-月内到岗 如deepseek-v4、智谱glm5、minimax m2.7 期望 北京 资产评估 职位 华泰证券 卖方分析师 院校 中央财经大学 金融工程";
  const candidate = parseCandidateCardText(text);

  assert.equal(candidate.years_experience, "27年应届生");
  assert.equal(candidate.short_summary, "如deepseek-v4、智谱glm5、minimax m2.7");
});

test("infers last seen timestamps from activity labels", () => {
  const collectedAt = new Date("2026-04-28T09:30:00.000Z");

  assert.equal(inferLastSeenAt("刚刚活跃", collectedAt), "2026-04-28T09:30:00.000Z");
  assert.equal(inferLastSeenAt("3日内活跃", collectedAt), "2026-04-25T09:30:00.000Z");
  assert.equal(inferLastSeenAt("2周内活跃", collectedAt), "2026-04-14T09:30:00.000Z");
  assert.equal(inferLastSeenAt("2月以上未活跃", collectedAt), "2026-02-28T09:30:00.000Z");
});

test("defaults missing activity label to two months inactive", () => {
  const candidate = parseCandidateCardText(
    "王** 30岁 5年 硕士 在职-考虑机会 面议 期望 北京 Java 职位 三快在线 AI Agent开发 院校 天津大学 计算机科学与技术"
  );

  assert.equal(candidate.active_status, "2月以上未活跃");
});
