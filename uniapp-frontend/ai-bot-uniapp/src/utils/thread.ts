/**
 * 会话 ID 生成。
 *
 * 原站直接调用 `crypto.randomUUID()`，但该 API 只在安全上下文（https 或
 * localhost）中可用。用局域网 IP 走 http 打开页面时 `crypto.randomUUID` 是
 * undefined，会直接抛错，导致「新建会话」完全不可用。这里做降级处理。
 */
function randomHex(length: number): string {
  const chars = '0123456789abcdef'
  let out = ''
  for (let i = 0; i < length; i += 1) {
    out += chars[Math.floor(Math.random() * chars.length)]
  }
  return out
}

export function makeThreadId(): string {
  const c = typeof crypto !== 'undefined' ? (crypto as Crypto & { randomUUID?: () => string }) : undefined
  if (typeof c?.randomUUID === 'function') {
    try {
      return `web-${c.randomUUID()}`
    } catch {
      // 某些 WebView 会抛错，继续走降级分支
    }
  }
  return `web-${randomHex(8)}-${randomHex(4)}-${randomHex(4)}-${randomHex(4)}-${randomHex(12)}`
}
