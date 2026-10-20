<template>
  <view class="message" :class="[message.role, { error: message.error }]">
    <view class="avatar">
      <text v-if="message.role === 'user'">{{ userInitial }}</text>
      <image v-else class="avatar-img" src="/static/ai-avatar.jpg" mode="aspectFill" alt="知序" />
    </view>

    <view class="bubble-wrap">
      <view class="message-label">
        <text>{{ message.role === 'user' ? '你' : '知序' }}</text>
      </view>

      <view v-if="elapsedText" class="elapsed-time"><text>{{ elapsedText }}</text></view>

      <!-- 用户发送的图片：点击全屏预览 -->
      <view
        v-if="message.images?.length"
        class="message-images"
        :class="{ 'is-user': message.role === 'user' }"
      >
        <image
          v-for="(url, index) in message.images"
          :key="index"
          class="message-image"
          :src="url"
          mode="aspectFill"
          @click="previewImage(url)"
        />
      </view>

      <!-- H5：与原站一致，把 Markdown 生成的 HTML 注入气泡，链接可点击 -->
      <!-- #ifdef H5 -->
      <view
        v-if="hasText"
        ref="bubbleRef"
        class="bubble"
        :class="bubbleClass"
        v-html="htmlContent"
      />
      <!-- #endif -->

      <!-- 小程序 / App：rich-text 不认外部 CSS 类，样式内联在节点上 -->
      <!-- #ifndef H5 -->
      <view v-if="hasText" class="bubble" :class="bubbleClass">
        <!-- 流式中 / 用户 / 错误消息按纯文本渲染 -->
        <rich-text v-if="isPlain" :nodes="plainNodes" />
        <!-- 正常回复：代码块单独拆出来，容器上才能绑定复制 / 全屏 -->
        <template v-else>
          <template v-for="(segment, index) in segments" :key="index">
            <rich-text
              v-if="segment.type === 'markdown'"
              class="md-segment"
              :nodes="renderMarkdownNodes(segment.content, fontScale)"
            />
            <view v-else class="md-code-block">
              <view class="md-code-head">
                <text class="md-code-lang">{{ segment.lang || 'code' }}</text>
                <view class="md-code-actions">
                  <view class="md-code-tool" @click="copyCode(segment.content)">
                    <text>复制</text>
                  </view>
                  <view class="md-code-tool" @click="openCode(segment)">
                    <text>全屏</text>
                  </view>
                </view>
              </view>
              <scroll-view class="md-code-scroll" scroll-x>
                <text class="md-code-text">{{ segment.content }}</text>
              </scroll-view>
            </view>
          </template>
        </template>
      </view>
      <!-- #endif -->

      <view v-if="message.mock" class="mock-badge"><text>离线演示回答</text></view>

      <view v-if="timeText" class="message-time time-hover" :data-full-time="fullTimeText">
        <text>{{ timeText }}</text>
      </view>

      <view v-if="showActions" class="message-actions">
        <view class="message-action" @click="copyContent"><text>复制</text></view>
        <view v-if="isLast && message.role === 'assistant'" class="message-action" @click="regenerate">
          <text>重新生成</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import type { UiMessage } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import {
  formatElapsed,
  formatFullMessageTime,
  formatMessageTime,
  plainTextToRichText,
} from '@/utils/format'
import { previewImages } from '@/utils/image-preview'
import {
  renderMarkdownHtml,
  renderMarkdownNodes,
  splitMarkdownSegments,
} from '@/utils/markdown'
import type { MarkdownSegment } from '@/utils/markdown'

const props = defineProps<{
  message: UiMessage
  userInitial: string
  /** 是否是最后一条助手消息（只有它能「重新生成」） */
  isLast?: boolean
}>()

const chat = useChatStore()
const settings = useSettingsStore()
const ui = useUiStore()
const bubbleRef = ref<{ $el?: HTMLElement } | null>(null)

/** 字号档位：rich-text 不继承外部 CSS，倍数要注入到内联样式里（H5 由 --font-scale 负责） */
const fontScale = computed(() => settings.fontScale)

/**
 * 渲染策略与原站一致：
 * - 用户消息、以及「流式输出中」和出错时的助手消息都按纯文本渲染；
 * - 助手消息结束后渲染 Markdown。
 */
