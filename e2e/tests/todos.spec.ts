import { spawnSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import {
  e2eRun,
  isolatedEnvironment,
  REPOSITORY_ROOT,
  settingsEnvironment,
} from "../environment.ts";

const TITLE = "Buy milk (e2e)";
const EMPTY_STATE = "No to-dos yet. Add one above.";

function todoList(page: Page) {
  return page.getByRole("list", { name: "To-dos" });
}

function todoItem(page: Page) {
  return todoList(page).getByRole("listitem").filter({ hasText: TITLE });
}

/**
 * Ask a process of its own whether the to-do is in the database. A reload alone
 * cannot tell a database from an API that keeps to-dos in memory.
 */
function expectStoredAndCompleted(id: string) {
  const { databaseUrl } = e2eRun();
  const result = spawnSync(
    "uv",
    ["run", "--locked", "python", "e2e/verify_persistence.py", databaseUrl, id, TITLE],
    {
      cwd: REPOSITORY_ROOT,
      env: isolatedEnvironment(settingsEnvironment(databaseUrl)),
      encoding: "utf8",
    },
  );
  expect(result.error, "could not start the persistence check").toBeUndefined();
  expect(result.status, `${result.stdout}${result.stderr}`).toBe(0);
  console.log(result.stdout.trim());
}

test("a to-do goes from the screen to the database and away again", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText(EMPTY_STATE)).toBeVisible();

  await page.getByLabel("Title", { exact: true }).fill(TITLE);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/todos",
  );
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const body: unknown = await response.json();
  expect(body).toMatchObject({
    id: expect.any(String),
    title: TITLE,
    completed: false,
  });
  const { id } = body as { id: string };
  await expect(todoItem(page)).toBeVisible();

  await page.reload();
  await expect(todoItem(page)).toBeVisible();

  await page.getByRole("button", { name: `Complete ${TITLE}`, exact: true }).click();
  await expect(todoItem(page).getByText("Completed", { exact: true })).toBeVisible();

  await page.reload();
  await expect(todoItem(page).getByText("Completed", { exact: true })).toBeVisible();

  expectStoredAndCompleted(id);

  await page.getByRole("button", { name: `Delete ${TITLE}`, exact: true }).click();
  await expect(todoItem(page)).toHaveCount(0);

  await page.reload();
  await expect(page.getByText(EMPTY_STATE)).toBeVisible();
  await expect(todoItem(page)).toHaveCount(0);
});
