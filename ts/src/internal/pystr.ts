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

/** `text.strip()` in Python: the same whitespace set as `split()`. */
export function pyStrip(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && IS_WS.test(text.charAt(start))) start += 1;
  while (end > start && IS_WS.test(text.charAt(end - 1))) end -= 1;
  return text.slice(start, end);
}

/** `len(text)` in Python counts code points; `.length` counts UTF-16 units. */
export function codePointLength(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** `text.rstrip("/")` in Python. */
export function rstripSlashes(text: string): string {
  let end = text.length;
  while (end > 0 && text.charCodeAt(end - 1) === 0x2f) end -= 1;
  return text.slice(0, end);
}

const IS_WS = new RegExp(`^[${PY_WS}]$`, "u");

/** What Python's `str.isprintable` rejects (the space itself is allowed). */
const NOT_PRINTABLE = /^[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]$/u;

function hex(code: number, width: number): string {
  return code.toString(16).padStart(width, "0");
}

/**
 * `repr(text)` in Python: single quotes unless the text holds a `'` and no `"`, the
 * backslash, the quote and `\n \r \t` escaped, and a non-printable character as `\xNN`,
 * `\uNNNN` or `\UNNNNNNNN`.
 */
export function pyRepr(text: string): string {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  let out = quote;
  for (const char of text) {
    const code = char.codePointAt(0) as number;
    if (char === quote || char === "\\") out += `\\${char}`;
    else if (char === "\n") out += "\\n";
    else if (char === "\r") out += "\\r";
    else if (char === "\t") out += "\\t";
    else if (char !== " " && NOT_PRINTABLE.test(char)) {
      if (code < 0x100) out += `\\x${hex(code, 2)}`;
      else if (code < 0x10000) out += `\\u${hex(code, 4)}`;
      else out += `\\U${hex(code, 8)}`;
    } else out += char;
  }
  return out + quote;
}

/** The parts of `urllib.parse.urlsplit` that `envconfig` reads. Query and fragment are dropped. */
export interface UrlParts {
  readonly scheme: string;
  readonly netloc: string;
  readonly path: string;
}

const SCHEME_REST = /^[A-Za-z0-9+.-]*$/;

/**
 * `urllib.parse.urlsplit`, minus the query and fragment. An RFC 3986 split, deliberately
 * not WHATWG `URL`: that lowercases the host and drops a default port, `urlsplit` keeps both.
 *
 * Follows current CPython: leading C0 controls and spaces are stripped and `\t \r \n`
 * removed everywhere, the scheme is lowercased, the netloc runs from `//` to the first of
 * `/?#`, and a lone bracket is an error. It does not validate the contents of a bracketed
 * host or NFKC-normalise a non-ASCII netloc.
 */
export function pyUrlsplit(input: string): UrlParts {
  let start = 0;
  while (start < input.length && input.charCodeAt(start) <= 0x20) start += 1; // CPython strips leading C0 controls
  let rest = input.slice(start).replace(/[\t\r\n]/g, "");
  let scheme = "";
  const colon = rest.indexOf(":");
  if (colon > 0 && /^[A-Za-z]$/.test(rest.charAt(0)) && SCHEME_REST.test(rest.slice(0, colon))) {
    scheme = rest.slice(0, colon).toLowerCase();
    rest = rest.slice(colon + 1);
  }
  let netloc = "";
  if (rest.startsWith("//")) {
    let end = rest.length;
    for (const delimiter of "/?#") {
      const at = rest.indexOf(delimiter, 2);
      if (at >= 0 && at < end) end = at;
    }
    netloc = rest.slice(2, end);
    rest = rest.slice(end);
    if (
      (netloc.includes("[") && !netloc.includes("]")) ||
      (netloc.includes("]") && !netloc.includes("["))
    ) {
      throw new Error("Invalid IPv6 URL");
    }
  }
  const cut = rest.search(/[#?]/);
  return { scheme, netloc, path: cut < 0 ? rest : rest.slice(0, cut) };
}

/**
 * `urlunsplit((scheme, netloc, path, "", ""))` for an http or https scheme, which is in
 * `uses_netloc`: the `//` is written whenever there is a netloc, or a path that does not
 * itself open with `//`.
 */
export function pyUrlunsplit(scheme: string, netloc: string, path: string): string {
  let url = path;
  if (netloc || !url.startsWith("//")) {
    if (url && !url.startsWith("/")) url = `/${url}`;
    url = `//${netloc}${url}`;
  }
  return `${scheme}:${url}`;
}
