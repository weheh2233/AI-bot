/**
 * 业务接口集合（与原站 Web 端接口一一对应）
 *
 * 所有方法都返回 Promise，失败时抛出 RequestError（见 ./request）。
 */

import { API_BASE, PATCH_METHOD, RequestError, getToken, request, uploadRequest } from './request'
import { streamChat as runStreamChat } from '@/utils/stream'
import type { StreamChatHandlers } from '@/utils/stream'

/** 登录/注册接口返回 */
export interface AuthResult {
  access_token: string
  token_type: string
  user_id: number
  username: string
}

/** 当前登录用户（GET /auth/me） */
export interface User {
  user_id: number
  username: string
  is_admin: boolean
}

/** 会话消息。v2 后端额外返回时间戳与这一轮的耗时（秒）。 */
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** 该条消息的时间，用于气泡下方的时间标签；可能为空 */
  timestamp?: string | null
  /** 助手回复这一轮的耗时（秒），用于 .elapsed-time 行 */
  elapsed?: number | null
  images?: string[]
}

/** 待人工确认的工具调用请求 */
export interface ActionRequest {
  name: string
  args?: Record<string, unknown>
  description?: string
  [key: string]: unknown
}

/** 人工确认的展示配置（后端自定义结构，前端透传） */
export interface ReviewConfig {
  [key: string]: unknown
}

/** 人工确认决定 */
export type Decision =
  | { type: 'approve' }
  | { type: 'reject'; message?: string }
  | { type: 'edit'; edited_action: { name: string; args: Record<string, unknown> } }

/**
 * 待人工确认的数据。
 *
 * `status` 在 /chat 与 /chat/stream 的 202 响应中一定是 'awaiting_approval'；
 * 但 GET /conversations/{id} 在 awaiting_approval 为 true 时只带
 * action_requests / review_configs，因此这里把 status 放宽为可选，
 * 便于直接用会话详情打开审批弹窗。
 */
export interface ApprovalPayload {
  status?: 'awaiting_approval'
  action_requests: ActionRequest[]
  review_configs: ReviewConfig[]
}

/** 会话列表项 */
export interface ConversationSummary {
  thread_id: string
  title: string
  preview: string
  message_count: number
  updated_at: string
  awaiting_approval: boolean
  /** v2：是否已加入收藏夹 */
  is_favorite?: boolean
  /** v2：用户标签，最多 8 个 */
  tags?: string[]
}

/** GET /conversations/search 的返回项，字段与列表项一致 */
export type ConversationSearchResult = ConversationSummary

/** 会话详情 */
export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[]
  action_requests: ActionRequest[]
  review_configs: ReviewConfig[]
}

/** 资料库条目 */
export interface DocumentItem {
  id: number
  title: string
  source: string
  file_type: string
  scope: 'private' | 'global' | string
  owner_id: number
  chunk_count: number
  created_at: string
}

/** 普通对话响应（200）。v2 额外返回这一轮的耗时（秒）。 */
export interface ChatResult {
  reply: string
  elapsed?: number
}

/**
 * 对话或续跑的可能结果：正常回复（reply）或等待确认（status + action_requests）。
 * 两种形态的字段都按可选建模，调用方用 isApprovalPayload() 或内联判断区分。
 */
export interface ChatOutcome extends Partial<ApprovalPayload>, Partial<ChatResult> {}

/** uni.chooseFile / uni.chooseMessageFile 选中的文件对象 */
export interface UniFileLike {
  /** H5 / App 端路径 */
  path?: string
  /** 小程序临时文件路径 */
  tempFilePath?: string
  /** 文件名（小程序端由 chooseMessageFile 提供） */
  name?: string
  /** H5 端的原始 File 实例（uni.chooseFile 的 tempFiles 项） */
  file?: File
  /** 另一种常见的原始 File 字段命名（见 stores/docs.ts 的 PickedFile） */
  raw?: File
  size?: number
}

/** 上传资料的可选参数 */
export interface UploadDocumentOptions {
  scope?: 'private' | 'global'
  title?: string
}