const isPlain = computed(
  () =>
    props.message.role === 'user' ||
    Boolean(props.message.streaming) ||
    Boolean(props.message.error),
)

const bubbleClass = computed(() => ({
  'markdown-body': props.message.role === 'assistant',
  streaming: Boolean(props.message.streaming),
}))

/** 只有图片、没有文字的消息不渲染空白气泡 */
const hasText = computed(
  () => Boolean(props.message.content) || !props.message.images?.length,
)

const htmlContent = computed(() =>
  isPlain.value
    ? plainTextToRichText(props.message.content)
    : renderMarkdownHtml(props.message.content),
)

/** 流式 / 用户 / 错误消息：纯文本节点 */
const plainNodes = computed(() => plainTextToRichText(props.message.content, fontScale.value))
/** 正常回复：按代码块切分，代码块交给原生 view 渲染以支持按钮事件 */
const segments = computed(() => splitMarkdownSegments(props.message.content))

const timeText = computed(() => formatMessageTime(props.message.timestamp))
const fullTimeText = computed(() => formatFullMessageTime(props.message.timestamp))
const elapsedText = computed(() =>
  props.message.role === 'assistant' ? formatElapsed(props.message.elapsed) : '',
)
const showActions = computed(
  () => !props.message.streaming && Boolean(props.message.content) && !props.message.error,
)

function copyContent() {
  uni.setClipboardData({
    data: props.message.content,
    success: () => ui.notify('已复制到剪贴板'),
    fail: () => ui.notify('复制失败', true),
  })
}

/** 非 H5：代码块复制 / 全屏 */
function copyCode(code: string) {
  uni.setClipboardData({
    data: code,
    success: () => ui.notify('代码已复制'),
    fail: () => ui.notify('复制失败', true),
  })
}

function openCode(segment: MarkdownSegment) {
  ui.openCodeDialog(segment.lang ? `代码 · ${segment.lang}` : '代码', segment.content)
}

async function regenerate() {
  if (!props.isLast || chat.busy) return
  await chat.regenerateLast()
}

/* ---------------------------------------------------------------------------
 * H5：给 Markdown 里的代码块补上 .code-block-shell 外壳与浮层工具栏，
 * 复刻原站的「复制 / 全屏」。小程序端的 rich-text 承载不了这层交互，故只做 H5。
 * ------------------------------------------------------------------------- */
// #ifdef H5
function enhanceCodeBlocks() {
  const root = bubbleRef.value?.$el
  if (!root || !root.querySelectorAll) return
  const blocks = Array.from(root.querySelectorAll('pre')) as HTMLElement[]
  for (const pre of blocks) {
    const parent = pre.parentElement
    if (!parent || parent.classList.contains('code-block-shell')) continue

    const shell = document.createElement('div')
    shell.className = 'code-block-shell'
    const toolbar = document.createElement('div')
    toolbar.className = 'code-toolbar'

    const copyBtn = document.createElement('button')
    copyBtn.type = 'button'
    copyBtn.className = 'code-tool'
    copyBtn.textContent = '复制'
    copyBtn.addEventListener('click', () => {
      const code = pre.querySelector('code')
      uni.setClipboardData({
        data: code ? code.textContent || '' : pre.textContent || '',
        success: () => ui.notify('代码已复制'),
        fail: () => ui.notify('复制失败', true),
      })
    })

    const fullBtn = document.createElement('button')
    fullBtn.type = 'button'
    fullBtn.className = 'code-tool'
    fullBtn.textContent = '全屏'
    fullBtn.addEventListener('click', () => {
      const code = pre.querySelector('code')
      const lang = code?.className?.match(/language-([\w-]+)/)?.[1]
      ui.openCodeDialog(lang ? `代码 · ${lang}` : '代码', code ? code.textContent || '' : '')
    })

    toolbar.append(copyBtn, fullBtn)
    parent.insertBefore(shell, pre)
    shell.append(toolbar, pre)
  }
}

onMounted(() => void nextTick(enhanceCodeBlocks))
watch(
  () => props.message.streaming,
  (streaming) => {
    if (!streaming) void nextTick(enhanceCodeBlocks)
  },
)
// #endif

function previewImage(current: string) {
  void previewImages(props.message.images || [], current)
}
</script>
