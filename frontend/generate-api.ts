import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createClient } from "@hey-api/openapi-ts";
import config, { outputPath } from "./openapi-ts.config.ts";

await createClient(await config);

// hey-api 0.99.0 emits two suppressions in each infinite helper: TanStack
// requires pagination defaults, and JavaScript treats null as an object.
// Its query keys also discard an explicitly empty base URL with ||.
// Correct this pinned output during generation; fail when its shape changes
// so an upgrade requires review instead of silently retaining suppressions.
const path = join(outputPath, "@tanstack/react-query.gen.ts");
const source = await readFile(path, "utf8");
const branch = "typeof pageParam === 'object' ? pageParam";
const query = "queryFn: async ({ pageParam, queryKey, signal }) => {";
const baseUrl = "baseUrl: options?.baseUrl ||";
const helpers = source.split(branch).length - 1;
if (
  source.split("// @ts-ignore").length - 1 !== helpers * 2 ||
  source.split(query).length - 1 !== helpers ||
  !source.includes(baseUrl)
) {
  throw new Error("Unexpected infinite helper output; review the generator correction");
}
await writeFile(
  path,
  source
    .replaceAll(/^[ \t]*\/\/ @ts-ignore\n/gm, "")
    .replaceAll(baseUrl, "baseUrl: options?.baseUrl ??")
    .replaceAll(branch, `pageParam !== null && ${branch}`)
    .replaceAll(
      query,
      // Consumers supply their response-specific next-page rule when using
      // this helper; these defaults represent a single initial page.
      `initialPageParam: {},\n        getNextPageParam: () => undefined,\n        ${query}`,
    ),
);

// A 204 has no representation: the SDK's generated void contract must not
// receive null (automatic stream parsing) or {} (explicit JSON parsing).
// Keep format-specific parsing for other zero-length successful responses.
const runtimePath = join(outputPath, "client/client.gen.ts");
const runtime = await readFile(runtimePath, "utf8");
const emptyResponse =
  "if (response.status === 204 || response.headers.get('Content-Length') === '0') {";
if (runtime.split(emptyResponse).length !== 2) {
  throw new Error("Unexpected empty-response output; review the generator correction");
}
await writeFile(
  runtimePath,
  runtime.replace(
    emptyResponse,
    `if (response.status === 204) {
          return opts.responseStyle === 'data'
            ? undefined
            : { data: undefined, ...result };
        }

        if (response.headers.get('Content-Length') === '0') {`,
  ),
);
