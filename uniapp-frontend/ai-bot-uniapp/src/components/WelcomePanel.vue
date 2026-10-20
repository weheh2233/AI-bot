<template>
  <view class="welcome">
    <view class="welcome-eyebrow">
      <text v-if="mode === 'default'">●</text>
      <text>{{ eyebrow }}</text>
    </view>

    <view class="welcome-title">
      <text v-for="line in titleLines" :key="line" class="welcome-title-line">{{ line }}</text>
    </view>

    <view class="welcome-text"><text>{{ text }}</text></view>

    <view v-if="mode === 'default'" class="suggestions">
      <view
        v-for="item in SUGGESTIONS"
        :key="item"
        class="suggestion"
        @click="emit('pick', item)"
      >
        <text>{{ item }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WelcomeMode } from '@/stores/chat'

const props = defineProps<{ mode: WelcomeMode }>()
const emit = defineEmits<{ pick: [text: string] }>()

/** 与原站首屏 HTML 里的四个建议问题一致 */
const SUGGESTIONS = [
  '用简单例子解释什么是 Agent',
  '帮我总结一下今天学到的内容',
  '我喜欢什么样的回答风格？',
  '根据我上传的资料回答一个问题',
]

/**
 * 原站三处欢迎区文案（首屏 / 新建会话 / 空的历史会话）。
 * 标题里的换行对应原站的 <br>，这里拆成两个块级 text。
 */
const COPY: Record<WelcomeMode, { eyebrow: string; titleLines: string[]; text: string }> = {
  default: {
    eyebrow: '学习工作台',
    titleLines: ['把资料读懂，', '把问题想清楚。'],
    text: '可以直接提问，也可以先上传自己的课程资料。回答会结合当前会话与可检索到的资料。',
  },
  new: {
    eyebrow: '新会话',
    titleLines: ['从一个问题开始。'],
    text: '输入问题，或先去资料页加入自己的课程资料。',
  },
  history: {
    eyebrow: '历史会话',
    titleLines: ['从这里继续。'],
    text: '这个会话还没有可展示的消息。',
  },
}

const eyebrow = computed(() => COPY[props.mode].eyebrow)
const titleLines = computed(() => COPY[props.mode].titleLines)
const text = computed(() => COPY[props.mode].text)
</script>
