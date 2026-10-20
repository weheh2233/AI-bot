<template>
  <scroll-view class="settings-workspace" scroll-y>
    <!-- Panels are mutually exclusive and driven by ui.settingsDetail. -->
    <view v-if="ui.settingsDetail === 'overview'" class="settings-inner">
      <view class="settings-hero">
        <view class="settings-overview-heading">
          <text class="settings-eyebrow">OVERVIEW</text>
          <view class="settings-back" @click="ui.focusWorkspace('chat')">
            <text>‹ 返回聊天</text>
          </view>
        </view>
        <view class="settings-title"><text>设置总览</text></view>
        <view class="settings-text"><text>个性化你的知序体验，配置专属模型连接。</text></view>
      </view>

      <view class="settings-list">
        <view class="settings-section" @click="ui.openSettingsDetail('model')">
          <view class="settings-section-icon">
            <image class="settings-icon" src="/static/icons/settings-model.png" />
          </view>
          <view class="settings-section-copy">
            <view class="settings-section-title"><text>模型连接</text></view>
            <view class="settings-section-desc"><text>连接 OpenAI 兼容 API 服务</text></view>
          </view>
          <view class="settings-section-status"><text>{{ settings.modelStatusText }}</text></view>
          <view class="settings-arrow"><text>›</text></view>
        </view>

        <view class="settings-section" @click="ui.openSettingsDetail('password')">
          <view class="settings-section-icon">
            <image class="settings-icon" src="/static/icons/settings-password.png" />
          </view>
          <view class="settings-section-copy">
            <view class="settings-section-title"><text>账户安全</text></view>
            <view class="settings-section-desc"><text>修改登录密码</text></view>
          </view>
          <view class="settings-section-status"><text>修改密码</text></view>
          <view class="settings-arrow"><text>›</text></view>
        </view>

        <view class="settings-section" @click="ui.openSettingsDetail('appearance')">
          <view class="settings-section-icon">
            <image class="settings-icon" src="/static/icons/settings-appearance.png" />
          </view>
          <view class="settings-section-copy">
            <view class="settings-section-title"><text>界面与输入</text></view>
            <view class="settings-section-desc"><text>字体大小、发送快捷键</text></view>
          </view>
          <view class="settings-section-status"><text>{{ settings.appearanceStatusText }}</text></view>
          <view class="settings-arrow"><text>›</text></view>
        </view>

        <view class="settings-section">
          <view class="settings-section-icon">
            <text>⇄</text>
          </view>
          <view class="settings-section-copy">
            <view class="settings-section-title"><text>回答来源</text></view>
            <view class="settings-section-desc">
              <text>{{ settings.mockMode ? '本地 Mock，不调用真实模型' : '调用真实模型服务' }}</text>
            </view>
          </view>
          <view class="settings-section-status">
            <text>{{ settings.mockMode ? 'Mock 离线模拟' : '真实模型' }}</text>
          </view>
          <switch
            :checked="settings.mockMode"
            color="#257d6a"
            style="transform: scale(0.75);"
            @change="onMockModeChange"
          />
        </view>

        <view class="settings-section" @click="onClearCache">
          <view class="settings-section-icon">
            <text>⌫</text>
          </view>
          <view class="settings-section-copy">
            <view class="settings-section-title"><text>清除缓存</text></view>
            <view class="settings-section-desc"><text>清理本地设置与图片预览临时文件</text></view>
          </view>
          <view class="settings-section-status"><text>会退出登录</text></view>
          <view class="settings-arrow"><text>›</text></view>
        </view>
      </view>
    </view>

    <view v-else-if="ui.settingsDetail === 'model'" class="settings-detail">
      <view class="settings-back" @click="ui.backToSettingsOverview()">
        <text>‹ 返回个人设置</text>
      </view>

      <view class="settings-detail-head">
        <text class="settings-eyebrow">模型连接</text>
        <view class="settings-detail-title"><text>使用你自己的模型服务</text></view>
        <view class="settings-detail-text">
          <text>填写一组 OpenAI 兼容服务配置。未保存个人配置时，聊天使用服务器默认模型。</text>
        </view>
      </view>

      <view class="settings-card">
        <view class="settings-card-title"><text>个人模型配置</text></view>
        <view class="settings-card-desc">
          <text>Key 会加密保存在服务端，页面不会回显已保存的 Key。</text>
        </view>

        <view v-if="storageBlocked" class="settings-notice">
          <text>服务端没有配置加密密钥，暂时无法保存个人模型配置，请联系管理员。</text>
        </view>

        <view class="settings-fields">
          <view class="settings-field">
            <text>公网 HTTPS Base URL</text>
            <input
              v-model="baseUrl"
              class="settings-field-input"
              type="text"
              :maxlength="512"
              placeholder="https://api.example.com/v1"
            />
            <view class="settings-field-help">
              <text>只支持公网 HTTPS 地址，不支持本机或内网地址。</text>
            </view>
          </view>

          <view class="settings-field">
            <text>API Key</text>
            <input
              v-model="apiKey"
              class="settings-field-input"
              password
              :maxlength="4096"
              placeholder="已保存 · 不回显"
            />
            <view class="settings-field-help">
              <text>修改 Base URL 后必须重新填写 Key。</text>
            </view>
          </view>

          <view class="settings-field">
            <text>模型名</text>
            <input
              v-model="modelName"
              class="settings-field-input"
              type="text"
              :maxlength="200"
              placeholder="按服务商提供的原始名称填写"
            />
            <view class="settings-field-help">
              <text>服务器默认：{{ defaultModelName }}</text>
            </view>
          </view>
        </view>

        <view class="settings-meta">
          <view>
            <text>更新时间：</text>
            <text class="settings-meta-value">{{ updatedAtText }}</text>
          </view>
          <view>
            <text>最后使用：</text>
            <text class="settings-meta-value">{{ lastUsedAtText }}</text>
          </view>
        </view>

        <view class="settings-actions">
          <view class="settings-quiet settings-action-button" @click="onTestModel">
            <text>测试连接</text>
          </view>
          <view class="settings-primary settings-action-button" @click="onSaveModel">
            <text>保存配置</text>
          </view>
          <view class="settings-danger settings-action-button" @click="onDeleteModel">
            <text>删除个人 Key并恢复默认</text>
          </view>
        </view>

        <view v-if="settings.testMessage" class="settings-notice">
          <text>{{ settings.testMessage }}</text>
        </view>
        <view class="settings-notice">
          <text>测试连接只发送一条固定短消息，可能产生少量服务商费用；不会携带当前会话内容。</text>
        </view>
      </view>
    </view>

    <view v-else-if="ui.settingsDetail === 'password'" class="settings-detail">
      <view class="settings-back" @click="ui.backToSettingsOverview()">
        <text>‹ 返回个人设置</text>
      </view>

      <view class="settings-detail-head">
        <text class="settings-eyebrow">账户安全</text>
        <view class="settings-detail-title"><text>修改密码</text></view>
        <view class="settings-detail-text">
          <text>修改后，下次登录请使用新密码；当前已经登录的页面不会被强制退出。</text>
        </view>
      </view>

      <view class="settings-card">
        <view class="settings-card-title"><text>更新登录密码</text></view>
        <view class="settings-fields">
          <view class="settings-field">
            <text>原密码</text>
            <input
              v-model="oldPassword"
              class="settings-field-input"
              password
              :maxlength="128"
            />
          </view>

          <view class="settings-field">
            <text>新密码</text>
            <input
              v-model="newPassword"
              class="settings-field-input"
              password
              :maxlength="128"
            />
            <view class="settings-field-help">
              <text>至少 6 个字符；服务端还会校验 bcrypt 的字节长度上限。</text>
            </view>
          </view>

          <view class="settings-field">
            <text>确认新密码</text>
            <input
              v-model="confirmPassword"
              class="settings-field-input"
              password
              :maxlength="128"
            />
          </view>
        </view>

        <view class="settings-actions">
          <view class="settings-primary settings-action-button" @click="onChangePassword">
            <text>更新密码</text>
          </view>
        </view>
      </view>
    </view>

    <view v-else-if="ui.settingsDetail === 'appearance'" class="settings-detail">
      <view class="settings-back" @click="ui.backToSettingsOverview()">
        <text>‹ 返回个人设置</text>
      </view>

      <view class="settings-detail-head">
        <text class="settings-eyebrow">界面与输入</text>
        <view class="settings-detail-title"><text>调整阅读和发送方式</text></view>
        <view class="settings-detail-text">
          <text>这些偏好只保存在当前浏览器，不会同步到其他设备，也不会影响模型连接。</text>
        </view>
      </view>

      <view class="settings-card">
        <view class="settings-card-title"><text>显示与输入</text></view>

        <view class="settings-choice-group">
          <text class="settings-choice-label">字体大小</text>
          <view class="settings-choice-row">
            <view
              class="settings-choice"
              :class="{ 'is-active': settings.appearance.fontSize === 'small' }"
              @click="settings.setFontSize('small')"
            >
              <view class="settings-choice-dot" />
              <text>小</text>
            </view>
            <view
              class="settings-choice"
              :class="{ 'is-active': settings.appearance.fontSize === 'standard' }"
              @click="settings.setFontSize('standard')"
            >
              <view class="settings-choice-dot" />
              <text>标准</text>
            </view>
            <view
              class="settings-choice"
              :class="{ 'is-active': settings.appearance.fontSize === 'large' }"
              @click="settings.setFontSize('large')"
            >
              <view class="settings-choice-dot" />
              <text>大</text>
            </view>
          </view>
        </view>

        <view class="settings-choice-group">
          <text class="settings-choice-label">发送快捷键</text>
          <view class="settings-choice-row">
            <view
              class="settings-choice"
              :class="{ 'is-active': settings.appearance.sendKey === 'enter' }"
              @click="settings.setSendKey('enter')"
            >
              <view class="settings-choice-dot" />
              <text>Enter 发送</text>
            </view>
            <view
              class="settings-choice"
              :class="{ 'is-active': settings.appearance.sendKey === 'ctrl-enter' }"
              @click="settings.setSendKey('ctrl-enter')"
            >
              <view class="settings-choice-dot" />
              <text>Ctrl + Enter 发送</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { ModelConfigInput } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useDocsStore } from '@/stores/docs'
