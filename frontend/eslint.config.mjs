import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright test files: not React code, and Playwright's own fixture
    // API parameter named `use` otherwise false-positives against the
    // react-hooks/rules-of-hooks rule.
    "tests/**",
  ]),
]);

export default eslintConfig;