/** 判断响应是否是需要人工确认的 202 */
export function isApprovalPayload(result: ChatOutcome): result is ApprovalPayload {
  return (result as ApprovalPayload).status === 'awaiting_approval'
}

/** POST /auth/login */
export function login(username: string, password: string): Promise<AuthResult> {
  return request<AuthResult>('/auth/login', {
    method: 'POST',
    data: { username, password },
  })
}

/** POST /auth/register */
export function register(username: string, password: string): Promise<AuthResult> {
  return request<AuthResult>('/auth/register', {
    method: 'POST',
    data: { username, password },
  })
}

/** GET /auth/me */
export function getMe(): Promise<User> {
  return request<User>('/auth/me')
}

/** GET /conversations?limit=N（1..100，默认 50） */
export function listConversations(limit = 50): Promise<ConversationSummary[]> {
  const safe = Math.min(100, Math.max(1, Math.floor(limit)))
  return request<ConversationSummary[]>(`/conversations?limit=${safe}`)
}

/** GET /conversations/{thread_id}，不存在时后端返回 404 */
export function getConversation(threadId: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(threadId)}`)
}

/** 会话改名接口的返回（后端是 ConversationTitle，不是完整的会话详情） */
export interface ConversationTitleResult {
  thread_id: string
  title: string
}

/** PATCH /conversations/{thread_id}（小程序端为 PUT） */
export function updateConversationTitle(
  threadId: string,
  title: string,
): Promise<ConversationTitleResult> {
  return request<ConversationTitleResult>(`/conversations/${encodeURIComponent(threadId)}`, {
    method: PATCH_METHOD,
    data: { title },
  })
}

/** DELETE /conversations/{thread_id} -> 204 */
export function deleteConversation(threadId: string): Promise<void> {
  return request<void>(`/conversations/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
  })
}

/** POST /chat 的请求体（与 /chat/stream 共用后端 ChatRequest） */
export interface ChatRequestPayload {
  message: string
  images?: string[]
  thread_id: string
  /** 选定角色；null 表示用账号默认 / 系统预设 */
  persona_id?: number | null
  /** 客户端生成的回合 ID；/chat 会忽略它 */
  turn_id?: string | null
  /** 仅 /chat/stream 支持：重新生成上一条回复 */
  regenerate?: boolean
}

/** POST /chat，可能返回 200 reply 或 202 awaiting_approval */
export function chat(
  message: string,
  threadId: string,
  personaId?: number | null,
): Promise<ChatOutcome> {
  return request<ChatOutcome>('/chat', {
    method: 'POST',
    data: { message, thread_id: threadId, persona_id: personaId ?? null },
  })
}

/** POST /chat/resume，提交人工确认结果后继续执行 */
export function resumeChat(threadId: string, decisions: Decision[]): Promise<ChatOutcome> {
  return request<ChatOutcome>('/chat/resume', {
    method: 'POST',
    data: { thread_id: threadId, decisions },
  })
}

/** POST /chat/stream（SSE 流式对话），具体实现见 @/utils/stream */
export function streamChat(
  payload: ChatRequestPayload,
  handlers: StreamChatHandlers,
): Promise<void> {
  return runStreamChat(payload, handlers)
}

/** GET /documents */
export function listDocuments(): Promise<DocumentItem[]> {
  return request<DocumentItem[]>('/documents')
}

/**
 * POST /documents（multipart/form-data）。
 *
 * 必须走 `uni.uploadFile`（封装在 request.ts 的 uploadRequest 里）：
 * `uni.request` 不会把 File 对象编码成 multipart，文件会被序列化坏。
 *
 * - H5：优先提交原始 File 实例（浏览器自行补全文件名与 boundary）；
 * - 小程序 / App：提交临时文件路径。
 */
