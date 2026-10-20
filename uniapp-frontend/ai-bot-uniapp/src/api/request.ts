/**
 * 统一请求封装（uni-app 版）
 *
 * 与原站保持一致的约定：
 * - 所有接口统一走 `${API_BASE}${path}`，H5 端由 Vite 代理 /api 到后端；
 * - token 存放在本地存储 ai_bot_token，用户名存放在 ai_bot_username；
 * - 401（非 /auth/ 路径）视为登录失效，清空凭证并通过回调通知 UI 层。
 */

/**
 * 后端接口前缀：
 * - H5 开发环境走 Vite 代理（/api 由开发服务器转发到 FastAPI），避免跨域；
 * - 小程序 / App 没有代理，必须使用 .env 里的完整地址。
 */
let apiBase = import.meta.env.VITE_API_BASE_URL || '/api'

// #ifdef H5
// H5 开发环境统一走 Vite 代理，忽略环境变量里的局域网地址
if (import.meta.env.DEV) apiBase = '/api'
// #endif

export const API_BASE = apiBase

/** token 存储 key，沿用原站命名 */
export const TOKEN_STORAGE_KEY = 'ai_bot_token'
/** 用户名存储 key，沿用原站命名 */
export const USERNAME_STORAGE_KEY = 'ai_bot_username'

/** 业务请求失败时抛出的错误，携带 HTTP 状态码与后端 detail */
export class RequestError extends Error {
  /** HTTP 状态码；网络层失败时为 0 */
  readonly status: number
  /** 后端返回的 detail 原文（可能是字符串或 FastAPI 校验数组） */
  readonly detail: unknown

  constructor(message: string, status: number, detail?: unknown) {
    super(message)
    this.name = 'RequestError'
    this.status = status
    this.detail = detail
  }
}

/** JSON 请求体 */
export type RequestData = Record<string, unknown> | unknown[] | string | undefined
/** multipart 表单字段（可包含字符串或文件对象） */
export type RequestFormData = Record<string, unknown>

/** request 选项 */
export interface RequestOptions {
  /** 请求方法，默认 GET */
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'
  /** JSON 请求体：会自动设置 Content-Type 并 JSON.stringify */
  data?: RequestData
  /**
   * multipart 表单体：直接交给 uni.request 的 data。
   * 不会设置 Content-Type，由各端自行补上 boundary。
   * 与 data 同时传入时以 formData 为准。
   */
  formData?: RequestFormData
  /** 自定义请求头 */
  header?: Record<string, string>
  /** 超时时间（毫秒） */
  timeout?: number
}

/** 未授权（登录失效）回调 */
export type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

/**
 * 注册登录失效回调，供 UI 层（如 Pinia store）在 token 过期时切换回登录页。
 * 传入 null 可取消注册。
 */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn
}

/** 读取本地 token（每次调用都重新读取，避免模块加载期缓存过期值） */
export function getToken(): string {
  try {
    return (uni.getStorageSync(TOKEN_STORAGE_KEY) as string) || ''
  } catch {
    return ''
  }
}

/** 读取本地用户名 */
export function getStoredUsername(): string {
  try {
    return (uni.getStorageSync(USERNAME_STORAGE_KEY) as string) || ''
  } catch {
    return ''
  }
}

/** 写入登录凭证 */
export function setAuthStorage(token: string, username: string): void {
  try {
    uni.setStorageSync(TOKEN_STORAGE_KEY, token)
    uni.setStorageSync(USERNAME_STORAGE_KEY, username)
  } catch {
    // 存储失败不影响内存中的登录态，忽略
  }
}

/** 清空登录凭证 */
export function clearAuthStorage(): void {
  try {
    uni.removeStorageSync(TOKEN_STORAGE_KEY)
    uni.removeStorageSync(USERNAME_STORAGE_KEY)
  } catch {
    // 忽略存储异常
  }
}

/**
 * 是否为“登录接口”的 401。
 * 只有 /auth/login 的 401 是“用户名或密码错误”，其余 401（包括 /auth/me）
 * 都代表 token 失效，应清空凭证并回到登录页。
 */
function isAuthPath(path: string): boolean {
  return path === '/auth/login'
}

/**
 * 统一处理“登录已失效”：清空本地凭证并通知 UI 层回到登录页。
 * 除了 request()/uploadRequest()，流式请求（utils/stream.ts）也需要在 401 时调用它。
 */
export function handleUnauthorized(): void {
  clearAuthStorage()
  if (!unauthorizedHandler) return
  try {
    unauthorizedHandler()
  } catch {
    // UI 回调异常不应掩盖原始错误
  }
}

/**
 * 微信小程序的 wx.request 不支持 PATCH（method 合法值里没有 PATCH），
 * 后端为需要 PATCH 的接口同时注册了 PUT，这里按平台选择实际方法。
 */
let patchMethod: 'PATCH' | 'PUT' = 'PATCH'
// #ifdef MP-WEIXIN
patchMethod = 'PUT'
// #endif
/** PATCH 类接口在该平台上应使用的方法 */
export const PATCH_METHOD = patchMethod

