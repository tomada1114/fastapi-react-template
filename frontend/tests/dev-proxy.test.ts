import { describe, expect, it, vi } from "vitest";

async function config() {
  vi.resetModules();
  return (await import("../vite.config.ts")).default;
}

describe("development API proxy", () => {
  it("routes API and health requests to the default loopback backend", async () => {
    vi.stubEnv("MY_APP_API_PORT", undefined);
    vi.stubEnv("VITE_PORT", undefined);

    const actual = await config();

    expect(actual.server).toMatchObject({
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/healthz": "http://127.0.0.1:8000",
      },
    });
  });

  it("uses explicit ports for an owned development pair", async () => {
    vi.stubEnv("MY_APP_API_PORT", "51001");
    vi.stubEnv("VITE_PORT", "51002");

    const actual = await config();

    expect(actual.server).toMatchObject({
      port: 51002,
      strictPort: true,
      proxy: {
        "/api": "http://127.0.0.1:51001",
        "/healthz": "http://127.0.0.1:51001",
      },
    });
  });

  it.each(["8000@external.invalid", "0", "65536"])(
    "rejects a non-port API target: %s",
    async (port) => {
      vi.stubEnv("MY_APP_API_PORT", port);

      await expect(config()).rejects.toThrow(/MY_APP_API_PORT.*1-65535/);
    },
  );
});
