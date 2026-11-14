import { describe, expect, it, vi } from "vitest";
import { canvas, map, polygon } from "leaflet";
import { disposeTestBrowser } from "../src/test-setup";

const nextFrame = () => new Promise<number>((resolve) => requestAnimationFrame(resolve));

describe("browser test environment", () => {
  it("uses UTC in test workers regardless of the invoking shell timezone", () => {
    expect(new Date("2026-07-31T01:30:00Z").getTimezoneOffset()).toBe(0);
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe("UTC");
  });

  it("returns one inspectable 2D context per canvas without inventing unknown methods", () => {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d")!;
    expect(context.canvas).toBe(canvas);
    expect(canvas.getContext("2d")).toBe(context);
    expect(document.createElement("canvas").getContext("2d")).not.toBe(context);
    expect(canvas.getContext("webgl")).toBeNull();
    expect((context as unknown as Record<string, unknown>).nonexistentMethod).toBeUndefined();
    context.clearRect(1, 2, 3, 4);
    expect(context.clearRect).toHaveBeenCalledWith(1, 2, 3, 4);
  });

  it("executes live frames and respects explicit cancellation", async () => {
    const live = vi.fn();
    const cancelled = vi.fn();
    requestAnimationFrame(live);
    const handle = requestAnimationFrame(cancelled);
    cancelAnimationFrame(handle);
    await nextFrame();
    expect(live).toHaveBeenCalledOnce();
    expect(live).toHaveBeenCalledWith(expect.any(Number));
    expect(cancelled).not.toHaveBeenCalled();
  });

  it("cancels Leaflet's orphaned redraw after a synchronous fitBounds and map teardown", async () => {
    const container = document.createElement("div");
    Object.defineProperties(container, {
      clientWidth: { value: 512 },
      clientHeight: { value: 512 },
    });
    document.body.appendChild(container);
    const renderer = canvas();
    const instance = map(container, { renderer, zoomAnimation: false }).setView([35.1, 129.1], 12);
    try {
      polygon([[35.1, 129.1], [35.11, 129.1], [35.11, 129.11]]).addTo(instance);
      const internals = renderer as unknown as { _redrawRequest: number | null };
      expect(internals._redrawRequest).toEqual(expect.any(Number));
      instance.fitBounds([[35.1, 129.1], [35.11, 129.11]], { animate: false });
      // Leaflet redraws now, clears its handle, but leaves the old frame queued.
      expect(internals._redrawRequest).toBeNull();
    } finally {
      instance.remove();
      container.remove();
    }
    disposeTestBrowser();
    // Any uncancelled orphan would throw against the deleted _ctx here, and
    // Vitest's unchanged unhandled-error reporting would fail this test run.
    await nextFrame();
  });

  it("disposes pending frames with the test DOM rather than letting them cross test boundaries", async () => {
    const stale = vi.fn();
    requestAnimationFrame(stale);
    disposeTestBrowser();
    await nextFrame();
    expect(stale).not.toHaveBeenCalled();
  });
});