export function uploadDocument(
  file: UniFileLike,
  opts: UploadDocumentOptions = {},
): Promise<DocumentItem> {
  // PickedFile 上的 file / raw 才是 H5 的原生 File；小程序端这两个字段是
  // undefined，临时路径在 tempFilePath 里。
  const source = file as UniFileLike
  const nestedFile = source.file ?? source.raw

  // 小程序端由 chooseMessageFile 提供 tempFilePath，H5/App 端由 chooseFile 提供 path
  // 用 var 而非 const：下面两个平台分支都会被 vue-tsc 看到，const 会报重复声明
  var filePath = source.tempFilePath || source.path || ''

  // H5 端才可能有原始 File 实例；小程序/App 没有 File 构造器，保持 undefined
  // #ifdef H5
  var h5File: File | undefined = nestedFile
  // #endif
  // #ifndef H5
  var h5File: File | undefined = undefined
  // #endif

  if (!h5File && !filePath) {
    return Promise.reject(new RequestError('未获取到文件路径，请重新选择文件', 0))
  }

  // H5 传原始 File，其余平台传路径；空值字段由 uploadRequest 过滤
  return uploadRequest<DocumentItem>('/documents', {
    file: h5File,
    filePath,
    name: 'file',
    formData: { scope: opts.scope, title: opts.title },
    timeout: 300000,
  })
}

/** DELETE /documents/{id} -> 204 */
export function deleteDocument(id: number): Promise<void> {
  return request<void>(`/documents/${encodeURIComponent(String(id))}`, {
    method: 'DELETE',
  })
}

/** 供流式实现复用：带鉴权头的接口地址 */
export { API_BASE, getToken }

/* ==========================================================================
 * v2：角色（Persona）、个人设置、会话元数据、流式回合控制
 * 契约逐条读自后端 app/api.py、app/routers/auth.py、app/routers/settings.py
 * ========================================================================== */

/**
 * 角色定义。
 * - `is_system` 为 true 的是系统预设（昔涟 / 上杉绘梨衣），所有用户可见但不可改不可删
 * - 自建角色 `owner_id` 为当前用户，`version` 每次 PATCH 自增
 * - `id` 为 null 只出现在会话快照里、且原角色已不可见的情况
 */
export interface Persona {
  id: number | null
  owner_id: number | null
  version: number
  is_system: boolean
  name: string
  role_definition: string
  tone: string
  style_rules: string
  constraints: string
}

/**
 * 新建 / 修改角色的请求体。
 *
 * 注意：PATCH /personas/{id} 是**整体替换**，省略 style_rules / constraints
 * 会被后端写成空字符串，所以调用时五个字段都要带上。
 */
export interface PersonaInput {
  name: string
  role_definition: string
  tone: string
  style_rules: string
  constraints: string
}

/** GET /personas —— 系统预设在前，自建角色按更新时间倒序 */
export function listPersonas(): Promise<Persona[]> {
  return request<Persona[]>('/personas')
}

/** POST /personas -> 201，owner_id 与 version/is_system 由后端设置 */
export function createPersona(body: PersonaInput): Promise<Persona> {
  return request<Persona>('/personas', { method: 'POST', data: { ...body } })
}

/** PATCH /personas/{id} —— 只有本人自建角色可改，version 自增 */
export function updatePersona(id: number, body: PersonaInput): Promise<Persona> {
  return request<Persona>(`/personas/${encodeURIComponent(String(id))}`, {
    method: PATCH_METHOD,
    data: { ...body },
  })
}

/** DELETE /personas/{id} -> 204 */
export function deletePersona(id: number): Promise<void> {
  return request<void>(`/personas/${encodeURIComponent(String(id))}`, { method: 'DELETE' })
}

/** GET /users/me/default-persona —— 未设置默认时后端回落到系统预设 */
export function getDefaultPersona(): Promise<Persona> {
  return request<Persona>('/users/me/default-persona')
}

/**
 * PATCH /users/me/default-persona
 * 传 null 表示取消个人默认、回到系统预设，此时**响应体就是 null**。
 */
export function setDefaultPersona(personaId: number | null): Promise<Persona | null> {
  return request<Persona | null>('/users/me/default-persona', {
    method: PATCH_METHOD,
    data: { persona_id: personaId },
  })
}

/**
 * GET /conversations/{thread_id}/persona —— 该会话当前的角色快照。
 * 注意：thread 不存在时**不会 404**，而是回落到账号默认 / 系统预设。
 */
