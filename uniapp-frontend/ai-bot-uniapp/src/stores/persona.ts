/**
 * 角色设定 store（对应原站 web 端的角色模块）。
 *
 * 后端事实（踩过的坑，改动前先读一遍）：
 * - PATCH /personas/{id} 是整体替换，五个字段必须全量发送，否则没发的字段会被清成 ""；
 * - 系统预设（is_system）对所有人可见，但改删都会返回 404 角色不存在或不可修改，
 *   只能「复制为我的角色」；
 * - setDefaultPersona(null) 会清空默认并 resolve 成 null，读 .id 之前必须先判空；
 * - PATCH /conversations/{tid}/persona 要求会话行已存在，全新会话会 404 会话不存在；
 * - 每次编辑 version 自增，会话里保存的是当时的快照，快照旧于线上版本时才提示「应用最新版」。
 */

import { defineStore } from 'pinia'
import {
  createPersona,
  deletePersona,
  getConversationPersona,
  getDefaultPersona,
  listPersonas,
  setConversationPersona,
  setDefaultPersona,
  updatePersona,
} from '@/api'
import { RequestError } from '@/api/request'
import type { Persona, PersonaInput } from '@/api'

/** 未登录 / 刚初始化时的占位文案 */
const SIGNED_OUT_PLACEHOLDER = '登录后查看可用角色。'
/** 读取成功但一个角色都没有时的占位文案 */
const EMPTY_PLACEHOLDER = '还没有可用角色。先创建一个，或把系统预设复制成自己的角色。'
/** 名称上限 80，复制出来的角色名必须仍然合法 */
const NAME_MAX = 80
const COPY_SUFFIX = '（副本）'

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/** 系统预设排在前面，其余保持后端返回的相对顺序（sort 是稳定排序） */
function sortSystemFirst(personas: Persona[]): Persona[] {
  return [...personas].sort((a, b) => Number(b.is_system) - Number(a.is_system))
}

/**
 * 部分接口（create / update）返回的可能是完整实体，也可能只回一份精简结果；
 * 这里按 id 覆盖写入列表，保证「改了立刻能看到」。
 */
function mergePersona(list: Persona[], persona: Persona): Persona[] {
  const others = persona.id === null ? list : list.filter((item) => item.id !== persona.id)
  return sortSystemFirst([...others, persona])
}

/**
 * 整理成后端要求的五字段全量请求体。
 * PATCH 是整体替换，缺字段会被清空成 ""，所以这里主动补 ""，
 * 即便调用方（或未来放宽的 PersonaInput）漏传可选字段也不会误删用户内容。
 */
function toFullInput(input: PersonaInput): PersonaInput {
  return {
    name: input.name,
    role_definition: input.role_definition,
    tone: input.tone,
    style_rules: input.style_rules ?? '',
    constraints: input.constraints ?? '',
  }
}

/** 复制系统预设时生成一个不与现有角色重名的名字，且不超过 80 字 */
function duplicateName(name: string, taken: string[]): string {
  const base = (name || '未命名角色').slice(0, NAME_MAX)
  let candidate = `${base.slice(0, NAME_MAX - COPY_SUFFIX.length)}${COPY_SUFFIX}`
  let index = 2
  while (taken.includes(candidate)) {
    const suffix = `（副本 ${index}）`
    candidate = `${base.slice(0, NAME_MAX - suffix.length)}${suffix}`
    index += 1
  }
  return candidate
}

/** 全新会话没有会话行，PATCH 会 404；这不是异常，而是「发第一条消息后生效」 */
function isMissingConversation(error: unknown): boolean {
  if (error instanceof RequestError) return error.status === 404
  return error instanceof Error && error.message.includes('会话不存在')
}

