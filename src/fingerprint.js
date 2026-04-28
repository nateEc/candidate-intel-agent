import { createHash } from "node:crypto";

export function createCandidateFingerprint(candidate) {
  const parts = [
    candidate.source_platform || "boss_zhipin",
    candidate.masked_name,
    candidate.age,
    candidate.years_experience,
    candidate.education_level,
    candidate.school,
    candidate.expected_city,
    candidate.expected_position,
    candidate.expected_salary,
    candidate.short_summary
  ]
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean);

  return createHash("sha256").update(parts.join("|")).digest("hex").slice(0, 24);
}
