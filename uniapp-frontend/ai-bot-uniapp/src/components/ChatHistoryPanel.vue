<template>
  <view class="chat-history-panel">
    <view class="chat-history-header">
      <view class="chat-history-heading"><text>历史对话</text></view>
      <view class="icon-button" @click="refresh"><text>↻</text></view>
    </view>

    <scroll-view class="chat-history-titles" scroll-y>
      <view class="chat-history-titles-inner">
        <view
          v-if="!chat.history.length"
          class="chat-history-empty"
          :class="{ 'history-error': chat.historyIsError }"
        >
          <text>{{ chat.historyPlaceholder }}</text>
        </view>

        <view v-for="item in chat.history" :key="item.thread_id" class="chat-history-item">
          <view class="chat-history-title-row">
            <view
              class="chat-history-title"
              :class="{ current: item.thread_id === chat.threadId }"
              @click="open(item)"
            >
              <text>{{ item.title || '未命名会话' }}</text>
            </view>
            <view
              class="session-del"
              :class="{ 'is-disabled': deleting === item.thread_id }"
              @click.stop="remove(item)"
            >
              <text>✕</text>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>

    <view class="quiet-button chat-history-all" @click="ui.focusWorkspace('history')">
      <text>查看全部历史</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ConversationSummary } from '@/api'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'

const chat = useChatStore()
const ui = useUiStore()
const deleting = ref('')

function refresh() {
  void chat.loadHistoryTitles()
}

async function open(item: ConversationSummary) {
  if (chat.busy) return
  try {
    await chat.loadConversation(item.thread_id)
    ui.focusWorkspace('chat')
    ui.notify('已恢复历史会话')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '会话读取失败', true)
  }
}

async function remove(item: ConversationSummary) {
  const confirmed = await new Promise<boolean>((resolve) => {
    uni.showModal({
      title: '删除会话',
      content: `删除会话“${item.title || '未命名会话'}”？该会话的全部消息会被清除，且无法恢复。`,
      confirmText: '删除',
      cancelText: '取消',
      success: (res) => resolve(Boolean(res.confirm)),
      fail: () => resolve(false),
    })
  })
  if (!confirmed) return

  deleting.value = item.thread_id
  try {
    await chat.deleteConversation(item.thread_id)
    ui.notify('会话已删除')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '删除失败', true)
  } finally {
    deleting.value = ''
  }
}
</script>