export function getConversationPersona(threadId: string): Promise<Persona> {
  return request<Persona>(`/conversations/${encodeURIComponent(threadId)}/persona`)
}

/**
 * PATCH /conversations/{thread_id}/persona —— 从下一条消息起切换角色。
 * 全新会话（还没有消息、没有 conversations 行）会返回 404 会话不存在。
 */
export function setConversationPersona(threadId: string, personaId: number): Promise<Persona> {
  return request<Persona>(`/conversations/${encodeURIComponent(threadId)}/persona`, {
    method: PATCH_METHOD,
    data: { persona_id: personaId },
  })
}

/** 会话元数据（收藏 / 标签）的更新结果 */
export interface ConversationMetadata {
  thread_id: string
  is_favorite: boolean
  tags: string[]
}

/**
 * PATCH /conversations/{thread_id}/metadata
 * 只提交要改的键；tags 最多 8 个、每个 strip 后 1~24 字符，空数组表示清空。
 * 返回值里的 tags 是后端去重后的结果，以它为准。
 */
export function updateConversationMetadata(
  threadId: string,
  changes: { is_favorite?: boolean; tags?: string[] },
): Promise<ConversationMetadata> {
  return request<ConversationMetadata>(
    `/conversations/${encodeURIComponent(threadId)}/metadata`,
    { method: PATCH_METHOD, data: { ...changes } },
  )
}

/** GET /conversations/search?q= —— 仅按标题搜索，后端最多返回 50 条 */
export function searchConversations(query: string): Promise<ConversationSearchResult[]> {
  return request<ConversationSearchResult[]>(
    `/conversations/search?q=${encodeURIComponent(query)}`,
  )
}

/** 个人模型连接状态。API Key 永远不会回显，`configured` 是唯一信号。 */
export interface ModelConfigStatus {
  configured: boolean
  storage_ready: boolean
  base_url: string
  model_name: string
  updated_at: string | null
  last_used_at: string | null
  default_model_name: string
}

export interface ModelConfigInput {
  base_url: string
  model_name: string
  /** 已保存过 Key 且 Base URL 未变时可以省略，表示沿用原 Key */
  api_key?: string
}

/** GET /settings/model */
export function getModelConfig(): Promise<ModelConfigStatus> {
  return request<ModelConfigStatus>('/settings/model')
}

/** PUT /settings/model（后端是 PUT；POST 会 405） */
export function saveModelConfig(body: ModelConfigInput): Promise<ModelConfigStatus> {
  return request<ModelConfigStatus>('/settings/model', { method: 'PUT', data: { ...body } })
}

/** DELETE /settings/model —— 返回删除后的状态对象（不是 204） */
export function deleteModelConfig(): Promise<ModelConfigStatus> {
  return request<ModelConfigStatus>('/settings/model', { method: 'DELETE' })
}

/** POST /settings/model/test —— 只发一条固定短消息，不落库、不更新 last_used_at */
export function testModelConfig(body: ModelConfigInput): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>('/settings/model/test', {
    method: 'POST',
    data: { ...body },
  })
}

/** POST /auth/password（后端是 POST；PATCH 会 405） */
export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ message: string }> {
  return request<{ message: string }>('/auth/password', {
    method: 'POST',
    data: { old_password: oldPassword, new_password: newPassword },
  })
}

/** 流式回合的控制结果 */
export interface TurnControlResult {
  status: 'queued' | 'running' | 'paused' | 'cancelled' | 'completed' | string
  last_sent_seq: number
}

/**
 * POST /chat/turns/{turn_id}/pause|resume|cancel
 *
 * 回合结束后（或服务重启、多 worker 落到别的进程）会返回 404
 * `生成任务不存在或已结束` —— 对调用方来说这只代表「这一轮已经结束了」。
 */
export function controlChatTurn(
  turnId: string,
  action: 'pause' | 'resume' | 'cancel',
): Promise<TurnControlResult> {
  return request<TurnControlResult>(`/chat/turns/${encodeURIComponent(turnId)}/${action}`, {
    method: 'POST',
    data: {},
  })
}

