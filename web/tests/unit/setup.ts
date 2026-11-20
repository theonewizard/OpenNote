import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { IDBFactory } from "fake-indexeddb";
import "fake-indexeddb/auto";
import { afterAll, afterEach, beforeAll } from "vitest";

// Tests add their handlers with server.use(...createHandlers()); an unmocked request fails.
export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  globalThis.indexedDB = new IDBFactory(); // each test starts with an empty device cache
});
afterAll(() => server.close());
