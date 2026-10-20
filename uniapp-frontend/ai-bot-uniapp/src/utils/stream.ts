/**
 * SSE 流式对话（POST /api/chat/stream）
 *
 * 由于 uni-app 各端传输能力不同，这里按平台分支实现：
 * - H5：fetch + TextDecoder(stream: true) 逐块读取；
 * - MP-WEIXIN：uni.request({ enableChunked: true }) + onChunkReceived；
 * - 其他端（App 等）：无可靠流式传输，退化为普通 POST /chat 一次性返回。
 *
 * 三种分支共用同一套 SSE 解析逻辑，保证切块切在事件中间也不会丢数据。
 */

import { API_BASE, extractErrorMessage, getToken, handleUnauthorized } from '@/api/request'
import type { ApprovalPayload } from '@/api'

/** 请求体（与后端 ChatRequest 对应） */
export interface StreamChatPayload {
  message: string
  /** 本轮附带的图片（base64 data URL）；重新生成时不传 */
  images?: string[]
  thread_id: string
  /** 选定角色；null 表示用账号默认 / 系统预设 */
  persona_id?: number | null
  /** 客户端生成的回合 ID，暂停/继续/停止都要用它；不传则服务端自己生成 */
  turn_id?: string | null
  /** 重新生成上一条回复 */
  regenerate?: boolean
}

/** 流式事件回调 */
export interface StreamChatHandlers {
  /** 收到一段增量文本 */
  onDelta: (text: string) => void
  /** 收到 202 待确认事件（工具调用需要人工审批） */
  onApproval: (payload: ApprovalPayload) => void
  /**
   * 收到首帧 {"type":"started"}，带上本轮的 turn_id。
   * 我们自己会先生成一个 turn_id 传上去，这里是服务端的确认值。
   */
  onStart?: (turnId: string) => void
  /**
   * 本轮结束。
   * @param interrupted 因等待人工确认而暂停
   * @param elapsed     本轮耗时（秒），来自 {"type":"done"} 帧
   */
  onDone?: (interrupted?: boolean, elapsed?: number) => void
  /** 服务端主动取消（{"type":"cancelled"}，之后不会再有 [DONE]） */
  onCancelled?: () => void
  /** 出错（message 为可直接展示的中文提示），同样可选 */
  onError?: (message: string) => void
}

/** 解构后的单帧数据 */
interface ParsedFrame {
  /** 文本增量 */
  delta?: string
  /** 是否为待确认帧 */
  approval?: ApprovalPayload
  /** {"type":"started"} 带来的 turn_id */
  started?: string
  /** {"type":"done"} 带来的耗时（秒） */
  elapsed?: number
  /** 是否收到 {"type":"done"} */
  finished?: boolean
  /** 是否收到 {"type":"cancelled"} */
  cancelled?: boolean
  /** {"type":"error"} 带来的提示 */
  error?: string
  /** 是否收到 [DONE] */
  done: boolean
}

/**
 * 增量解析 SSE 缓冲。
 *
 * 事件之间以空行（\n\n）分隔；单个网络分片可能包含半个事件或多个事件，
 * 因此把最后一个不完整片段留在 buffer 里交给下一次调用。
 *
 * @param buffer 当前缓冲（会被就地修改）
 * @param chunk  新到达的文本
 * @param onFrame 每解析出一帧就回调
 */
