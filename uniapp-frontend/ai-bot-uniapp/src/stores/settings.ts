/**
 * 个人设置 store：模型连接 + 外观偏好 + 修改密码。
 *
 * 与原站 web 端的差异：
 * - 原站把字体大小 / 发送快捷键分别存在 `ai_bot_font_size`、`ai_bot_send_key`，
 *   这里合并成一份 JSON 存到 `ai_bot_appearance`，读取时按字段各自校验并回落默认值；
 * - 原站直接操作 DOM，这里只维护状态，页面由 SettingsView.vue 渲染；
 * - 全局 CSS 用 `.settings-choice.is-active` 表示选中项（uni-app 无法用 :has(input:checked)），
 *   所以选中态从本 store 的 appearance 派生。
 */

import { defineStore } from 'pinia'
import {
  changePassword,
  deleteModelConfig,
  getModelConfig,
  saveModelConfig,
  testModelConfig,
} from '@/api'
import type { ModelConfigInput, ModelConfigStatus } from '@/api'
import { useUiStore } from '@/stores/ui'

/** 字体大小档位 */
export type FontSize = 'small' | 'standard' | 'large'
/** 发送快捷键：Enter 发送 / Ctrl + Enter 发送 */
export type SendKey = 'enter' | 'ctrl-enter'

/** 外观偏好 */
export interface Appearance {
  fontSize: FontSize
  sendKey: SendKey
}

/** 外观偏好的本地存储键 */
const APPEARANCE_STORAGE_KEY = 'ai_bot_appearance'
/** 回答来源偏好：'1' 表示 Mock 离线模拟，其它值表示真实模型 */
const MOCK_MODE_STORAGE_KEY = 'ai_bot_mock_mode'

/** 默认外观：标准 + Enter 发送 */
const DEFAULT_APPEARANCE: Appearance = { fontSize: 'standard', sendKey: 'enter' }

const FONT_SIZES: readonly FontSize[] = ['small', 'standard', 'large']
const SEND_KEYS: readonly SendKey[] = ['enter', 'ctrl-enter']

const FONT_SIZE_LABELS: Record<FontSize, string> = {
  small: '小',
  standard: '标准',
  large: '大',
}

/** 字号档位对应的缩放倍数（CSS 变量 --font-scale 与 rich-text 内联字号共用） */
const FONT_SCALES: Record<FontSize, number> = {
  small: 0.88,
  standard: 1,
  large: 1.18,
}

const SEND_KEY_LABELS: Record<SendKey, string> = {
  enter: 'Enter',
  'ctrl-enter': 'Ctrl + Enter',
}

/** 每次返回新对象，避免多处共享同一个默认值引用 */
function defaultAppearance(): Appearance {
  return { fontSize: DEFAULT_APPEARANCE.fontSize, sendKey: DEFAULT_APPEARANCE.sendKey }
}

/**
 * 把存储里的任意值解析成外观偏好。
 *
 * 兼容两种形态：JSON 字符串（我们写入的）与已被 uni 解析好的对象；
 * JSON 损坏、字段类型不对或取值越界时返回 null 或对应字段的默认值。
 */
