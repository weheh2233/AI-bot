import { defineStore } from 'pinia'
import {
  controlChatTurn,
  deleteConversation,
  getConversation,
  listConversations,
  resumeChat,
  searchConversations,
  streamChat,
  updateConversationMetadata,
  updateConversationTitle,
} from '@/api'
import type { ApprovalPayload, ConversationSummary, Decision } from '@/api'
import { pickMockReply, playMockReply, shouldUseMockReply } from '@/data/mock-replies'
import { useAuthStore } from '@/stores/auth'
import { usePersonaStore } from '@/stores/persona'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { nextMessageId } from '@/utils/format'
import { makeThreadId } from '@/utils/thread'

export interface UiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[]
  /** 正在流式输出，此时按纯文本渲染 */
  streaming?: boolean
  error?: boolean
  /** 消息时间（ISO），用于气泡下方的时间标签 */
  timestamp?: string | null
  /** 助手这一轮的耗时（秒），用于 .elapsed-time */
  elapsed?: number | null
  /** 模型/网络不可用时由前端兜底的演示回答 */
  mock?: boolean
}

/** 欢迎区的三种形态，与原站三处 innerHTML 一一对应。 */
export type WelcomeMode = 'default' | 'new' | 'history'

/** 历史会话的分组筛选 */
export type HistoryFilter = 'all' | 'favorites'

export type TurnStatus = 'idle' | 'streaming' | 'paused'

function nowIso(): string {
  return new Date().toISOString()
}

