/**
 * The few places where a JavaScript string built-in and its Python counterpart differ,
 * and the rendering contract was written against Python. Not part of the public surface.
 */

/**
 * Python's `str.split()`, `str.strip()` and `\s` whitespace: JS `\s` minus U+FEFF, plus
 * U+001C to U+001F and U+0085.
 */
export const PY_WS =
  "\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";

const WS_RUN = new RegExp(`[${PY_WS}]+`, "u");
const WS_ONLY = new RegExp(`^[${PY_WS}]*$`, "u");

/** `text.strip() == ""` in Python. */
export function isBlank(text: string): boolean {
  return WS_ONLY.test(text);
}

/** `text.split()` in Python: runs of whitespace separate, and leading/trailing ones vanish. */
export function pySplit(text: string): string[] {
  return text.split(WS_RUN).filter((word) => word !== "");
}

/** `text[:1].upper() + text[1:]` in Python, where an index is a code point, not a UTF-16 unit. */
export function capitalise(text: string): string {
  const first = text.codePointAt(0);
  if (first === undefined) return text;
  const head = String.fromCodePoint(first);
  return head.toUpperCase() + text.slice(head.length);
}
