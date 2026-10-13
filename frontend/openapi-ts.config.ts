import { defineConfig } from "@hey-api/openapi-ts";

const { OPENAPI_TS_OUTPUT } = process.env;
export const outputPath = OPENAPI_TS_OUTPUT ?? "./src/api/generated";

export default defineConfig({
  input: "./openapi.json",
  output: {
    path: outputPath,
    // Owner-approved #27: hey-api's bundled client/core runtime fails
    // exactOptionalPropertyTypes. Input-dependent types, SDK and query options
    // stay checked. check_generated_client.py verifies the actual file scope.
    header: (context) =>
      context.file
        ? context.defaultValue
        : [
            "// @ts-nocheck -- bundled runtime violates exactOptionalPropertyTypes",
            ...context.defaultValue,
          ],
  },
  plugins: [
    "@hey-api/client-fetch",
    "@hey-api/typescript",
    "@hey-api/sdk",
    {
      name: "@tanstack/react-query",
      queryOptions: true,
      mutationOptions: true,
      infiniteQueryOptions: true,
    },
  ],
});
