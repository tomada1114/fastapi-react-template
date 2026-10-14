import path from "node:path";

/** The repository root, where `just`, `uv`, and `pnpm` commands run from. */
export const REPOSITORY_ROOT = path.resolve(import.meta.dirname, "..");

const MISSING =
  "E2E_DATABASE_URL, E2E_API_PORT and E2E_WEB_PORT are set by `just e2e`; run that instead";

/** What `just e2e` hands this suite: a throwaway database, two free ports, and Just. */
export interface E2eRun {
  databaseUrl: string;
  apiPort: number;
  webPort: number;
  just: string;
}

/** An environment variable's value, with an empty one counted as unset. */
export function variable(name: string): string | undefined {
  const value = process.env[name];
  return value === undefined || value === "" ? undefined : value;
}

function port(name: string, value: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`${name} must be an integer port in 1-65535, got ${value}`);
  }
  return parsed;
}

/**
 * Read the run `just e2e` set up, or fail naming the recipe: without it there is
 * no throwaway database, and the servers would fall back to the developer's.
 */
export function e2eRun(): E2eRun {
  const names = ["E2E_DATABASE_URL", "E2E_API_PORT", "E2E_WEB_PORT", "JUST"];
  const missing = names.filter((name) => variable(name) === undefined);
  const [databaseUrl, apiPort, webPort, just] = names.map(variable);
  if (
    missing.length > 0 ||
    databaseUrl === undefined ||
    apiPort === undefined ||
    webPort === undefined ||
    just === undefined
  ) {
    throw new Error(`${MISSING} (unset: ${missing.join(", ")})`);
  }
  return {
    databaseUrl,
    apiPort: port("E2E_API_PORT", apiPort),
    webPort: port("E2E_WEB_PORT", webPort),
    just,
  };
}

/**
 * Every current Settings field (backend/src/my_app/settings.py) with this run's
 * value. Settings reads the environment before backend/.env, so a field set here
 * can never come from the developer's dotenv file; a field left out could.
 * tests/test_just_e2e.py fails when this list and Settings disagree.
 */
export function settingsEnvironment(databaseUrl: string): Record<string, string> {
  return {
    MY_APP_DATABASE_URL: databaseUrl,
    MY_APP_CORS_ORIGINS: "",
    MY_APP_LOG_LEVEL: "INFO",
    MY_APP_LOG_FORMAT: "text",
  };
}

/** This process's environment without any inherited MY_APP_* key, plus `settings`. */
export function isolatedEnvironment(
  settings: Record<string, string>,
): Record<string, string> {
  const inherited = Object.entries(process.env).filter(
    (entry): entry is [string, string] =>
      entry[1] !== undefined && !entry[0].startsWith("MY_APP_"),
  );
  return { ...Object.fromEntries(inherited), ...settings };
}

/** Quote one word for the POSIX shell Playwright runs a webServer command in. */
export function shellQuote(word: string): string {
  return `'${word.replaceAll("'", `'\\''`)}'`;
}
