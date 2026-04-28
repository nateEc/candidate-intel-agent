export const DEFAULT_POLICY = Object.freeze({
  storeFullResumeText: false,
  storeContactInfo: false,
  maxSummaryChars: 220,
  maxDetailSummaryChars: 360
});

const PHONE_RE = /(?:\+?86[- ]?)?1[3-9]\d{9}/g;
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const WECHAT_RE = /(?:微信|wechat|wx|VX|v信)[:：\s]*[A-Za-z][-_A-Za-z0-9]{5,19}/g;

export function redactSensitiveText(value) {
  if (!value) return value;

  return String(value)
    .replace(PHONE_RE, "[redacted-phone]")
    .replace(EMAIL_RE, "[redacted-email]")
    .replace(WECHAT_RE, "[redacted-wechat]");
}

export function truncateText(value, maxLength) {
  const text = redactSensitiveText(String(value || "").replace(/\s+/g, " ").trim());
  if (!text || text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}

export function compactArray(values, limit = 12) {
  return [...new Set(values.map((item) => String(item || "").trim()).filter(Boolean))].slice(0, limit);
}
