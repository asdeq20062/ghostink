(function exposeZeroWidthSteg(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZeroWidthSteg = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const ZERO = "\u200B";
  const ONE = "\u200C";

  function encode(secret) {
    const bytes = new TextEncoder().encode(secret);
    const bits = new Array(bytes.length * 8);
    let offset = 0;
    for (const byte of bytes) {
      for (let shift = 7; shift >= 0; shift -= 1) {
        bits[offset] = ((byte >> shift) & 1) === 0 ? ZERO : ONE;
        offset += 1;
      }
    }
    return bits.join("");
  }

  function hide(carrier, secret) {
    if (!carrier) throw new Error("請輸入作為載體的文字。");
    if (!secret) throw new Error("請輸入要隱藏的文字。");

    // Remove only the two symbols used by this codec so extraction is unambiguous.
    const cleanCarrier = carrier.replace(/[\u200B\u200C]/g, "");
    const firstCodePoint = cleanCarrier.codePointAt(0);
    const insertAt = firstCodePoint > 0xFFFF ? 2 : 1;
    const payload = encode(secret);
    return {
      text: `${cleanCarrier.slice(0, insertAt)}${payload}${cleanCarrier.slice(insertAt)}`,
      bitCount: payload.length,
      byteCount: payload.length / 8,
    };
  }

  function extract(text) {
    if (!text) throw new Error("請貼上含有零寬字元的文字。");
    const symbols = [...text].filter((character) => character === ZERO || character === ONE);
    if (symbols.length === 0) throw new Error("找不到 U+200B 或 U+200C 隱藏資料。");
    if (symbols.length % 8 !== 0) throw new Error("隱藏資料不完整：零寬字元數量不是 8 的倍數。");

    const bytes = new Uint8Array(symbols.length / 8);
    for (let byteIndex = 0; byteIndex < bytes.length; byteIndex += 1) {
      let value = 0;
      for (let bitIndex = 0; bitIndex < 8; bitIndex += 1) {
        value = (value << 1) | (symbols[byteIndex * 8 + bitIndex] === ONE ? 1 : 0);
      }
      bytes[byteIndex] = value;
    }

    try {
      return {
        text: new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        bitCount: symbols.length,
        byteCount: bytes.length,
      };
    } catch {
      throw new Error("隱藏資料不是有效的 UTF-8 文字，可能已被截斷或修改。");
    }
  }

  return { ZERO, ONE, encode, hide, extract };
}));