function pullEvents(
  buffer: string,
  chunk: string,
  onFrame: (frame: ParsedFrame) => void,
): { buffer: string; done: boolean } {
  const merged = buffer + chunk
  const events = merged.split('\n\n')
  // 最后一段可能不完整，保留到下次
  const rest = events.pop() ?? ''
  let done = false

  for (const event of events) {
    const line = event.split('\n').find((item) => item.startsWith('data: '))
    if (!line) continue
    // 注意：冒号后的空格属于前缀
    const raw = line.slice(6)

    if (raw === '[DONE]') {
      done = true
      break
    }

    // 帧内容不是 JSON 时，按原样当作文本增量（保持服务端异常帧的行为）
    let frame: unknown
    try {
      frame = JSON.parse(raw)
    } catch {
      onFrame({ delta: raw, done: false })
      continue
    }

    if (frame && typeof frame === 'object') {
      const obj = frame as Record<string, unknown>

      // 审批帧没有 type 字段，只能靠 status 识别
      if (obj.status === 'awaiting_approval') {
        onFrame({
          approval: {
            status: 'awaiting_approval',
            action_requests: Array.isArray(obj.action_requests) ? obj.action_requests : [],
            review_configs: Array.isArray(obj.review_configs) ? obj.review_configs : [],
          } as ApprovalPayload,
          done: false,
        })
        continue
      }

      // v2 的生命周期帧：started / done / cancelled / error
      const type = typeof obj.type === 'string' ? obj.type : ''
      if (type === 'started') {
        onFrame({ started: typeof obj.turn_id === 'string' ? obj.turn_id : '', done: false })
        continue
      }
      if (type === 'done') {
        onFrame({
          finished: true,
          elapsed: typeof obj.elapsed === 'number' ? obj.elapsed : undefined,
          done: false,
        })
        continue
      }
      if (type === 'cancelled') {
        // 取消后服务端不会再发 [DONE]，这里直接终止读取
        onFrame({ cancelled: true, done: true })
        done = true
        break
      }
      if (type === 'error') {
        onFrame({
          error: typeof obj.detail === 'string' && obj.detail ? obj.detail : '模型调用失败，请稍后重试',
          done: true,
        })
        done = true
        break
      }

      if (obj.delta !== undefined) {
        onFrame({
          delta: typeof obj.delta === 'string' ? obj.delta : JSON.stringify(obj.delta),
          done: false,
        })
        continue
      }
    }

    // 其他结构无法识别，忽略该帧
  }

  return { buffer: done ? '' : rest, done }
}

/**
 * 手写 UTF-8 解码器（小程序端 TextDecoder 不可用时兜底）。
 * 内部缓存不完整的多字节序列，保证跨分片不会被截断。
 */
class ManualUtf8Decoder {
  private pending: number[] = []

  decode(chunk: Uint8Array): string {
    const bytes = this.pending.concat(Array.from(chunk))
    this.pending = []
    let result = ''
    let i = 0

    while (i < bytes.length) {
      const first = bytes[i]

      if (first < 0x80) {
        result += String.fromCharCode(first)
        i += 1
        continue
      }

      let need = 0
      let code = 0
      if (first >= 0xc2 && first <= 0xdf) {
        need = 1
        code = first & 0x1f
      } else if (first >= 0xe0 && first <= 0xef) {
        need = 2
        code = first & 0x0f
      } else if (first >= 0xf0 && first <= 0xf4) {
        need = 3
        code = first & 0x07
      } else {
        // 非法首字节
        result += '\uFFFD'
        i += 1
        continue
      }

      // 后续字节不足：把剩余片段缓存起来等待下一个分片
      if (i + need >= bytes.length) break

      let valid = true
      for (let k = 1; k <= need; k += 1) {
        const next = bytes[i + k]
        if ((next & 0xc0) !== 0x80) {
          valid = false
          break
        }
        code = (code << 6) | (next & 0x3f)
      }
      if (!valid) {
        result += '\uFFFD'
        i += 1
        continue
      }

      if (code > 0xffff) {
        const v = code - 0x10000
        result += String.fromCharCode(0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff))
      } else {
        result += String.fromCharCode(code)
      }
      i += need + 1
    }

    if (i < bytes.length) this.pending = bytes.slice(i)
    return result
  }

  /** 流结束时冲刷残留字节 */
  flush(): string {
    if (this.pending.length === 0) return ''
    this.pending = []
    return '\uFFFD'
  }
}

/** 统一的 UTF-8 文本解码器接口 */
interface TextDecoderLike {
  decode(chunk: Uint8Array): string
  flush?: () => string
}

/** 按运行时能力选择解码器 */
function createDecoder(): TextDecoderLike {
  if (typeof TextDecoder !== 'undefined') {
    const decoder = new TextDecoder('utf-8')
    return {
      decode: (chunk: Uint8Array) => decoder.decode(chunk, { stream: true }),
      flush: () => decoder.decode(),
    }
  }
  return new ManualUtf8Decoder()
}

/**
 * 把整段 ArrayBuffer 解码成文本。
 * 小程序没有 TextDecoder，部分运行时虽有实现但可能不支持流式参数，因此统一兜底。
 */
