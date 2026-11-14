import type { Region } from "./api";

export type SpatialPromptOperation =
  | { kind: "filter" }
  | { kind: "hotspot" }
  | { kind: "neighborhood"; ftrId: string; distanceM: number };

const SPATIAL_METRIC_PATTERN = /(종합\s*위험|위해성|노출성|취약성|강풍|강우|해일|파랑|해수면\s*상승|고령인구|인구|건물|도로|농경지|시설재배|양식장|어항|항만|침수면적|지하|반지하|문화재|대피소|급경사지|침식지역)/g;

export function spatialOperationFromPrompt(prompt: string): SpatialPromptOperation | null {
  const neighborhood = prompt.match(/([A-Za-z0-9_-]+)\s*격자.{0,20}?(?:주변\s*)?(?:(\d+(?:\.\d+)?)\s*(?:m|미터)(?:\s*이내)?|인접)/i);
  if (neighborhood) {
    return {
      kind: "neighborhood",
      ftrId: neighborhood[1],
      distanceM: /인접/.test(neighborhood[0]) ? 0 : Number(neighborhood[2]),
    };
  }
  if (/(핫스팟|군집|격자.{0,10}(몰린|밀집))/.test(prompt)) return { kind: "hotspot" };
  const metrics = prompt.match(SPATIAL_METRIC_PATTERN) || [];
  if (metrics.length && /[1-5](?:\s*[·,~\-]\s*[1-5])?\s*등급/.test(prompt)
    && /(격자|공간|지도|필터|찾아|표시|보여)/.test(prompt)) {
    return { kind: "filter" };
  }
  return null;
}

export type ResolvedRegion = {
  sido: string;
  district: string;
  label: string;
};

function sidoAlias(name: string) {
  return name.replace(/(특별자치도|특별자치시|광역시|특별시|도)$/, "");
}

function districtIsMentioned(prompt: string, name: string) {
  const alias = name.replace(/\([^)]*\)$/, "");
  return prompt.includes(name) || prompt.includes(alias);
}

export function displayRegionName(value: string) {
  return value.replace(/\s*\([^)]*\)\s*$/, "").trim();
}

export function displayRegionText(text: string, rawRegions: string[]) {
  const variants = rawRegions.flatMap((region) => {
    const parts = region.split(" ");
    return [region, parts.length > 1 ? parts.slice(1).join(" ") : ""];
  }).filter((value) => /\([^)]*\)$/.test(value));
  return [...new Set(variants)]
    .sort((left, right) => right.length - left.length)
    .reduce((current, raw) => current.replaceAll(raw, displayRegionName(raw)), text);
}

export function resolveRegionFromPrompt(
  prompt: string,
  regions: Region[],
  currentSido: string,
): ResolvedRegion | null {
  const mentionedSido = regions.find((item) => (
    prompt.includes(item.name) || prompt.includes(sidoAlias(item.name))
  ));

  if (mentionedSido) {
    const district = mentionedSido.districts.find((name) => districtIsMentioned(prompt, name)) || "";
    return {
      sido: mentionedSido.name,
      district,
      label: [mentionedSido.name, district].filter(Boolean).join(" "),
    };
  }

  const districtMatches = regions.flatMap((item) => (
    item.districts
      .filter((name) => districtIsMentioned(prompt, name))
      .map((district) => ({ sido: item.name, district }))
  ));
  if (!districtMatches.length) return null;

  const match = districtMatches.find((item) => item.sido === currentSido)
    || (districtMatches.length === 1 ? districtMatches[0] : null);
  if (!match) return null;
  return { ...match, label: `${match.sido} ${match.district}` };
}