/**
 * 从响应体中提取错误信息。
 * - detail 为字符串：直接使用；
 * - detail 为数组（FastAPI 校验错误）：取 detail[0].msg；
 * - 其他情况：回退到 `请求失败（<status>）`。
 */
export function extractErrorMessage(body: unknown, status: number): string {
  const fallback = `请求失败（${status}）`
  const detail = (body as { detail?: unknown } | null | undefined)?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown } | null | undefined
    if (first && typeof first.msg === 'string' && first.msg) return first.msg
  }
  return fallback
}

/**
 * 通用请求方法。
 * uni.request 在 HTTP 错误状态时不会 reject，因此必须在 success 回调中自行判断 statusCode。
 */
export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', data, formData, header, timeout } = options
  const token = getToken()

  // 请求头：默认按 JSON 提交，multipart 场景不设置 Content-Type
  const headers: Record<string, string> = { ...(header || {}) }
  if (formData === undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  // multipart 直接透传对象，让各端自行生成 boundary
  const body: unknown =
    formData !== undefined ? formData : data !== undefined ? JSON.stringify(data) : undefined

  return new Promise<T>((resolve, reject) => {
    // 注意：@dcloudio/types 的 method 联合类型未包含 PATCH（小程序运行时也不支持），
    // PATCH 类接口在 api/index.ts 里通过 PATCH_METHOD 按平台切换成 PUT。
    const options = {
      url: `${API_BASE}${path}`,
      method,
      data: body as never,
      header: headers,
      timeout,
      success: (res: { statusCode: number; data: unknown }) => {
        const status = res.statusCode

        // 401：非鉴权路径视为登录失效
        if (status === 401 && !isAuthPath(path)) {
          handleUnauthorized()
          reject(new RequestError('登录已失效，请重新登录', status, res.data))
          return
        }

        if (status >= 200 && status < 300) {
          // 204 等无响应体的成功状态
          if (status === 204) {
            resolve(undefined as T)
            return
          }
          resolve(res.data as T)
          return
        }

        reject(new RequestError(extractErrorMessage(res.data, status), status, res.data))
      },
      fail: (error: { errMsg?: string }) => {
        const message =
          typeof error?.errMsg === 'string' && error.errMsg.includes('timeout')
            ? '请求超时，请稍后重试'
            : '网络异常，请检查网络后重试'
        reject(new RequestError(message, 0, error))
      },
    }

    uni.request(options as never)
  })
}

/** multipart 上传选项 */
export interface UploadOptions {
  /** 文件路径：小程序临时路径 / H5 与 App 的 blob 路径 */
  filePath?: string
  /**
   * H5 端的原始 File 实例。
   * 传了它就用 `files` 提交，浏览器会自行补全文件名与 boundary，比 blob 路径更可靠。
   */
  file?: File
  /** 文件字段名，默认 `file` */
  name?: string
  /** 附加表单字段；值为 undefined / null 的字段会被丢弃 */
  formData?: Record<string, string | number | undefined | null>
  timeout?: number
}

/**
 * multipart/form-data 上传。
 *
 * 这里必须用 `uni.uploadFile` 而不是 `uni.request`：
 * `uni.request` 不会把 File 对象编码成 multipart，文件会被序列化坏。
 * 响应体是字符串，需要自行 JSON.parse。
 */
export function uploadRequest<T>(path: string, options: UploadOptions): Promise<T> {
  const token = getToken()
  const header: Record<string, string> = {}
  if (token) header.Authorization = `Bearer ${token}`

  // 丢弃空值，避免各端把字面量 "undefined" 当成字段值提交
  const formData: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(options.formData || {})) {
    if (value !== undefined && value !== null && value !== '') formData[key] = value
  }

  const fieldName = options.name || 'file'

  return new Promise<T>((resolve, reject) => {
    const handle = (res: { statusCode: number; data: unknown }) => {
      const status = res.statusCode
      // uploadFile 的 data 是字符串，尽量解析成 JSON
      let body: unknown = res.data
      if (typeof body === 'string') {
        try {
          body = JSON.parse(body)
        } catch {
          // 保持字符串原样，下面按错误信息处理
        }
      }

      if (status === 401 && !isAuthPath(path)) {
        handleUnauthorized()
        reject(new RequestError('登录已失效，请重新登录', status, body))
        return
      }

      if (status >= 200 && status < 300) {
        resolve(body as T)
        return
      }

      reject(new RequestError(extractErrorMessage(body, status), status, body))
    }

    const payload: Record<string, unknown> = {
      url: `${API_BASE}${path}`,
      header,
      formData,
      timeout: options.timeout,
      success: handle,
      fail: (error: { errMsg?: string }) => {
        const message =
          typeof error?.errMsg === 'string' && error.errMsg.includes('timeout')
            ? '上传超时，请稍后重试'
            : '上传失败，请检查网络后重试'
        reject(new RequestError(message, 0, error))
      },
    }

    if (options.file) {
      // 仅 H5 支持 files；小程序/App 走 filePath 分支
      payload.files = [{ name: fieldName, file: options.file }]
    } else {
      payload.filePath = options.filePath
      payload.name = fieldName
    }

    uni.uploadFile(payload as never)
  })
}

export default request
