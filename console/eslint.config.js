import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

// Model-written text must never become markup: no raw HTML from React or the DOM.
const RAW_HTML = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: "Render text, never raw HTML.",
  },
  {
    selector: "MemberExpression[property.name=/^(innerHTML|outerHTML|insertAdjacentHTML)$/]",
    message: "Render text, never raw HTML.",
  },
];

export default tseslint.config(
  { ignores: ["dist", "src/api-types.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: { globals: globals.browser },
    rules: { "no-restricted-syntax": ["error", ...RAW_HTML] },
  },
);
