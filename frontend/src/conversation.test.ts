import { describe, expect, it } from "vitest";

import {
  conversationTitle,
  displayRegionName,
  displayRegionText,
  gradesFromPrompt,
  isExplicitReportCommand,
  isReportRequest,
  resolveRegionFromPrompt,
  resolveRegionsFromPrompt,
  spatialOperationFromPrompt,
} from "./conversation";

describe("resolveRegionFromPrompt", () => {
  it("matches a conversational district name to its actual disambiguated DB label", () => {
    expect(resolveRegionFromPrompt(
      "부산 남구 보고서 작성해줘",
      [{ name: "부산광역시", districts: ["남구(부산)", "수영구"] }],
      "부산광역시",
    )).toEqual({
      sido: "부산광역시",
      district: "남구(부산)",
      label: "부산광역시 남구(부산)",
    });
  });
});

describe("resolveRegionsFromPrompt", () => {
  it("finds every district named in a comparison request", () => {
    expect(resolveRegionsFromPrompt(
      "수영구와 해운대구를 비교해줘",
      [{ name: "부산광역시", districts: ["수영구", "해운대구"] }],
    )).toEqual([
      { sido: "부산광역시", district: "수영구", label: "부산광역시 수영구" },
      { sido: "부산광역시", district: "해운대구", label: "부산광역시 해운대구" },
    ]);
  });

  it("resolves a province-wide baseline and its district without matching a namesake district", () => {
    expect(resolveRegionsFromPrompt(
      "강원도 전체 대비 / 강원도 고성군은 어느 수준이야",
      [
        { name: "강원특별자치도", districts: ["고성군(강원)", "속초시"] },
        { name: "경상남도", districts: ["고성군(경남)"] },
      ],
    )).toEqual([
      { sido: "강원특별자치도", district: "", label: "강원특별자치도" },
      { sido: "강원특별자치도", district: "고성군(강원)", label: "강원특별자치도 고성군(강원)" },
    ]);
  });
});

describe("gradesFromPrompt", () => {
  it("recognizes comma-separated grades when only the last value has the grade suffix", () => {
    expect(gradesFromPrompt("4,5등급만 남겨줘", [])).toEqual(["4", "5"]);
  });
});

describe("conversationTitle", () => {
  it("summarizes the question intent instead of copying the request wording", () => {
    expect(conversationTitle("수영구 고위험 지역을 자세히 알려줘")).toBe("수영구 고위험 지역");
  });
});

describe("isReportRequest", () => {
  it("distinguishes explicit slash commands from natural report requests", () => {
    expect(isExplicitReportCommand("/보고서작성")).toBe(true);
    expect(isExplicitReportCommand("/보고서 작성")).toBe(true);
    expect(isExplicitReportCommand("보고서를 만들어줘")).toBe(false);
  });

  it("recognizes the compact report command", () => {
    expect(isReportRequest("/보고서작성")).toBe(true);
  });

  it("does not create a report when the user explicitly negates the action", () => {
    expect(isReportRequest("보고서는 만들지 말고 핵심만 요약해줘")).toBe(false);
    expect(isReportRequest("보고서를 생성하지 않고 결과만 알려줘")).toBe(false);
  });
});

describe("region display names", () => {
  it("removes database disambiguation suffixes without changing the raw region", () => {
    const raw = "강원특별자치도 고성군(강원)";
    expect(displayRegionName(raw)).toBe("강원특별자치도 고성군");
    expect(displayRegionText("고성군(강원)의 위험지역입니다.", [raw])).toBe("고성군의 위험지역입니다.");
    expect(raw).toBe("강원특별자치도 고성군(강원)");
  });
});

describe("spatialOperationFromPrompt", () => {
  it("routes a multi-factor grade question to the deterministic spatial filter", () => {
    expect(spatialOperationFromPrompt("강풍 4·5등급이면서 고령인구 4·5등급 격자를 찾아줘"))
      .toEqual({ kind: "filter" });
  });

  it("extracts buffer and adjacency operations for a named grid", () => {
    expect(spatialOperationFromPrompt("SYG100001 격자 주변 500m를 분석해줘"))
      .toEqual({ kind: "neighborhood", ftrId: "SYG100001", distanceM: 500 });
    expect(spatialOperationFromPrompt("SYG100001 격자와 인접한 격자를 보여줘"))
      .toEqual({ kind: "neighborhood", ftrId: "SYG100001", distanceM: 0 });
  });

  it("routes concentration questions to hotspot analysis", () => {
    expect(spatialOperationFromPrompt("고위험 격자가 몰린 핫스팟을 찾아줘"))
      .toEqual({ kind: "hotspot" });
  });
});
