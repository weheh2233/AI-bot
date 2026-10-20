/** 与原站 web/index.html 中一致的格式化 / 校验工具。 */

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024
export const SUPPORTED_EXTENSIONS = ['pdf', 'txt', 'md', 'docx', 'pptx'] as const
export const SUPPORTED_EXTENSIONS_TEXT = SUPPORTED_EXTENSIONS.map((e) => `.${e}`).join('、')

/**
 * 会话时间的展示格式。
 * 原站用 Intl.DateTimeFormat('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})，
 * 输出形如 `10/13 14:30`。这里手写等价实现，避免依赖各端 Intl 的差异。
 */
export function formatConversationTime(value?: string | null): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '未知大小'
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** HTML 转义；用于把纯文本安全地塞进 rich-text 的 HTML 字符串模式。 */
export function escapeHtmlText(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 纯文本 -> rich-text 可用的 HTML（换行转 <br />）。
 *  scale 用于小程序端的字号档位：rich-text 不继承外部 CSS，只能把字号写进根节点。
 */
export function plainTextToRichText(text: string, scale = 1): string {
  const html = escapeHtmlText(text).replace(/\r\n|\r|\n/g, '<br />')
  if (!Number.isFinite(scale) || scale === 1) return html
  const fontSize = Math.round(14 * scale * 100) / 100
  return `<div style="font-size:${fontSize}px;line-height:1.75;">${html}</div>`
}

export interface UploadCandidate {
  name?: string
  path?: string
  size?: number
}

/**
 * 上传前的本地预校验。
 *
 * 接口文档把「扩展名与大小预校验」列为前端职责，但原站完全没有做校验，
 * 用户选了不支持的格式或超大文件要等后端返回 415 / 413 才知道。
 */
export function validateUploadFile(file: UploadCandidate): string | null {
  const name = (file.name || file.path || '').toLowerCase()
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot + 1) : ''
  if (!ext) {
    return `无法识别文件类型，请上传 ${SUPPORTED_EXTENSIONS_TEXT} 文件`
  }
  if (!(SUPPORTED_EXTENSIONS as readonly string[]).includes(ext)) {
    return `不支持的文件格式：${ext}，请上传 ${SUPPORTED_EXTENSIONS_TEXT} 文件`
  }
  if (typeof file.size === 'number' && file.size > MAX_UPLOAD_BYTES) {
    return `文件超过上限 ${MAX_UPLOAD_BYTES / 1024 / 1024}MB`
  }
  return null
}

/** 稳定且唯一的本地 key，用于消息列表渲染。 */
let seq = 0
export function nextMessageId(): string {
  seq += 1
  return `m${seq}`
}

/* ---------------------------------------------------------------------------
 * v2 的时间显示：消息气泡下方的时间、悬浮完整时间、日期分隔线、耗时
 * ------------------------------------------------------------------------- */

function toDate(value?: string | null): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** 气泡下方的时间：`14:30` */
export function formatMessageTime(value?: string | null): string {
  const date = toDate(value)
  if (!date) return ''
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

/** 悬浮提示里的完整时间：`2026-10-13 14:30:05` */
export function formatFullMessageTime(value?: string | null): string {
  const date = toDate(value)
  if (!date) return ''
  return (
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
  )
}

/** 按天分组的 key */
export function dateKey(value?: string | null): string {
  const date = toDate(value)
  if (!date) return ''
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/** 日期分隔线文案：今天 / 昨天 / 2026年10月13日 */
export function formatDateDivider(value?: string | null): string {
  const date = toDate(value)
  if (!date) return ''
  const now = new Date()
  const today = dateKey(now.toISOString())
  const target = dateKey(value)
  if (target === today) return '今天'
  const yesterday = new Date(now.getTime() - 86400000)
  if (target === dateKey(yesterday.toISOString())) return '昨天'
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

/** 助手回复这一轮的耗时：`用时 3.2 秒` */
export function formatElapsed(seconds?: number | null): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return ''
  return `用时 ${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`
}

/** 设置页里展示的时间：`2026-10-13 14:30` */
export function formatDateTime(value?: string | null): string {
  const date = toDate(value)
  if (!date) return ''
  return (
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
  )
}
