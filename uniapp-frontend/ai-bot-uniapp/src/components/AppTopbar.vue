<template>
  <view class="topbar">
    <view class="topbar-heading">
      <view class="topbar-title-row">
        <view class="topbar-title"><text>{{ workspaceTitle }}</text></view>

        <view
          v-if="canEdit && !editing"
          class="icon-button thread-title-action"
          @click="beginEdit"
        >
          <text>✎</text>
        </view>

        <view v-if="editing" class="thread-title-edit">
          <input
            ref="titleInput"
            v-model="draft"
            class="thread-title-input"
            type="text"
            :maxlength="255"
            confirm-type="done"
            aria-label="会话标题"
            @confirm="save"
          />
          <view
            class="icon-button thread-title-action thread-title-save"
            :class="{ 'is-disabled': saving }"
            @click="save"
          >
            <text>✓</text>
          </view>
          <view class="icon-button thread-title-action" @click="cancel">
            <text>×</text>
          </view>
        </view>
      </view>
      <view class="topbar-meta"><text>{{ metaText }}</text></view>
    </view>

    <view class="topbar-actions">
      <view
        v-if="showExport"
        class="icon-button topbar-export"
        title="导出 Markdown"
        @click="exportMarkdown"
      >
        <text>↓</text>
      </view>
      <view
        v-if="showExport"
        class="icon-button topbar-export"
        title="导出会话图片"
        @click="exportImage"
      >
        <text>▧</text>
      </view>
      <!-- 移动端顶栏放不下两个导出按钮，合并成一个菜单（桌面端隐藏） -->
      <view v-if="showExport" class="icon-button topbar-more" title="导出会话" @click="openExportMenu">
        <text>⋯</text>
      </view>
      <view v-if="ui.view === 'chat'" class="quiet-button topbar-new" @click="onNewChat">
        <text class="topbar-new-text">新建会话</text>
        <text class="topbar-new-icon">+</text>
      </view>
      <!-- 移动端左栏变成 tab 栏，账号与退出登录挪到这里（桌面端隐藏） -->
      <view v-if="auth.loggedIn" class="topbar-user" :title="auth.username">
        <text>{{ auth.avatarChar }}</text>
      </view>
      <view
        v-if="auth.loggedIn"
        class="icon-button topbar-logout"
        title="退出登录"
        @click="onLogout"
      >
        <text>⏻</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useDocsStore } from '@/stores/docs'
import { usePersonaStore } from '@/stores/persona'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const chat = useChatStore()
const docs = useDocsStore()
const persona = usePersonaStore()
const settings = useSettingsStore()
const ui = useUiStore()

const editing = ref(false)
const saving = ref(false)
const draft = ref('')
const titleInput = ref<{ $el?: HTMLElement } | null>(null)

const workspaceTitle = computed(() => {
  if (ui.view === 'docs') return '我的资料'
  if (ui.view === 'history') return '历史会话'
  if (ui.view === 'personas') return '角色设定'
  if (ui.view === 'settings') return '个人设置'
  return chat.conversationTitle || '学习对话'
})

const metaText = computed(() => {
  if (ui.view === 'docs') return '管理资料 · 上传后可在聊天中检索'
  if (ui.view === 'history') return '选择一条记录继续对话'
  if (ui.view === 'personas') return '创建并管理对话角色'
  if (ui.view === 'settings') return '账户与模型连接'
  return `当前会话 · ${chat.threadId.slice(0, 18)}`
})

/** 只有「对话」工作区且已有标题时才允许改名 */
const canEdit = computed(() => ui.view === 'chat' && Boolean(chat.conversationTitle))

/** 有消息时才能导出，与原站一致 */
const showExport = computed(() => ui.view === 'chat' && chat.messages.length > 0)

function beginEdit() {
  if (!chat.conversationTitle || ui.view !== 'chat') return
  draft.value = chat.conversationTitle
  editing.value = true
  void nextTick(() => {
    const root = titleInput.value?.$el
    const el = root?.querySelector?.('input') as HTMLInputElement | null | undefined
    el?.focus()
    el?.select()
  })
}

function cancel() {
  editing.value = false
}

async function save() {
  const title = draft.value.trim()
  if (!title) {
    ui.notify('会话标题不能为空', true)
    return
  }
  if (!chat.conversationTitle || title === chat.conversationTitle) {
    cancel()
    return
  }
  saving.value = true
  try {
    await chat.saveConversationTitle(title)
    editing.value = false
    ui.notify('会话标题已更新')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '标题更新失败', true)
  } finally {
    saving.value = false
  }
}

function onNewChat() {
  // 流式生成中新建会话会把当前回复丢掉，先拦住
  if (chat.busy) {
    ui.notify('正在生成回复，请先停止或等待完成', true)
    return
  }
  chat.resetConversation()
  ui.focusWorkspace('chat')
}

function onLogout() {
  auth.clearSession()
  chat.resetUserWorkspace()
  docs.reset()
  persona.reset()
  settings.reset()
  ui.focusWorkspace('chat')
  ui.notify('已退出登录')
}

/* ---------------- 导出 ---------------- */

function buildMarkdown(): string {
  const lines: string[] = [`# ${chat.conversationTitle || '学习对话'}`, '']
  for (const message of chat.messages) {
    lines.push(message.role === 'user' ? '## 你' : '## 知序')
    lines.push('')
    lines.push(message.content)
    lines.push('')
  }
  return lines.join('\n')
}

function exportMarkdown() {
  const content = buildMarkdown()
  const fileName = `${(chat.conversationTitle || '学习对话').replace(/[\\/:*?"<>|]/g, '_')}.md`

  // #ifdef H5
  try {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = fileName
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    ui.notify('已导出 Markdown')
  } catch {
    ui.notify('导出失败，请重试', true)
  }
  // #endif

  // #ifdef MP-WEIXIN
  // 小程序：写入用户目录后用 shareFileMessage 发到聊天（可转发给“文件传输助手”），失败再退回剪贴板
  try {
    const wxApi = (globalThis as unknown as { wx?: any }).wx
    const filePath = `${wxApi.env.USER_DATA_PATH}/${fileName}`
    wxApi.getFileSystemManager().writeFileSync(filePath, content, 'utf8')
    wxApi.shareFileMessage({
      filePath,
      fileName,
      success: () => ui.notify('已导出 Markdown'),
      fail: (error: { errMsg?: string }) => {
        if (String(error?.errMsg || '').includes('cancel')) return
        copyMarkdown(content)
      },
    })
  } catch {
    copyMarkdown(content)
  }
  // #endif

  // #ifdef APP-PLUS
  // App：没有通用的「另存为」，复制到剪贴板最可靠
  copyMarkdown(content)
  // #endif
}

function copyMarkdown(content: string) {
  uni.setClipboardData({
    data: content,
    success: () => ui.notify('已复制会话 Markdown 到剪贴板'),
    fail: () => ui.notify('当前平台暂不支持导出 Markdown', true),
  })
}

function openExportMenu() {
  uni.showActionSheet({
    itemList: ['导出 Markdown', '导出会话图片'],
    success: (res) => {
      if (res.tapIndex === 0) exportMarkdown()
      else if (res.tapIndex === 1) exportImage()
    },
  })
}

function exportImage() {
  // 导出整段对话为图片需要 canvas 逐块绘制（头像、气泡、Markdown、代码块），
  // H5 与小程序要分别实现，这一版先明确告知而不是给半成品。
  ui.notify('会话图片导出尚未在这次移植中实现，可先导出 Markdown', true)
}

defineExpose({ cancelEdit: cancel })
</script>
