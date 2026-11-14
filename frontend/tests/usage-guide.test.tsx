import { readFileSync, readdirSync } from "node:fs";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UsageGuideContent from "../src/UsageGuide";

afterEach(cleanup);

const disclosure = "Illustrative workflow, no production data";

describe("public workflow guide", () => {
  it("uses nine accessible, self-authored English schematics rather than production captures", () => {
    render(<UsageGuideContent onClose={vi.fn()} />);
    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(9);
    expect(screen.getAllByText(disclosure)).toHaveLength(9);
    expect(screen.getByText(/not a standalone end-to-end demo/)).toBeInTheDocument();
    const paths = new Set<string>();
    const authored = readdirSync("src/assets").filter((name) => /^guide-.*\.svg$/.test(name)).map((name) => readFileSync(`src/assets/${name}`, "utf8"));
    expect(authored).toHaveLength(9);
    for (const image of images) {
      expect(image).toHaveAccessibleName(expect.stringContaining("Schematic:"));
      expect(image).toHaveAccessibleName(expect.stringContaining(disclosure));
      const src = image.getAttribute("src")!;
      expect(src).toMatch(/^data:image\/svg\+xml;base64,/);
      expect(paths.has(src)).toBe(false);
      paths.add(src);
      const svg = atob(src.slice(src.indexOf(",") + 1));
      expect(authored).toContain(svg);
      expect(svg).toContain(disclosure);
      expect(svg).toContain("not a production screenshot");
      expect(svg).toMatch(/<title[^>]*>[^<]+<\/title>/);
      expect(svg).toMatch(/<desc[^>]*>[^<]+<\/desc>/);
      expect(svg).not.toMatch(/<image\b|<script\b|<foreignObject\b|(?:href|src)=/i);
    }
  });

  it("preserves all eight section links, instructions, examples and close action", () => {
    const onClose = vi.fn();
    const { container } = render(<UsageGuideContent onClose={onClose} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(8);
    for (const link of links) {
      const id = link.getAttribute("href")!.slice(1);
      const section = container.querySelector(`[id="${id}"]`);
      expect(section).not.toBeNull();
      expect(section?.querySelector("h3")).toHaveTextContent(/\S/);
      expect(section?.querySelectorAll("ol li").length).toBeGreaterThan(0);
      expect(section?.querySelectorAll("code").length).toBeGreaterThan(0);
    }
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
