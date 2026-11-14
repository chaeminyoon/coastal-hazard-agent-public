import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const nginx = readFileSync("../deploy/nginx.conf", "utf8");

describe("deployment cache policy", () => {
  it("forces the application HTML to revalidate after a deployment", () => {
    expect(nginx).toMatch(
      /location = \/\s*\{[^}]*expires -1;/s,
    );
  });
});