/** 客户端生成的回合 ID（后端接受客户端自带 turn_id） */
function makeTurnId(): string {
  return `turn-${makeThreadId().replace(/^web-/, '')}`
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    threadId: '',
    conversationTitle: null as string | null,
    messages: [] as UiMessage[],
    welcomeMode: 'default' as WelcomeMode | null,
    busy: false,
    /** 本轮 SSE 的 turn id，暂停/继续/停止都要用它 */
    turnId: '',
    turnStatus: 'idle' as TurnStatus,
    /** 本会话当前角色 id，发送消息时带给后端 */
    personaId: null as number | null,

    history: [] as ConversationSummary[],
    historyPlaceholder: '登录后查看历史对话。',
    historyIsError: false,
    /** 历史页的搜索关键词（走后端 /conversations/search） */
    historyQuery: '',
    /** 历史页的标签筛选，空串表示不限 */
    historyTag: '',
    /** 历史页的分组：全部 / 收藏夹 */
    historyFilter: 'all' as HistoryFilter,

    pendingApproval: null as ApprovalPayload | null,
  }),

  getters: {
    awaitingApproval: (state) => Boolean(state.pendingApproval),
    lastAssistant: (state) => {
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        if (state.messages[i].role === 'assistant') return state.messages[i]
      }
      return null
    },
    lastUser: (state) => {
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        if (state.messages[i].role === 'user') return state.messages[i]
      }
      return null
    },
    /** 流式进行中可以暂停/停止 */
    canControlTurn: (state) => state.turnStatus !== 'idle',
    isPaused: (state) => state.turnStatus === 'paused',

    /** 所有出现过的标签，供筛选下拉使用 */
    historyTags: (state) => {
      const seen = new Set<string>()
      for (const item of state.history) {
        for (const tag of item.tags || []) seen.add(tag)
      }
      return Array.from(seen).sort()
    },

    /**
     * 应用「全部/收藏夹」+ 标签过滤后的列表。
     * 关键词过滤由后端 /conversations/search 完成（标题 + 正文），
     * 这里不能再按标题筛一遍，否则正文命中的会话会被丢掉。
     */
    filteredHistory: (state) => {
      return state.history.filter((item) => {
        if (state.historyFilter === 'favorites' && !item.is_favorite) return false
        if (state.historyTag && !(item.tags || []).includes(state.historyTag)) return false
        return true
      })
    },
  },

  actions: {
    /**
     * 启动初始化：每次冷启动都进入一个全新的会话。
     * 不再从本地存储恢复旧 thread_id —— 旧逻辑会把上回的会话 ID 带进来，
     * 却不加载该会话的消息，看起来就像在旧会话里得到一片空白。
     * 历史会话只能由用户从「历史会话」列表主动打开。
     */
    restoreThread() {
      this.resetConversation()
      this.welcomeMode = 'default'
    },

    /** 新建会话：换一个 thread_id 并清空消息。 */
    resetConversation() {
      this.closeApproval()
      this.busy = false
      this.turnId = ''
      this.turnStatus = 'idle'
      this.threadId = makeThreadId()
      this.conversationTitle = null
      this.messages = []
      this.welcomeMode = 'new'
      this.personaId = null

      // 会话角色快照属于上一个会话，必须一起清掉，
      // 否则「新建会话」后角色栏还会显示上一轮的“本会话角色”。
      const persona = usePersonaStore()
      persona.conversationPersona = null
      persona.conversationVersion = 0
    },

    resetUserWorkspace() {
      this.resetConversation()
      this.welcomeMode = 'default'
      this.history = []
      this.historyPlaceholder = '登录后查看历史对话。'
      this.historyIsError = false
      this.historyQuery = ''
      this.historyTag = ''
      this.historyFilter = 'all'
    },

    openApproval(payload: ApprovalPayload) {
      this.pendingApproval = payload
      useUiStore().setApprovalVisible(true)
    },

    closeApproval() {
      this.pendingApproval = null
      useUiStore().setApprovalVisible(false)
    },

    /* ---------------- 会话列表 ---------------- */

    async loadHistoryTitles(limit = 20) {
      // 回到普通列表时清空搜索词，避免输入框和过滤条件不同步
      this.historyQuery = ''
      const auth = useAuthStore()
      if (!auth.loggedIn) {
        this.history = []
        this.historyPlaceholder = '登录后查看历史对话。'
        this.historyIsError = false
        return
      }
      this.historyPlaceholder = '正在读取…'
      this.historyIsError = false
      try {
        this.history = await listConversations(limit)
        this.historyPlaceholder = this.history.length ? '' : '还没有历史对话。'
      } catch (error) {
        this.history = []
        this.historyPlaceholder = error instanceof Error ? error.message : '历史对话读取失败'
        this.historyIsError = true
      }
    },

    /** 后端按标题和正文搜索；清空关键词时回到普通列表 */
    async searchHistory(query: string, limit = 50) {
      const keyword = query.trim()
      this.historyQuery = keyword
      if (!keyword) {
        await this.loadHistoryTitles(limit)
        return
      }
      this.historyIsError = false
      try {
        this.history = await searchConversations(keyword)
        this.historyPlaceholder = this.history.length ? '' : '没有匹配的会话。'
      } catch (error) {
        this.history = []
        this.historyPlaceholder = error instanceof Error ? error.message : '搜索失败'
        this.historyIsError = true
      }
    },

    setHistoryFilter(filter: HistoryFilter) {
      this.historyFilter = filter
    },

    setHistoryTag(tag: string) {
      this.historyTag = tag
    },

    async toggleFavorite(threadId: string) {
      const target = this.history.find((item) => item.thread_id === threadId)
      const next = !target?.is_favorite
      if (target) target.is_favorite = next
      try {
        const result = await updateConversationMetadata(threadId, { is_favorite: next })
        if (target) target.is_favorite = result.is_favorite
        return result.is_favorite
      } catch (error) {
        if (target) target.is_favorite = !next
        useUiStore().notify(error instanceof Error ? error.message : '收藏失败', true)
        return next === false
      }
    },

    /** 标签以服务端去重后的结果为准 */
    async setConversationTags(threadId: string, tags: string[]) {
      const result = await updateConversationMetadata(threadId, { tags })
      const target = this.history.find((item) => item.thread_id === threadId)
      if (target) target.tags = result.tags
      return result.tags
    },

    /* ---------------- 单个会话 ---------------- */

    async loadConversation(threadId: string) {
      const conversation = await getConversation(threadId)
      this.threadId = conversation.thread_id
      this.conversationTitle = conversation.title || null
      this.messages = (conversation.messages || []).map((message) => ({
        id: nextMessageId(),
        role: message.role,
        content: message.content,
        images: message.images,
        timestamp: message.timestamp ?? null,
        elapsed: message.elapsed ?? null,
      }))
      this.welcomeMode = this.messages.length ? null : 'history'
      this.turnStatus = 'idle'
      this.turnId = ''

      // 同步该会话当前角色，供「本会话角色」栏使用
      const persona = usePersonaStore()
      await persona.loadConversationPersona(this.threadId)
      this.personaId = persona.conversationPersona?.id ?? null

      if (conversation.awaiting_approval) this.openApproval(conversation)
      else this.closeApproval()
    },

    async deleteConversation(threadId: string) {
      await deleteConversation(threadId)
      if (threadId === this.threadId) {
        this.resetConversation()
        this.welcomeMode = 'default'
      }
      await this.loadHistoryTitles()
    },

    async saveConversationTitle(title: string) {
      const result = await updateConversationTitle(this.threadId, title)
      this.conversationTitle = result.title || title
      await this.loadHistoryTitles()
    },

    async syncConversationTitle() {
      const auth = useAuthStore()
      if (!auth.loggedIn) return
      try {
        const conversation = await getConversation(this.threadId)
        this.conversationTitle = conversation.title || null
      } catch (error) {
        const message = error instanceof Error ? error.message : ''
        if (message.includes('会话不存在')) this.conversationTitle = null
      }
    },

    /* ---------------- 发送与流式 ---------------- */

    /**
     * 发送一条消息并流式接收回复。
     *
     * turn_id 由客户端生成（后端允许，且暂停/继续/停止都要用它），
     * 首帧 {"type":"started"} 会带回服务端的确认值。
     */
    async sendMessage(
      rawText: string,
      options: { regenerate?: boolean; images?: string[] } = {},
    ) {
      const text = rawText.trim()
      const regenerate = Boolean(options.regenerate)
      const images = regenerate ? [] : (options.images || []).filter(Boolean)
      if (!regenerate && !text && !images.length) return
      if (this.busy) return

      if (!regenerate) {
        this.messages.push({
          id: nextMessageId(),
          role: 'user',
          content: text,
          images: images.length ? images : undefined,
          timestamp: nowIso(),
        })
        this.welcomeMode = null
      }

      const target: UiMessage = {
        id: nextMessageId(),
        role: 'assistant',
        content: '',
        streaming: true,
        timestamp: nowIso(),
      }
      this.messages.push(target)

      // push 之后必须从数组里重新取一次：Pinia 的 state 是响应式代理，
      // 只有通过代理修改属性才会触发视图更新。直接改原始 target 对象
      // 内容会累加，但界面不会刷新（要重新进入会话才看得到）。
      const streamTarget = this.messages[this.messages.length - 1]

      this.busy = true
      this.turnStatus = 'streaming'
      this.turnId = makeTurnId()
      let interrupted = false
      /** 本轮是否使用了本地 Mock（设置页手动切换，或异常兜底） */
      let usedMock = false
      /** 模型/网络异常时启动的离线兜底播放，需要在流结束后等它播完 */
      let mockPlayback: Promise<void> | null = null

      const startMockReply = (): Promise<void> => {
        return playMockReply(
          streamTarget,
          pickMockReply(text, {
            hasImages: images.length > 0,
            threadId: this.threadId,
          }),
        )
      }

      try {
        // 设置页切到 Mock 离线模拟时，完全不发网络请求，直接播放本地回答。
        if (useSettingsStore().mockMode) {
          usedMock = true
          await startMockReply()
          return
        }

        await streamChat(
          {
            message: regenerate ? text || '重新生成上一条回复' : text,
            images: images.length ? images : undefined,
            thread_id: this.threadId,
            persona_id: this.personaId,
            turn_id: this.turnId,
            regenerate,
          },
          {
            onStart: (turnId) => {
              if (turnId) this.turnId = turnId
            },
            onDelta: (delta) => {
              streamTarget.content += delta
            },
            onApproval: (payload) => {
              interrupted = true
              // 这一轮还没有任何文本时，把占位的空气泡去掉
              if (!streamTarget.content) {
                const index = this.messages.findIndex((m) => m.id === target.id)
                if (index >= 0) this.messages.splice(index, 1)
              }
              this.openApproval(payload)
            },
            onDone: (_paused, elapsed) => {
              if (typeof elapsed === 'number') streamTarget.elapsed = elapsed
            },
            onCancelled: () => {
              if (!streamTarget.content) streamTarget.content = '（已停止生成）'
            },
            onError: (message) => {
              // 模型/网络不可用时用离线回答兜底；登录失效、配额等业务错误仍按原文提示。
              if (shouldUseMockReply(message)) {
                usedMock = true
                mockPlayback = startMockReply()
                return
              }
              streamTarget.error = true
              streamTarget.streaming = false
              streamTarget.content = message
            },
          },
        )

        if (mockPlayback) await mockPlayback

        if (!streamTarget.content && !interrupted && !streamTarget.error) {
          streamTarget.content = '（没有收到文本回复）'
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : '请求失败'
        if (shouldUseMockReply(message)) {
          usedMock = true
          await startMockReply()
        } else {
          streamTarget.error = true
          streamTarget.streaming = false
          streamTarget.content = message
        }
      } finally {
        streamTarget.streaming = false
        this.busy = false
        this.turnStatus = 'idle'
        // Mock 模式没有写入服务端，不需要刷新历史或标题。
        if (!usedMock) {
          void this.loadHistoryTitles()
          void this.syncConversationTitle()
        }
      }
    },

    /** 重新生成最后一条回复（只有流式接口支持） */
    async regenerateLast() {
      const lastUser = this.lastUser
      if (!lastUser) return
      for (let i = this.messages.length - 1; i >= 0; i -= 1) {
        if (this.messages[i].role === 'assistant') {
          this.messages.splice(i, 1)
          break
        }
      }
      await this.sendMessage(lastUser.content, { regenerate: true })
    },

    /** 暂停 / 继续当前这一轮 */
    async togglePause() {
      if (this.turnStatus === 'idle' || !this.turnId) return
      const action = this.turnStatus === 'paused' ? 'resume' : 'pause'
      try {
        const result = await controlChatTurn(this.turnId, action)
        this.turnStatus = result.status === 'paused' ? 'paused' : 'streaming'
      } catch (error) {
        const message = error instanceof Error ? error.message : ''
        // 404 表示这一轮已经结束，不是错误
        if (message.includes('生成任务不存在')) {
          this.turnStatus = 'idle'
          return
        }
        useUiStore().notify(message || '操作失败', true)
      }
    },

    /** 停止生成 */
    async cancelTurn() {
      if (!this.turnId) return
      try {
        await controlChatTurn(this.turnId, 'cancel')
      } catch (error) {
        const message = error instanceof Error ? error.message : ''
        if (!message.includes('生成任务不存在')) {
          useUiStore().notify(message || '停止失败', true)
        }
      } finally {
        this.turnStatus = 'idle'
      }
    },

    /**
     * 提交人工审批决定并继续执行。
     * 失败时向上抛，由审批弹窗原地显示错误并允许重试。
     */
    async submitDecisions(decisions: Decision[]) {
      this.busy = true
      try {
        const result = await resumeChat(this.threadId, decisions)
        this.closeApproval()
        if (result.status === 'awaiting_approval') {
          this.openApproval({
            status: 'awaiting_approval',
            action_requests: result.action_requests || [],
            review_configs: result.review_configs || [],
          })
        } else {
          this.messages.push({
            id: nextMessageId(),
            role: 'assistant',
            content: result.reply || '（操作已完成）',
            timestamp: nowIso(),
            elapsed: result.elapsed ?? null,
          })
        }
      } finally {
        this.busy = false
        void this.loadHistoryTitles()
      }
    },
  },
})