import { usePersonaStore } from '@/stores/persona'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { clearAppCache } from '@/utils/cache'

/** 密码长度上限：后端按 bcrypt 限制为 72 个 UTF-8 字节 */
const MAX_PASSWORD_BYTES = 72

const ui = useUiStore()
const auth = useAuthStore()
const chat = useChatStore()
const docs = useDocsStore()
const persona = usePersonaStore()
const settings = useSettingsStore()

/** 模型连接表单 */
const baseUrl = ref('')
const apiKey = ref('')
const modelName = ref('')

/** 修改密码表单 */
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPassword = ref(false)

/** 服务端没配加密密钥时禁止保存（configured 之外唯一的硬性阻断） */
const storageBlocked = computed(() => settings.model?.storage_ready === false)

const defaultModelName = computed(() => settings.model?.default_model_name || '读取中')

const updatedAtText = computed(() => formatSettingsTime(settings.model?.updated_at) || '未配置')

const lastUsedAtText = computed(() => formatSettingsTime(settings.model?.last_used_at) || '未使用')

/** ISO 时间 -> 'YYYY-MM-DD HH:mm'（本地时区）；无法解析时返回空串 */
function formatSettingsTime(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 后端 message 已经是中文提示，直接展示；否则给兜底文案 */
function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : '操作失败，请稍后重试'
}

