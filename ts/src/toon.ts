/**
 * TOON output, behind the toolkit's own interface.
 *
 * A thin wrapper over `@toon-format/toon`, the one runtime dependency. Nothing from that
 * library is re-exported: a tool imports `encode` from here, so the encoder can be
 * swapped without touching a caller, and every AXI tool encodes the same way (the
 * library's `replacer` is deliberately not exposed). The fixture rig in `toon-spec`
 * judges whatever this is wired to.
 */

import { encode as encodeValue } from "@toon-format/toon";

export type Delimiter = "," | "\t" | "|";

export interface EncodeOptions {
  delimiter?: Delimiter;
  /** Spaces per indentation level. */
  indent?: number;
}

/** Encode a JSON-shaped value as TOON. */
export function encode(value: unknown, options: EncodeOptions = {}): string {
  return encodeValue(value, {
    ...(options.delimiter === undefined ? {} : { delimiter: options.delimiter }),
    ...(options.indent === undefined ? {} : { indentSize: options.indent }),
  });
}

/**
 * Encode a single primitive the way it appears as a field value.
 *
 * This is the field form, not the root form: a root string has extra quoting rules (a
 * leading U+FEFF) that do not apply inside a document, so the value is encoded as the
 * member of an object and the key is taken off again.
 */
export function encodeScalar(
  value: unknown,
  options: Pick<EncodeOptions, "delimiter"> = {},
): string {
  if (value !== null && !["string", "number", "boolean"].includes(typeof value)) {
    throw new TypeError("encodeScalar takes a string, number, boolean or null");
  }
  return encode({ k: value }, options).slice("k: ".length);
}
