import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom no implementa matchMedia — el Dashboard lo usa para detectar orientación
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// jsdom tampoco implementa Notification
if (!("Notification" in window)) {
  window.Notification = {
    permission: "denied",
    requestPermission: vi.fn().mockResolvedValue("denied"),
  };
}