function decodeBuffer(buffer: ArrayBuffer): string {
  if (typeof TextDecoder !== 'undefined') {
    try {
      return new TextDecoder('utf-8').decode(buffer)
    } catch {
      // 继续用自带的 UTF-8 解码器
    }
  }
  return new ManualUtf8Decoder().decode(new Uint8Array(buffer))
}

/**
 * 创建一次流式会话的运行时状态，三种平台分支共用。
 * 保证 onDone 只触发一次，并统一 interrupted 语义。
 */
function createRuntime(handlers: StreamChatHandlers) {
  const decoder = createDecoder()
  let buffer = ''
  let interrupted = false
  let finished = false
  let elapsed: number | undefined

  const finish = (): void => {
    if (finished) return
    finished = true
    const tail = decoder.flush ? decoder.flush() : ''
    if (tail) handlers.onDelta(tail)
    handlers.onDone?.(interrupted, elapsed)
  }

  /** 返回 true 表示继续读取，false 表示这一轮已经终结 */
  const handleFrame = (frame: ParsedFrame): boolean => {
    if (frame.error) {
      handlers.onError?.(frame.error)
      return false
    }
    if (frame.cancelled) {
      handlers.onCancelled?.()
      return false
    }
    if (frame.started !== undefined) {
      handlers.onStart?.(frame.started)
      return true
    }
    if (frame.finished) {
      elapsed = frame.elapsed
      return true
    }
    if (frame.done) return true
    if (frame.approval) {
      interrupted = true
      handlers.onApproval(frame.approval)
      return true
    }
    if (frame.delta !== undefined) handlers.onDelta(frame.delta)
    return true
  }

  /** 处理一个网络分片；返回 false 表示这一轮已终结，应停止读取 */
  const pushChunk = (text: string): boolean => {
    const outcome = pullEvents(buffer, text, handleFrame)
    buffer = outcome.buffer
    return !outcome.done
  }

  /** 处理原始字节分片（小程序端） */
  const pushBytes = (chunk: Uint8Array): boolean => pushChunk(decoder.decode(chunk))

  return { finish, pushChunk, pushBytes, isFinished: () => finished }
}

