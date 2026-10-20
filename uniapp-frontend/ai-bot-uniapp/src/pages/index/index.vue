<template>
  <view
    class="app-shell"
    :class="{
      'modal-open': ui.approvalVisible,
      'settings-mode': ui.settingsMode,
      'font-small': settings.appearance.fontSize === 'small',
      'font-large': settings.appearance.fontSize === 'large',
    }"
    :style="pageStyle"
  >
    <AppRail />

    <view class="main" :class="{ 'settings-active': ui.settingsMode }">
      <AppTopbar />

      <view class="chat-view" :class="{ hidden: ui.view !== 'chat' }">
        <view class="chat-column">
          <!-- 本会话角色 -->
          <view class="chat-persona-bar">
            <text>本会话角色</text>
            <picker
              class="persona-picker"
              mode="selector"
              :range="personaLabels"
              :value="personaIndex"
              @change="onPersonaChange"
            >
              <view class="persona-picker-select">
                <text>{{ pickerLabel }}</text>
              </view>
            </picker>
            <text class="chat-persona-current">{{ currentPersonaName }}</text>
            <view
              v-if="persona.canApplyLatest"
              class="chat-persona-latest"
              @click="applyLatestPersona"
            >
              <text>应用角色最新版</text>
            </view>
          </view>

          <scroll-view
            class="messages"
            scroll-y
            :scroll-top="scrollTop"
            :scroll-with-animation="false"
          >
            <view class="messages-inner">
              <WelcomePanel v-if="chat.welcomeMode" :mode="chat.welcomeMode" @pick="onSuggestion" />

              <MessageItem
                v-for="(message, index) in chat.messages"
                :key="message.id"
                :message="message"
                :user-initial="auth.avatarChar"
                :is-last="index === chat.messages.length - 1"
              />
            </view>
          </scroll-view>

          <view class="composer-wrap">
            <view class="composer">
              <!-- 待发送图片预览 -->
              <view v-if="pendingImages.length" class="composer-images">
                <view
                  v-for="(url, index) in pendingImages"
                  :key="index"
                  class="composer-image-item"
                >
                  <image
                    class="composer-image"
                    :src="url"
                    mode="aspectFill"
                    @click="previewPending(url)"
                  />
                  <view class="composer-image-remove" @click="removePending(index)">
                    <text>×</text>
                  </view>
                </view>
              </view>

              <textarea
                v-if="showComposer"
                ref="composerRef"
                v-model="draft"
                class="composer-input"
                :disabled="chat.busy"
                placeholder="输入问题……"
                :maxlength="-1"
                :auto-height="false"
                :adjust-position="false"
                @confirm="onSend"
              />
              <view class="composer-footer">
                <view
                  class="attach-button"
                  :class="{ 'is-disabled': chat.busy || pickingImages }"
                  @click="pickImages"
                >
                  <text>{{ pickingImages ? '…' : '📎' }}</text>
                </view>
                <text class="composer-hint">Enter 发送 · Shift + Enter 换行</text>

                <view v-if="chat.canControlTurn" class="stream-controls">
                  <view class="stream-control" @click="chat.togglePause()">
                    <text>{{ chat.isPaused ? '继续' : '暂停' }}</text>
                  </view>
                  <view class="stream-control cancel" @click="chat.cancelTurn()">
                    <text>停止</text>
                  </view>
                </view>

                <view class="send-button" :class="{ 'is-disabled': chat.busy }" @click="onSend">
                  <image class="send-button-icon" src="/static/icons/send.png" mode="aspectFit" />
                </view>
              </view>
            </view>
          </view>
        </view>

        <ChatHistoryPanel />
      </view>

      <DocumentsView :class="{ hidden: ui.view !== 'docs' }" />
      <HistoryView :class="{ hidden: ui.view !== 'history' }" />
      <PersonaView :class="{ hidden: ui.view !== 'personas' }" />
      <SettingsView :class="{ hidden: ui.view !== 'settings' }" />
    </view>

    <AuthScreen />
    <ApprovalModal />
    <CodeDialog />
    <NoticeToast />
  </view>

  <!-- 隐藏 canvas 用于图片压缩 -->
  <!-- 图片压缩用隐藏 canvas：微信小程序用新版 2D，其他平台用旧版 -->
  <!-- #ifdef MP-WEIXIN -->
  <canvas id="image-compress-canvas" type="2d"
          style="width:640px;height:640px;position:fixed;left:-9999px;top:0;" />
  <!-- #endif -->
  <!-- #ifndef MP-WEIXIN -->
  <canvas canvas-id="image-compress-canvas"
          style="width:1280px;height:1280px;position:fixed;left:-9999px;top:0;" />
  <!-- #endif -->