/** 按 UTF-8 统计字节数；小程序端没有 TextEncoder 时手工计数 */
function utf8ByteLength(value: string): number {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(value).length
  }
  let bytes = 0
  for (const char of value) {
    const code = char.codePointAt(0) || 0
    if (code <= 0x7f) bytes += 1
    else if (code <= 0x7ff) bytes += 2
    else if (code <= 0xffff) bytes += 3
    else bytes += 4
  }
  return bytes
}

/** uni.showModal 包成 Promise；取消或失败都返回 false */
function confirmAction(title: string, content: string, confirmText = '继续'): Promise<boolean> {
  return new Promise((resolve) => {
    uni.showModal({
      title,
      content,
      confirmText,
      cancelText: '取消',
      success: (res) => resolve(Boolean(res.confirm)),
      fail: () => resolve(false),
    })
  })
}

/** 切换回答来源；切换后立即对下一条消息生效 */
function onMockModeChange(event: { detail: { value: boolean } }) {
  const enabled = Boolean(event?.detail?.value)
  settings.setMockMode(enabled)
  ui.notify(enabled ? '已切换到 Mock 离线模拟' : '已切换到真实模型')
}

/** 清除本地缓存与预览临时文件；顺便按既有退出登录流程重置内存状态 */
async function onClearCache() {
  const confirmed = await confirmAction(
    '清除缓存',
    '将清除本地设置缓存和图片预览临时文件，并退出登录。服务端的聊天记录与长期记忆不会被删除。',
    '清除',
  )
  if (!confirmed) return
  try {
    await clearAppCache()
    // 与 401 / 主动退出登录保持同一套内存清理逻辑
    auth.clearSession()
    chat.resetUserWorkspace()
    docs.reset()
    persona.reset()
    settings.reset()
    ui.focusWorkspace('chat')
    ui.notify('缓存已清除，请重新登录')
  } catch {
    ui.notify('清除失败，请重试', true)
  }
}