/** H5：fetch + ReadableStream 增量读取 */
async function streamOnH5(
  payload: StreamChatPayload,
  handlers: StreamChatHandlers,
): Promise<void> {
  const runtime = createRuntime(handlers)
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`

  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      // 非 2xx 时后端返回的通常不是事件流，而是普通 JSON 错误体
      let body: unknown
      try {
        body = await response.json()
      } catch {
        body = undefined
      }
      if (response.status === 401) {
        handleUnauthorized()
        throw new Error('登录已失效，请重新登录')
      }
      throw new Error(extractErrorMessage(body, response.status))
    }

    if (!response.body) {
      throw new Error('当前浏览器不支持流式响应')
    }

    const reader = response.body.getReader()
    let reading = true
    while (reading) {
      const { value, done } = await reader.read()
      if (done) break
      if (!value) continue
      reading = runtime.pushBytes(value)
    }
    runtime.finish()
  } catch (error) {
    runtime.finish()
    handlers.onError?.(
      error instanceof Error ? error.message : '流式响应失败，请稍后重试',
    )
  }
}

/** 小程序：uni.request enableChunked + onChunkReceived */
function streamOnMiniProgram(
  payload: StreamChatPayload,
  handlers: StreamChatHandlers,
): Promise<void> {
  return new Promise<void>((resolve) => {
    const runtime = createRuntime(handlers)
    const token = getToken()
    const header: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) header.Authorization = `Bearer ${token}`

    let settled = false
    /** 是否收到过 onChunkReceived 分片（用于判断是否需要回退解析整段响应体） */
    let chunkSeen = false
    /** 结束：先触发 onDone，再 resolve */
    const settle = (): void => {
      if (settled) return
      settled = true
      runtime.finish()
      resolve()
    }

    const task = uni.request({
      url: `${API_BASE}/chat/stream`,
      method: 'POST',
      data: JSON.stringify(payload),
      header,
      timeout: 300000,
      enableChunked: true,
      responseType: 'arraybuffer',
      success: (res) => {
        if (settled) return
        // 非分块实现（或后端直接返回错误 JSON）时，按普通响应兜底解析
        if (res.statusCode < 200 || res.statusCode >= 300) {
          const raw = res.data
          let body: unknown = raw
          if (raw instanceof ArrayBuffer) {
            try {
              body = JSON.parse(decodeBuffer(raw))
            } catch {
              body = undefined
            }
          }
          const unauthorized = res.statusCode === 401
          if (unauthorized) handleUnauthorized()
          runtime.finish()
          handlers.onError?.(
            unauthorized ? '登录已失效，请重新登录' : extractErrorMessage(body, res.statusCode),
          )
          if (!settled) {
            settled = true
            resolve()
          }
          return
        }
        // 某些基础库/容器不会回调 onChunkReceived，此时整段响应体在 res.data 里，
        // 直接交给同一个 SSE 解析器，避免整条回复被丢弃。
        if (!chunkSeen && res.data) {
          try {
            const text =
              typeof res.data === 'string' ? res.data : decodeBuffer(res.data as ArrayBuffer)
            if (text) runtime.pushChunk(text)
          } catch {
            // 解析失败时保持“没有收到文本”的既有兜底
          }
        }
        // 分块数据在 success 之前已全部回调，这里直接收尾
        settle()
      },
      fail: () => {
        // 收到 [DONE] 后我们会主动 abort，这同样会触发 fail；
        // 已经正常收尾的请求不能再误报成网络异常。
        if (settled) return
        settled = true
        runtime.finish()
        handlers.onError?.('网络异常，请检查网络后重试')
        resolve()
      },
      complete: () => {
        settle()
      },
    })

    const stream = task as unknown as {
      onChunkReceived?: (cb: (res: { data: ArrayBuffer }) => void) => void
      abort?: () => void
    }

    if (typeof stream.onChunkReceived === 'function') {
      stream.onChunkReceived((res) => {
        if (settled || runtime.isFinished()) return
        chunkSeen = true
        const keepGoing = runtime.pushBytes(new Uint8Array(res.data))
        if (!keepGoing) {
          // 收到 [DONE]：先标记正常结束，再断开连接，
          // 避免 abort 触发的 fail 回调覆盖已经流式显示的内容
          settle()
          if (typeof stream.abort === 'function') stream.abort()
        }
      })
    }
  })
}

/** App 等无流式能力的平台：退化为一次性 POST /chat */
async function chatWithoutStream(
  payload: StreamChatPayload,
  handlers: StreamChatHandlers,
): Promise<void> {
  try {
    const response = await uni.request({
      url: `${API_BASE}/chat`,
      method: 'POST',
      data: JSON.stringify(payload),
      header: (() => {
        const token = getToken()
        const header: Record<string, string> = { 'Content-Type': 'application/json' }
        if (token) header.Authorization = `Bearer ${token}`
        return header
      })(),
      timeout: 300000,
    })

    const status = response.statusCode
    const body = response.data as Record<string, unknown> | undefined

    if (status === 401) {
      handleUnauthorized()
      throw new Error('登录已失效，请重新登录')
    }
    if (status < 200 || status >= 300) {
      throw new Error(extractErrorMessage(body, status))
    }

    if (body && body.status === 'awaiting_approval') {
      handlers.onApproval({
        status: 'awaiting_approval',
        action_requests: Array.isArray(body.action_requests) ? body.action_requests : [],
        review_configs: Array.isArray(body.review_configs) ? body.review_configs : [],
      } as ApprovalPayload)
      handlers.onDone?.(true)
      return
    }

    const reply = typeof body?.reply === 'string' ? body.reply : ''
    if (reply) handlers.onDelta(reply)
    handlers.onDone?.(false)
  } catch (error) {
    handlers.onError?.(error instanceof Error ? error.message : '请求失败，请稍后重试')
  }
}

/**
 * 发起流式对话。
 * 返回的 Promise 在流结束（或降级请求完成）时 resolve，业务错误通过 onError 上报。
 */
export function streamChat(
  payload: StreamChatPayload,
  handlers: StreamChatHandlers,
): Promise<void> {
  // #ifdef H5
  return streamOnH5(payload, handlers)
  // #endif

  // #ifdef MP-WEIXIN
  return streamOnMiniProgram(payload, handlers)
  // #endif

  // #ifndef H5
  // #ifndef MP-WEIXIN
  return chatWithoutStream(payload, handlers)
  // #endif
  // #endif
}

export default streamChat