function parseAppearance(raw: unknown): Appearance | null {
  if (!raw) return null

  let value: unknown = raw
  if (typeof raw === 'string') {
    try {
      value = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (!value || typeof value !== 'object') return null

  const record = value as Record<string, unknown>
  const fontSize = record.fontSize
  const sendKey = record.sendKey
  return {
    fontSize: FONT_SIZES.includes(fontSize as FontSize)
      ? (fontSize as FontSize)
      : DEFAULT_APPEARANCE.fontSize,
    sendKey: SEND_KEYS.includes(sendKey as SendKey)
      ? (sendKey as SendKey)
      : DEFAULT_APPEARANCE.sendKey,
  }
}

/** 读取外观偏好；任何异常（存储不可用、JSON 损坏）都回落默认值 */
function readAppearance(): Appearance {
  try {
    if (typeof uni === 'undefined') return defaultAppearance()
    const raw: unknown = uni.getStorageSync(APPEARANCE_STORAGE_KEY)
    return parseAppearance(raw) || defaultAppearance()
  } catch {
    return defaultAppearance()
  }
}

/** 写入外观偏好；存储不可用时静默降级为仅内存态 */
function persistAppearance(appearance: Appearance) {
  try {
    if (typeof uni === 'undefined') return
    uni.setStorageSync(APPEARANCE_STORAGE_KEY, JSON.stringify(appearance))
  } catch {
    // 忽略写入失败
  }
}

/** 读取回答来源偏好；存储不可用或未设置时默认使用真实模型 */
function readMockMode(): boolean {
  try {
    if (typeof uni === 'undefined') return false
    const raw: unknown = uni.getStorageSync(MOCK_MODE_STORAGE_KEY)
    return raw === '1' || raw === 1 || raw === true
  } catch {
    return false
  }
}

/** 后端错误信息已经是中文可直接展示，这里只补一个兜底文案 */
function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    /** 个人模型配置状态；未读取到（或读取失败）时为 null */
    model: null as ModelConfigStatus | null,
    modelLoading: false,
    modelSaving: false,
    modelTesting: false,
    /** 测试连接的结果文案，由 testModel 写入 */
    testMessage: '',
    appearance: defaultAppearance() as Appearance,
    /** true 表示不调用真实模型，直接使用本地 Mock 回答 */
    mockMode: readMockMode(),
  }),

  getters: {
    /** '已配置 · <model_name>' | '使用服务器默认模型' | '正在读取…' */
    modelStatusText: (state): string => {
      if (state.modelLoading) return '正在读取…'
      const model = state.model
      if (!model || !model.configured) return '使用服务器默认模型'
      const name = model.model_name || model.default_model_name
      return name ? `已配置 · ${name}` : '已配置'
    },

    /** 形如 '标准 · Enter' */
    appearanceStatusText: (state): string =>
      `${FONT_SIZE_LABELS[state.appearance.fontSize]} · ${SEND_KEY_LABELS[state.appearance.sendKey]}`,

    fontSizeLabel: (state): string => FONT_SIZE_LABELS[state.appearance.fontSize],

    fontScale: (state): number => FONT_SCALES[state.appearance.fontSize] ?? 1,

    sendKeyLabel: (state): string => SEND_KEY_LABELS[state.appearance.sendKey],
  },

  actions: {
    /** 退出登录时清空所有个人设置状态（外观与回答来源偏好保留在本地存储里） */
    reset(): void {
      this.model = null
      this.modelLoading = false
      this.modelSaving = false
      this.modelTesting = false
      this.testMessage = ''
      this.appearance = defaultAppearance()
      // 清除缓存时存储已被删除，这里读到的就是默认 false。
      this.mockMode = readMockMode()
    },

    /** 切换回答来源：true = Mock 离线模拟，false = 真实模型 */
    setMockMode(enabled: boolean): void {
      this.mockMode = enabled
      try {
        if (typeof uni !== 'undefined') {
          uni.setStorageSync(MOCK_MODE_STORAGE_KEY, enabled ? '1' : '0')
        }
      } catch {
        // 存储不可用时只保留内存态
      }
    },

    /** 读取个人模型配置；容错，失败只提示不抛出 */
    async loadModel(): Promise<void> {
      this.modelLoading = true
      try {
        this.model = await getModelConfig()
      } catch (error) {
        useUiStore().notify(errorText(error, '模型配置读取失败'), true)
      } finally {
        this.modelLoading = false
      }
    },

    /** 保存个人模型配置（PUT）；失败向上抛出，由页面展示后端文案 */
    async saveModel(input: ModelConfigInput): Promise<void> {
      this.modelSaving = true
      try {
        this.model = await saveModelConfig(input)
      } finally {
        this.modelSaving = false
      }
    },

    /** 删除个人 Key 并恢复服务器默认模型；接口返回的是删除后的新状态 */
    async deleteModel(): Promise<void> {
      this.modelSaving = true
      try {
        this.model = await deleteModelConfig()
        this.testMessage = ''
      } finally {
        this.modelSaving = false
      }
    },

    /**
     * 测试连接（POST /settings/model/test）。
     *
     * 该接口不写入任何配置、也不更新 last_used_at，
     * 因此这里只写 testMessage，绝不改动 model / configured。
     */
    async testModel(input: ModelConfigInput): Promise<void> {
      this.modelTesting = true
      this.testMessage = ''
      try {
        const result = await testModelConfig(input)
        this.testMessage = result.message || (result.ok ? '连接成功' : '连接失败')
        useUiStore().notify(this.testMessage, !result.ok)
      } catch (error) {
        this.testMessage = errorText(error, '连接失败')
        useUiStore().notify(this.testMessage, true)
      } finally {
        this.modelTesting = false
      }
    },

    /** 从 'ai_bot_appearance' 读取外观偏好，容忍损坏的 JSON */
    loadAppearance(): void {
      this.appearance = readAppearance()
    },

    setFontSize(size: FontSize): void {
      if (!FONT_SIZES.includes(size)) return
      this.appearance.fontSize = size
      persistAppearance(this.appearance)
    },

    setSendKey(key: SendKey): void {
      if (!SEND_KEYS.includes(key)) return
      this.appearance.sendKey = key
      persistAppearance(this.appearance)
    },

    /** 修改登录密码；已有会话不会被强制退出，失败向上抛出 */
    async changeMyPassword(oldPassword: string, newPassword: string): Promise<void> {
      await changePassword(oldPassword, newPassword)
    },
  },
})