</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppRail from '@/components/AppRail.vue'
import AppTopbar from '@/components/AppTopbar.vue'
import ApprovalModal from '@/components/ApprovalModal.vue'
import AuthScreen from '@/components/AuthScreen.vue'
import ChatHistoryPanel from '@/components/ChatHistoryPanel.vue'
import CodeDialog from '@/components/CodeDialog.vue'
import DocumentsView from '@/components/DocumentsView.vue'
import HistoryView from '@/components/HistoryView.vue'
import MessageItem from '@/components/MessageItem.vue'
import NoticeToast from '@/components/NoticeToast.vue'
import PersonaView from '@/components/PersonaView.vue'
import SettingsView from '@/components/SettingsView.vue'
import WelcomePanel from '@/components/WelcomePanel.vue'
import { compressImages } from '@/utils/image-compress'
import { previewImages } from '@/utils/image-preview'
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

const draft = ref('')
const composerRef = ref<{ $el?: HTMLElement } | null>(null)
/** App / 小程序的状态栏高度（H5 为 0），避免自定义导航栏被状态栏遮挡 */
const statusBarHeight = ref(0)
/** 小程序右上角胶囊按钮占用的宽度（px），H5 为 0 */
const capsuleSpace = ref(0)
/** 键盘高度（px）；>0 时把整页底部垫高，输入区不会被键盘挡住 */
const keyboardHeight = ref(0)
let keyboardHandler: ((res: { height: number }) => void) | null = null

/**
 * 小程序的原生 textarea 会盖在弹窗/登录浮层之上，因此这些状态下要卸载它；
 * H5 的 textarea 是普通 DOM，保持挂载，避免重新挂载后键盘监听失效。
 */
let hideComposerForModal = false
// #ifdef MP-WEIXIN
hideComposerForModal = true
// #endif

const showComposer = computed(() =>
  hideComposerForModal
    ? auth.loggedIn && !ui.approvalVisible && !ui.codeDialogVisible
    : true,
)

/** 页面根节点样式：状态栏避让、键盘避让、胶囊避让（CSS 变量传给 .topbar） */
const pageStyle = computed<Record<string, string>>(() => {
  const style: Record<string, string> = {
    paddingTop: `${statusBarHeight.value}px`,
    '--capsule-space': `${capsuleSpace.value}px`,
    // 字号档位：CSS 变量会穿过小程序自定义组件边界继承下去，类名后代选择器不会
    '--font-scale': String(settings.fontScale),
  }
  if (keyboardHeight.value > 0) style.paddingBottom = `${keyboardHeight.value}px`
  return style
})

/* ---------- 本会话角色 ---------- */

const personaLabels = computed(() => {
  if (!persona.list.length) return ['默认角色']
  return persona.list.map((item) => item.name)
})

const personaIndex = computed(() => {
  const index = persona.list.findIndex((item) => item.id !== null && item.id === chat.personaId)
  return index < 0 ? 0 : index
})

const currentPersonaName = computed(() => persona.conversationPersona?.name || '')

/**
 * 下拉框展示的文案：
 * 有匹配角色时显示角色名；personaId 为空（默认角色）时显示会话快照名，
 * 不要盲目退回列表第一项，否则会和右侧“本会话角色”对不上。
 */
const pickerLabel = computed(() => {
  const index = persona.list.findIndex((item) => item.id !== null && item.id === chat.personaId)
  if (index >= 0) return persona.list[index].name
  return currentPersonaName.value || '默认角色'
})

async function onPersonaChange(event: { detail: { value: number | string } }) {
  const index = Number(event.detail.value) || 0
  const target = persona.list[index]
  if (!target || target.id === null) return

  // 新会话还没有 conversations 行，PATCH 会 404；此时只记住选择，发第一条消息时带上
  if (!chat.messages.length) {
    chat.personaId = target.id
    persona.conversationPersona = target
    ui.notify('角色将在发出第一条消息后生效')
    return
  }

  try {
    await persona.applyToConversation(chat.threadId, target.id)
    chat.personaId = target.id
    ui.notify(`已切换到「${target.name}」`)
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '角色切换失败', true)
  }
}

async function applyLatestPersona() {
  if (chat.personaId === null) return
  try {
    await persona.applyLatest(chat.threadId)
    ui.notify('已应用角色最新版')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '应用失败', true)
  }
}

/* ---------- 滚动到底部 ---------- */

const scrollTop = ref(0)
let scrollTick = 0

function scrollToEnd() {
  scrollTick += 1
  scrollTop.value = 1_000_000 + scrollTick
}

watch(
  () => `${chat.messages.length}:${chat.lastAssistant?.content.length ?? 0}`,
  () => scrollToEnd(),
)

/* ---------- H5：Enter 发送 / Shift + Enter 换行（可在设置里切成 Ctrl+Enter） ---------- */

function h5Textarea(): HTMLTextAreaElement | null {
  const root = composerRef.value?.$el
  const el = root?.querySelector?.('textarea')
  return (el as HTMLTextAreaElement | null | undefined) ?? null
}

