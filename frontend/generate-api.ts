import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createClient } from "@hey-api/openapi-ts";
import config, { outputPath } from "./openapi-ts.config.ts";

await createClient(await config);

// hey-api 0.99.0 emits two suppressions in the infinite helper: TanStack
// requires pagination defaults, and JavaScript treats null as an object.
// Correct this pinned output during generation; fail when its shape changes
// so an upgrade requires review instead of silently retaining suppressions.
const path = join(outputPath, "@tanstack/react-query.gen.ts");
const source = await readFile(path, "utf8");
const branch = "typeof pageParam === 'object' ? pageParam";
const query = "queryFn: async ({ pageParam, queryKey, signal }) => {";
const helpers = source.split(branch).length - 1;
if (
  source.split("// @ts-ignore").length - 1 !== helpers * 2 ||
  source.split(query).length - 1 !== helpers
) {
  throw new Error("Unexpected infinite helper output; review the generator correction");
}
await writeFile(
  path,
  source
    .replaceAll(/^[ \t]*\/\/ @ts-ignore\n/gm, "")
    .replaceAll(branch, `pageParam !== null && ${branch}`)
    .replaceAll(
      query,
      // Consumers supply their response-specific next-page rule when using
      // this helper; these defaults represent a single initial page.
      `initialPageParam: {},\n        getNextPageParam: () => undefined,\n        ${query}`,
    ),
);
