import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

Element.prototype.scrollIntoView = () => undefined;

// jsdom has no rasterizer. Model only the 2D operations used by Leaflet, not
// arbitrary properties/methods. Each canvas owns one stable, inspectable context.
const contexts = new WeakMap<HTMLCanvasElement, CanvasRenderingContext2D>();
(HTMLCanvasElement.prototype as unknown as { getContext: unknown }).getContext = function getContext(
  this: HTMLCanvasElement,
  contextId: string,
) {
  if (contextId !== "2d") return null;
  let context = contexts.get(this);
  if (!context) {
    context = {
      canvas: this,
      globalAlpha: 1,
      fillStyle: "#000000",
      strokeStyle: "#000000",
      lineWidth: 1,
      lineCap: "butt",
      lineJoin: "miter",
      save: vi.fn(),
      restore: vi.fn(),
      scale: vi.fn(),
      translate: vi.fn(),
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      rect: vi.fn(),
      clip: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      setLineDash: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    contexts.set(this, context);
  }
  return context;
};

// Preserve jsdom's real asynchronous frame execution and cancellation. Leaflet
// captures these functions at import time. Track every pending handle because a
// synchronous Canvas._redraw() can clear _redrawRequest without cancelling the
// already queued callback. That orphan must not outlive a disposed test DOM.
const requestFrame = window.requestAnimationFrame.bind(window);
const cancelFrame = window.cancelAnimationFrame.bind(window);
const pendingFrames = new Set<number>();
window.requestAnimationFrame = (callback: FrameRequestCallback) => {
  const handle = requestFrame((timestamp) => {
    pendingFrames.delete(handle);
    callback(timestamp); // Do not catch errors: jsdom/Vitest must report them.
  });
  pendingFrames.add(handle);
  return handle;
};
window.cancelAnimationFrame = (handle: number) => {
  pendingFrames.delete(handle);
  cancelFrame(handle);
};

export function disposeTestBrowser() {
  // Unmount first so React/Leaflet run their normal lifecycle and cancel their
  // own work. Then dispose any orphaned frames, without running them against
  // destroyed canvas contexts or leaking them into the next test.
  cleanup();
  for (const handle of pendingFrames) cancelFrame(handle);
  pendingFrames.clear();
}

afterEach(disposeTestBrowser);
