export async function extractVisibleCandidateCards(page, limit) {
  return page.evaluate((maxItems) => {
    const salaryRe = /\b\d{1,3}(?:-\d{1,3})?K(?:·\d{1,2}薪)?\b/i;
    const ageRe = /\d{2}岁/;

    function isVisible(element) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        style.visibility !== "hidden" &&
        style.display !== "none" &&
        rect.width >= 420 &&
        rect.height >= 80 &&
        rect.height <= 360 &&
        rect.bottom > 0 &&
        rect.top < window.innerHeight &&
        rect.right > 0 &&
        rect.left < window.innerWidth
      );
    }

    function normalize(text) {
      return String(text || "")
        .replace(/\r/g, "")
        .split("\n")
        .map((line) => line.replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join("\n");
    }

    function looksLikeCard(element) {
      const text = normalize(element.innerText);
      if (!salaryRe.test(text) || !ageRe.test(text)) return false;
      if (/学历要求|院校要求|经验要求|年龄要求|其他筛选/.test(text)) return false;
      const childMatches = [...element.children].filter((child) => {
        const childText = normalize(child.innerText);
        return isVisible(child) && salaryRe.test(childText) && ageRe.test(childText);
      });
      return childMatches.length === 0;
    }

    const elements = [...document.querySelectorAll("li, article, section, div")];
    const cards = [];
    const seen = new Set();

    for (const element of elements) {
      if (!isVisible(element) || !looksLikeCard(element)) continue;

      const text = normalize(element.innerText);
      if (seen.has(text)) continue;
      seen.add(text);

      const rect = element.getBoundingClientRect();
      cards.push({
        index: cards.length,
        text,
        rect: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        }
      });

      if (cards.length >= maxItems) break;
    }

    return cards;
  }, limit);
}

export async function extractLikelyDialogText(page) {
  return page.evaluate(() => {
    function isVisible(element) {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width >= 500 &&
        rect.height >= 300 &&
        rect.bottom > 0 &&
        rect.top < window.innerHeight &&
        rect.right > 0 &&
        rect.left < window.innerWidth
      );
    }

    function normalize(text) {
      return String(text || "")
        .replace(/\r/g, "")
        .split("\n")
        .map((line) => line.replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join("\n");
    }

    const candidates = [...document.querySelectorAll('[role="dialog"], .dialog, .modal, .resume, div')]
      .filter(isVisible)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const text = normalize(element.innerText);
        const fixedLike = style.position === "fixed" || style.position === "absolute";
        return {
          text,
          rect: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height)
          },
          score: text.length + (fixedLike ? 5000 : 0) - Math.abs(rect.width - 920)
        };
      })
      .filter((item) => item.text.length >= 120)
      .sort((a, b) => b.score - a.score);

    return candidates[0] || null;
  });
}