function focusComposer() {
  h5Textarea()?.focus()
}

// #ifdef H5
onMounted(() => {
  const el = h5Textarea()
  if (!el) return
  el.addEventListener('keydown', (event: KeyboardEvent) => {
    if (event.key !== 'Enter') return
    const ctrlOrMeta = event.ctrlKey || event.metaKey
    const sendKey = settings.appearance.sendKey
    const shouldSend = sendKey === 'ctrl-enter' ? ctrlOrMeta : !event.shiftKey && !ctrlOrMeta
    if (!shouldSend) return
    event.preventDefault()
    onSend()
  })
})
// #endif

/* ---------- 图片 ---------- */

/** 与后端 MAX_IMAGES_PER_REQUEST 的默认值保持一致 */
const MAX_IMAGES = 5
const pendingImages = ref<string[]>([])
const pickingImages = ref(false)

function previewPending(url: string) {
  void previewImages(pendingImages.value, url)
}

function removePending(index: number) {
  pendingImages.value.splice(index, 1)
}

async function pickImages() {
  if (chat.busy || pickingImages.value) return

  const remaining = MAX_IMAGES - pendingImages.value.length
  if (remaining <= 0) {
    ui.notify(`一次最多发送 ${MAX_IMAGES} 张图片`, true)
    return
  }

  type ChosenImages = { tempFilePaths?: string[]; tempFiles?: unknown[] }
  let result: ChosenImages | undefined
  try {
    result = await new Promise<ChosenImages>((resolve, reject) => {
      uni.chooseImage({
        count: remaining,
        sizeType: ['compressed'],
        sourceType: ['album', 'camera'],
        success: (res) => resolve(res as unknown as ChosenImages),
        fail: reject,
      })
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('cancel')) ui.notify('选择图片失败', true)
    return
  }

  const paths = result?.tempFilePaths || []
  if (!result || !paths.length) return

  // H5 的 tempFiles 是原始 File，压缩工具会走 FileReader + canvas 分支
  let sources: Array<string | File> = paths
  // #ifdef H5
  sources = (result.tempFiles as File[]) || []
  // #endif

  pickingImages.value = true
  try {
    const compressed = await compressImages(sources)
    pendingImages.value = [...pendingImages.value, ...compressed].slice(0, MAX_IMAGES)
  } catch {
    ui.notify('图片处理失败，请重试', true)
  } finally {
    pickingImages.value = false
  }
}

/* ---------- 发送 ---------- */

function onSend() {
  if (chat.busy) return
  const text = draft.value
  const images = pendingImages.value
  if (!text.trim() && !images.length) return
  draft.value = ''
  pendingImages.value = []
  void chat.sendMessage(text, { images }).finally(() => {
    scrollToEnd()
    if (!chat.awaitingApproval) focusComposer()
  })
}

function onSuggestion(text: string) {
  draft.value = text
  onSend()
}

/* ---------- 数据加载：跟随工作区与登录态 ---------- */

watch(
  () => [ui.view, auth.loggedIn] as const,
  ([view, loggedIn]) => {
    if (!loggedIn) return
    if (view === 'docs') {
      void docs.load().catch((error: unknown) => {
        ui.notify(error instanceof Error ? error.message : '资料读取失败', true)
      })
    } else if (view === 'history') {
      void chat.loadHistoryTitles(50)
    } else if (view === 'personas') {
      void persona.load()
    } else if (view === 'settings') {
      settings.loadAppearance()
      void settings.loadModel()
    } else {
      void chat.loadHistoryTitles()
      void persona.load()
      void persona.loadConversationPersona(chat.threadId).then(() => {
        chat.personaId = persona.conversationPersona?.id ?? null
      })
      void chat.syncConversationTitle()
    }
  },
  { immediate: true },
)

onMounted(() => {
  const info = uni.getSystemInfoSync()
  statusBarHeight.value = info.statusBarHeight || 0

  // #ifdef MP-WEIXIN
  // 自定义导航：胶囊按钮固定在右上角，顶栏右侧操作必须让开它
  const menu = (
    uni as unknown as {
      getMenuButtonBoundingClientRect?: () => { left: number }
    }
  ).getMenuButtonBoundingClientRect?.()
  if (menu) capsuleSpace.value = Math.max(0, info.windowWidth - menu.left + 8)
  // #endif

  // 键盘弹起时把页面底部垫高，配合 textarea 的 adjust-position=false
  if (typeof uni.onKeyboardHeightChange === 'function') {
    keyboardHandler = (res) => {
      keyboardHeight.value = res.height || 0
    }
    uni.onKeyboardHeightChange(keyboardHandler)
  }

  settings.loadAppearance()
})

onUnmounted(() => {
  if (keyboardHandler && typeof uni.offKeyboardHeightChange === 'function') {
    uni.offKeyboardHeightChange(keyboardHandler)
  }
})
</script>