/** 组装 PUT/POST 的入参：Key 为空时省略，后端才会沿用已保存的 Key */
function buildModelInput(): ModelConfigInput {
  const input: ModelConfigInput = {
    base_url: baseUrl.value.trim(),
    model_name: modelName.value.trim(),
  }
  const key = apiKey.value.trim()
  if (key) input.api_key = key
  return input
}

/** 用服务端状态回填表单；Key 永远不回显，提交成功后清空输入框 */
function applyStatusToForm() {
  const model = settings.model
  if (!model) return
  baseUrl.value = model.base_url || ''
  modelName.value = model.model_name || ''
  apiKey.value = ''
}

async function refreshModelPanel() {
  await settings.loadModel()
  applyStatusToForm()
}

async function onTestModel() {
  if (settings.modelTesting) return
  await settings.testModel(buildModelInput())
}

async function onSaveModel() {
  if (settings.modelSaving) return
  if (storageBlocked.value) {
    ui.notify('服务端没有配置加密密钥，暂时无法保存个人模型配置', true)
    return
  }
  try {
    await settings.saveModel(buildModelInput())
    applyStatusToForm()
    ui.notify('模型配置已保存')
  } catch (error) {
    ui.notify(errorMessage(error), true)
  }
}

async function onDeleteModel() {
  if (settings.modelSaving) return
  const confirmed = await confirmAction(
    '删除个人配置',
    '删除个人 Key 后，聊天将恢复使用服务器默认配置。继续吗？',
  )
  if (!confirmed) return
  try {
    await settings.deleteModel()
    applyStatusToForm()
    ui.notify('个人配置已删除，已恢复默认')
  } catch (error) {
    ui.notify(errorMessage(error), true)
  }
}

async function onChangePassword() {
  if (changingPassword.value) return
  const old = oldPassword.value
  const next = newPassword.value

  if (!old) {
    ui.notify('请输入原密码', true)
    return
  }
  if (next !== confirmPassword.value) {
    ui.notify('两次输入的新密码不一致', true)
    return
  }
  if (next.length < 6) {
    ui.notify('新密码至少 6 个字符', true)
    return
  }
  if (utf8ByteLength(next) > MAX_PASSWORD_BYTES) {
    ui.notify('新密码最多 72 个 UTF-8 字节（中文通常占 3 字节）', true)
    return
  }

  changingPassword.value = true
  try {
    await settings.changeMyPassword(old, next)
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    ui.notify('密码已修改')
  } catch (error) {
    ui.notify(errorMessage(error), true)
  } finally {
    changingPassword.value = false
  }
}

onMounted(() => {
  settings.loadAppearance()
  if (auth.loggedIn) void settings.loadModel()
})

// 原站进入模型详情时才拉取配置，这里保持一致；进入外观页时重新读取本地偏好
watch(
  () => ui.settingsDetail,
  (detail) => {
    if (detail === 'model' && auth.loggedIn) void refreshModelPanel()
    if (detail === 'appearance') settings.loadAppearance()
  },
)
</script>
