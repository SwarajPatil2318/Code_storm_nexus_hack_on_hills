import fs from "node:fs/promises";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";
const schema = new URL("../packages/contracts/openapi.json", import.meta.url);
const generated = new URL("../apps/web/src/lib/api.generated.ts", import.meta.url);
const expected = COMMENT_HEADER + astToString(await openapiTS(schema));
const actual = await fs.readFile(generated, "utf8");
if (actual !== expected) {
  throw new Error("Generated TypeScript contract drift detected; run npm run contracts:generate");
}
console.log("Generated TypeScript contracts match the OpenAPI snapshot");