export const usePersonaStore = defineStore('persona', {
  state: () => ({
    /** 当前账号可见的全部角色，系统预设在前 */
    list: [] as Persona[],
    loading: false,
    /** 新会话默认角色 id；后端可能返回 null（表示没有默认） */
    defaultPersonaId: null as number | null,
    /** 新会话默认角色的完整实体，未设置时为 null */
    defaultPersona: null as Persona | null,
    /** 当前会话保存的角色快照（由会话接口返回，可能落后于 list 里的线上版本） */
    conversationPersona: null as Persona | null,
    /** 会话快照版本号，等价于 conversationPersona?.version ?? 0 */
    conversationVersion: 0,
    /** 角色库空状态文案；读取失败时这里就是错误信息 */
    placeholder: SIGNED_OUT_PLACEHOLDER,
  }),

  getters: {
    /** 自己创建的角色（可编辑、可删除） */
    customPersonas: (state): Persona[] => state.list.filter((item) => !item.is_system),

    /** 系统预设（只读，只能复制） */
    systemPersonas: (state): Persona[] => state.list.filter((item) => item.is_system),

    /** 会话绑定角色在角色库里的最新版本；找不到（已删除 / 未加载）时为 null */
    latestOfConversation: (state): Persona | null => {
      const snapshot = state.conversationPersona
      if (!snapshot || snapshot.id === null) return null
      return state.list.find((item) => item.id === snapshot.id) ?? null
    },

    /** 线上版本比会话快照更新时，才显示「应用角色最新版」 */
    canApplyLatest: (state): boolean => {
      const snapshot = state.conversationPersona
      if (!snapshot || snapshot.id === null) return false
      const live = state.list.find((item) => item.id === snapshot.id)
      return live !== undefined && live.version > state.conversationVersion
    },
  },

  actions: {
    /** 退出登录时清空所有角色状态 */
    reset() {
      this.list = []
      this.loading = false
      this.defaultPersonaId = null
      this.defaultPersona = null
      this.conversationPersona = null
      this.conversationVersion = 0
      this.placeholder = SIGNED_OUT_PLACEHOLDER
    },

    /**
     * 读取角色库 + 默认角色。**绝不抛错**：失败信息写进 placeholder，
     * 由角色库的空状态展示；默认角色单独兜底，它失败不该让整个角色库不可用。
     */
    async load(): Promise<void> {
      this.loading = true
      this.placeholder = '正在读取角色…'

      let listError = ''
      try {
        this.list = sortSystemFirst(await listPersonas())
      } catch (error) {
        this.list = []
        listError = errorText(error, '角色读取失败')
      }

      await this.refreshDefault()

      if (this.list.length) this.placeholder = ''
      else this.placeholder = listError || EMPTY_PLACEHOLDER

      this.loading = false
    },

    /** 只刷新默认角色；没有默认角色时后端返回 null，这里必须先判空再读 .id */
    async refreshDefault(): Promise<void> {
      try {
        const current = await getDefaultPersona()
        this.defaultPersona = current ?? null
        this.defaultPersonaId = current && current.id !== null ? current.id : null
      } catch {
        this.defaultPersona = null
        this.defaultPersonaId = null
      }
    },

    async create(input: PersonaInput): Promise<Persona> {
      const created = await createPersona(toFullInput(input))
      this.list = mergePersona(this.list, created)
      this.placeholder = ''
      return created
    },

    async update(id: number, input: PersonaInput): Promise<Persona> {
      const updated = await updatePersona(id, toFullInput(input))
      this.list = mergePersona(this.list, updated)
      // 默认角色被编辑后，新会话要拿到新的定义
      if (this.defaultPersonaId === id) this.defaultPersona = updated
      return updated
    },

    /** 删除自己的角色；系统预设后端会回 404，组件层已隐藏入口 */
    async remove(persona: Persona): Promise<void> {
      const id = persona.id
      if (id === null) throw new Error('这个角色没有可用的编号，无法删除')
      await deletePersona(id)
      this.list = this.list.filter((item) => item.id !== id)
      if (this.defaultPersonaId === id) {
        this.defaultPersonaId = null
        this.defaultPersona = null
      }
      // 会话里保存的是历史快照，保留它；线上角色没了，latestOfConversation 自然为 null
      if (!this.list.length) this.placeholder = EMPTY_PLACEHOLDER
    },

    /** 设置新会话默认角色；personaId 为 null 表示清空默认（后端 resolve null） */
    async makeDefault(personaId: number | null): Promise<void> {
      const result = await setDefaultPersona(personaId)
      if (result && result.id !== null) {
        this.defaultPersona = result
        this.defaultPersonaId = result.id
      } else {
        this.defaultPersona = null
        this.defaultPersonaId = null
      }
    },

    /** 读取当前会话的角色快照；会话不存在 / 接口失败一律吞掉并置 null */
    async loadConversationPersona(threadId: string): Promise<void> {
      try {
        const snapshot = await getConversationPersona(threadId)
        this.conversationPersona = snapshot ?? null
      } catch {
        this.conversationPersona = null
      }
      this.conversationVersion = this.conversationPersona?.version ?? 0
    },

    /**
     * 给会话绑定角色。全新会话还没有会话行时会 404，
     * 这里翻译成能直接展示的提示，由调用方 toast 出去。
     */
    async applyToConversation(threadId: string, personaId: number): Promise<void> {
      try {
        const applied = await setConversationPersona(threadId, personaId)
        this.conversationPersona = applied ?? null
        this.conversationVersion = applied?.version ?? 0
      } catch (error) {
        if (isMissingConversation(error)) {
          throw new Error('该会话还没有消息，角色会在发出第一条消息后生效')
        }
        // 其余错误保留原始实例（RequestError 带 status，调用方可能需要）
        throw error
      }
    },

    /** 「应用角色最新版」：拿同一个 id 再 PATCH 一次，把会话快照刷到最新版本 */
    async applyLatest(threadId: string): Promise<void> {
      const snapshot = this.conversationPersona
      const live =
        snapshot && snapshot.id !== null
          ? this.list.find((item) => item.id === snapshot.id) ?? null
          : null
      const personaId = live?.id ?? snapshot?.id ?? null
      if (personaId === null) throw new Error('当前会话还没有可应用的角色')
      await this.applyToConversation(threadId, personaId)
    },

    /** 把系统预设（或任何只读角色）复制成自己的角色 */
    async duplicate(persona: Persona): Promise<Persona> {
      const taken = this.list.map((item) => item.name)
      return this.create({
        name: duplicateName(persona.name, taken),
        role_definition: persona.role_definition,
        tone: persona.tone,
        style_rules: persona.style_rules,
        constraints: persona.constraints,
      })
    },
  },
})
