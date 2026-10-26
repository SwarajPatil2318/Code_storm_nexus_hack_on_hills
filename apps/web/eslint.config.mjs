import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";
export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  globalIgnores([
    ".next/**",
    ".next-demo/**",
    ".next-assurance/**",
    ".next-resource/**",
    ".next-timing/**",
    ".next-center/**",
    ".next-ui/**",
    "next-env.d.ts",
    "src/lib/api.generated.ts",
  ]),
]);