export function resolveRegionsFromPrompt(prompt: string, regions: Region[]): ResolvedRegion[] {
  const mentionedProvinces = regions.filter((item) => (
    prompt.includes(item.name) || prompt.includes(sidoAlias(item.name))
  ));
  const provinceMatches = mentionedProvinces
    .filter((item) => {
      const alias = sidoAlias(item.name);
      return [`${item.name} 전체`, `${alias} 전체`, `${alias}도 전체`]
        .some((value) => prompt.includes(value));
    })
    .map((item) => ({ sido: item.name, district: "", label: item.name }));
  const districtScope = mentionedProvinces.length ? mentionedProvinces : regions;
  const districtMatches = districtScope.flatMap((item) => item.districts
    .filter((district) => districtIsMentioned(prompt, district))
    .map((district) => ({
      sido: item.name,
      district,
      label: `${item.name} ${district}`,
    })));
  const matches = [...provinceMatches, ...districtMatches];
  return matches.filter((match, index) => (
    matches.findIndex((candidate) => candidate.label === match.label) === index
  ));
}

export function isExplicitReportCommand(prompt: string) {
  return /^\/보고서\s*작성(?:\s|$)/.test(prompt.trim());
}

export function isReportRequest(prompt: string) {
  const normalized = prompt.trim();
  if (isExplicitReportCommand(normalized)) return true;
  if (/(보고서.{0,12}(작성|만들|생성).{0,4}(?:하지|지\s*말|지\s*않)|(작성|만들|생성).{0,4}(?:하지|지\s*말|지\s*않).{0,12}보고서)/.test(normalized)) {
    return false;
  }
  return /(보고서.{0,12}(작성|만들|생성)|(작성|만들|생성).{0,12}보고서)/.test(normalized);
}

export function isRegionSelectionRequest(prompt: string) {
  return /((분석|보고서|대상)?\s*지역.{0,15}(변경|바꿔|설정|선택)|(변경|바꿔|설정|선택).{0,15}지역)/.test(prompt);
}

export function gradesFromPrompt(prompt: string, current: string[]) {
  if (/(전체\s*등급|등급\s*전체|등급\s*필터\s*해제)/.test(prompt)) return [];
  const gradeLists = [...prompt.matchAll(
    /((?:[1-5]\s*(?:[,，·/]|및|와|과)\s*)+[1-5])\s*등급/g,
  )].flatMap((match) => match[1].match(/[1-5]/g) || []);
  if (gradeLists.length) return [...new Set(gradeLists)].sort();
  if (/(고위험|4\s*[·~\-]?\s*5\s*등급)/.test(prompt)) return ["4", "5"];
  const mentioned = [...prompt.matchAll(/([1-5])\s*등급/g)].map((match) => match[1]);
  return mentioned.length ? [...new Set(mentioned)].sort() : current;
}

export function conversationTitle(prompt: string) {
  const original = prompt.trim().replace(/\s+/g, " ");
  let title = original
    .replace(/^\//, "")
    .replace(/[?!。.]+$/g, "")
    .replace(/\s*(?:자세히\s*)?(?:알려|보여|설명|분석|비교|조회|확인|작성|생성|만들)(?:해)?(?:줘|주세요|주라)?$/g, "")
    .replace(/([가-힣]+)[을를은는이가]$/g, "$1")
    .trim();
  if (!title) title = original.replace(/^\//, "").replace(/[?!。.]+$/g, "");
  const characters = Array.from(title);
  return characters.length > 44 ? `${characters.slice(0, 43).join("")}…` : title;
}

function revisionKey(value: string) {
  return value.replace(/^\d+(?:\.\d+)*\s*/, "").replace(/[^가-힣A-Za-z]/g, "").toLowerCase();
}

export function isRevisionRequest(prompt: string) {
  return /(수정|다시\s*작성|재작성|줄여|늘려|보완)/.test(prompt);
}

export function resolveRevisionSection(prompt: string, markdown: string) {
  if (!isRevisionRequest(prompt)) return null;
  const promptKey = revisionKey(prompt);
  const headings = [...markdown.matchAll(/^#{2,3}\s+(.+?)\s*$/gm)].map((match) => match[1]);
  return headings.find((heading) => {
    const key = revisionKey(heading);
    return key.length >= 2 && promptKey.includes(key);
  }) || null;
}
