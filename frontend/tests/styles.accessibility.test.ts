import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync("src/styles.css", "utf8");

describe("accessible typography", () => {
  it("uses local system fonts without requiring bundled or remote font downloads", () => {
    expect(styles).not.toMatch(/@import\s+url\(["']?https?:\/\//);
    expect(styles).not.toMatch(/@font-face|Pretendard|\.(?:woff2?|ttf|otf)\b/i);
    expect(styles).toMatch(/--font-sans:\s*system-ui,[^;]*"Apple SD Gothic Neo",\s*"Malgun Gothic",\s*sans-serif;/);
    expect(styles).toMatch(/:root\s*\{[^}]*font-family:\s*var\(--font-sans\)/s);
    expect(styles).toMatch(/html,\s*body,\s*body \*\s*\{[^}]*font-family:\s*var\(--font-sans\)\s*!important/s);
    expect(styles).toMatch(/button,\s*input,\s*textarea,\s*select\s*\{[^}]*font:\s*inherit/s);
  });

  it("restores the 18081 global 16px Regular typography contract", () => {
    expect(styles).toMatch(
      /html,\s*body,\s*body \*\s*\{[^}]*font-size:\s*16px\s*!important[^}]*font-weight:\s*400\s*!important[^}]*line-height:\s*1\.5\s*!important/s,
    );
  });

  it("keeps semantic emphasis Bold and headings within the 1.25 to 1.5 scale", () => {
    expect(styles).toMatch(
      /body :where\(strong, b, h1, h2, h3, h4, h5, h6, th\)\s*\{[^}]*font-weight:\s*700\s*!important/s,
    );
    expect(styles).toMatch(
      /body :where\(h1, h3, h4, h5, h6\)\s*\{[^}]*font-size:\s*20px\s*!important/s,
    );
    expect(styles).toMatch(/body h2\s*\{[^}]*font-size:\s*24px\s*!important/s);
  });

  it("overlays the spatial studio before the chat workspace becomes unreadably narrow", () => {
    expect(styles).toMatch(
      /@media \(min-width: 921px\) and \(max-width: 1500px\)\s*\{[\s\S]*?\.chat-main\.spatial-active\s*\{[^}]*margin-right:\s*0/s,
    );
    expect(styles).toMatch(
      /@media \(min-width: 921px\) and \(max-width: 1500px\)\s*\{[\s\S]*?\.composer-dock\.spatial-active\s*\{[^}]*right:\s*0/s,
    );
  });

  it("keeps the header region fields and conversation controls on one readable row", () => {
    expect(styles).toMatch(
      /\.region-picker\.equal-columns\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s,
    );
    expect(styles).toMatch(
      /\.query-actions\s*>\s*button\s*\{[^}]*display:\s*inline-flex[^}]*min-height:\s*40px[^}]*white-space:\s*nowrap/s,
    );
    expect(styles).toMatch(
      /\.thinking\s*>\s*button\s*\{[^}]*display:\s*inline-flex[^}]*min-height:\s*40px[^}]*white-space:\s*nowrap/s,
    );
  });
});
