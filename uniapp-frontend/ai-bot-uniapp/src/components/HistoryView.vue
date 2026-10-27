<template>
  <view class="history-workspace-wrap">
    <!-- 小程序 / App：手机专用布局（单手操作、卡片不横向溢出、操作收进菜单） -->
    <!-- #ifndef H5 -->
    <view class="m-history">
      <view class="m-head">
        <view class="m-search">
          <text class="m-search-icon">⌕</text>
          <input
            v-model="keyword"
            class="m-search-input"
            type="text"
            placeholder="搜索会话内容或标题"
            :maxlength="120"
            confirm-type="search"
            @input="onKeywordInput"
            @confirm="onSearch"
          />
          <view v-if="keyword" class="m-search-clear" @click="clearSearch"><text>×</text></view>
        </view>

        <scroll-view class="m-chips" scroll-x :show-scrollbar="false">
          <view class="m-chips-row">
            <view
              class="m-chip"
              :class="{ on: chat.historyFilter === 'all' && !chat.historyTag }"
              @click="pickAll"
            >
              <text>全部</text>
            </view>
            <view
              class="m-chip"
              :class="{ on: chat.historyFilter === 'favorites' }"
              @click="chat.setHistoryFilter(chat.historyFilter === 'favorites' ? 'all' : 'favorites')"
            >
              <text>★ 收藏</text>
            </view>
            <view
              v-for="tag in chat.historyTags"
              :key="tag"
              class="m-chip"
              :class="{ on: chat.historyTag === tag }"
              @click="chat.setHistoryTag(chat.historyTag === tag ? '' : tag)"
            >
              <text># {{ tag }}</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <scroll-view
        class="m-list"
        scroll-y
        refresher-enabled
        :refresher-triggered="refreshing"
        @refresherrefresh="onPullRefresh"
      >
        <view class="m-list-inner">
          <view
            v-if="!chat.filteredHistory.length"
            class="m-empty"
            :class="{ error: chat.historyIsError }"
          >
            <text>{{ emptyText }}</text>
          </view>

          <view
            v-for="item in chat.filteredHistory"
            :key="item.thread_id"
            class="m-card"
            :class="{ current: item.thread_id === chat.threadId }"
            hover-class="m-card-hover"
            @click="open(item)"
            @longpress="openActions(item)"
          >
            <view class="m-card-top">
              <view class="m-card-title"><text>{{ item.title || '未命名会话' }}</text></view>
              <view class="m-star" :class="{ on: item.is_favorite }" @click.stop="onToggleFavorite(item)">
                <text>{{ item.is_favorite ? '★' : '☆' }}</text>
              </view>
            </view>

            <view v-if="item.preview" class="m-card-preview"><text>{{ item.preview }}</text></view>

            <view class="m-card-foot">
              <view class="m-card-meta">
                <view v-if="item.awaiting_approval" class="m-pending"><text>等待确认</text></view>
                <text>{{ formatConversationTime(item.updated_at) }} · {{ item.message_count }} 条</text>
                <text v-for="tag in item.tags || []" :key="tag" class="m-tag"># {{ tag }}</text>
              </view>
              <view class="m-more" @click.stop="openActions(item)"><text>⋯</text></view>
            </view>
          </view>

          <view v-if="chat.filteredHistory.length" class="m-hint">
            <text>下拉刷新 · 长按卡片可编辑标签或删除</text>
          </view>
        </view>
      </scroll-view>
    </view>
    <!-- #endif -->

    <!-- #ifdef H5 -->
    <scroll-view class="history-workspace" scroll-y>
    <view class="history-inner">
      <view class="history-header">
        <view>
          <view class="documents-eyebrow"><text>会话记录</text></view>
          <view class="history-heading"><text>继续之前的对话</text></view>
          <view class="history-text">
            <text>选择一条历史会话，恢复当时的上下文并从那里接着聊。</text>
          </view>
        </view>

        <view class="history-tools">
          <view class="history-search">
            <input
              v-model="keyword"
              class="history-search-input"
              type="text"
              placeholder="搜索会话内容或标题"
              :maxlength="120"
              confirm-type="search"
              @input="onKeywordInput"
            @confirm="onSearch"
            />
            <text class="history-search-icon">⌕</text>
          </view>

          <picker
            class="history-tools-picker"
            mode="selector"
            :range="tagOptions"
            :value="tagIndex"
            @change="onTagChange"
          >
            <view class="history-tools-select">
              <text>{{ tagOptions[tagIndex] }}</text>
            </view>
          </picker>

          <view class="history-filters">
            <view
              class="history-filter-button"
              :class="{ active: chat.historyFilter === 'all' }"
              @click="chat.setHistoryFilter('all')"
            >
              <text>全部</text>
            </view>
            <view
              class="history-filter-button"
              :class="{ active: chat.historyFilter === 'favorites' }"
              @click="chat.setHistoryFilter('favorites')"
            >
              <text>收藏夹</text>
            </view>
          </view>

          <view class="quiet-button" @click="refresh"><text>↻</text></view>
        </view>
      </view>

      <view class="history-list">
        <view
          v-if="!chat.filteredHistory.length"
          class="history-empty"
          :class="{ 'history-error': chat.historyIsError }"
        >
          <text>{{ emptyText }}</text>
        </view>

        <view
          v-for="item in chat.filteredHistory"
          :key="item.thread_id"
          class="history-item"
          :class="{ current: item.thread_id === chat.threadId }"
          @click="open(item)"
        >
          <view>
            <view class="history-title-row">
              <view class="history-title"><text>{{ item.title || '未命名会话' }}</text></view>
              <view v-if="item.awaiting_approval" class="history-pending">
                <text>等待确认</text>
              </view>
            </view>

            <view class="history-preview"><text>{{ item.preview }}</text></view>

            <view v-if="(item.tags || []).length" class="history-tags">
              <view v-for="tag in item.tags" :key="tag" class="history-tag">
                <text>{{ tag }}</text>
              </view>
            </view>
          </view>

          <view class="history-meta">
            <text>{{ formatConversationTime(item.updated_at) }}</text>
            <text>{{ item.message_count }} 条消息</text>
            <view class="history-resume"><text>继续对话 →</text></view>

            <view class="history-actions">
              <view
                class="message-action"
                :class="{ 'is-active': item.is_favorite }"
                @click.stop="onToggleFavorite(item)"
              >
                <text>{{ item.is_favorite ? '★' : '☆' }}</text>
              </view>
              <view class="message-action" @click.stop="onEditTags(item)"><text>标签</text></view>
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
      </view>
    </view>
    </scroll-view>
    <!-- #endif -->

    <!-- 标签编辑：用页内弹窗而不是 showModal editable（后者在 H5 不支持，
         会导致确认后把标签清空） -->
    <view v-if="tagEditor.open" class="approval-modal">
      <view class="approval-backdrop" @click="closeTagEditor" />
      <view class="approval-dialog">
        <view class="approval-header">
          <view class="approval-shield"><text>#</text></view>
          <view>
            <view class="approval-kicker"><text>TAGS</text></view>
            <view class="approval-heading"><text>编辑会话标签</text></view>
            <view class="approval-subheading"><text>{{ tagEditor.title }}</text></view>
          </view>
        </view>

        <view class="approval-request-list">
          <view class="approval-request">
            <view class="approval-decision-label">
              <text>用逗号分隔，最多 8 个，每个 1～24 字</text>
            </view>
            <input
              v-model="tagEditor.value"
              class="field-control tag-editor-input"
              type="text"
              :maxlength="255"
              placeholder="例如：课程，复习"
            />
          </view>
        </view>

        <view class="approval-status"><text>{{ tagEditor.error }}</text></view>

        <view class="approval-footer">
          <view class="approval-note"><text>保存后立即生效。</text></view>
          <view class="approval-buttons">
            <view class="modal-reject" @click="closeTagEditor"><text>取消</text></view>
            <view
              class="modal-approve"
              :class="{ 'is-disabled': tagEditor.saving }"
              @click="saveTags"
            >
              <text>{{ tagEditor.saving ? '保存中…' : '保存' }}</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import type { ConversationSummary } from '@/api'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import { formatConversationTime } from '@/utils/format'

const chat = useChatStore()
const ui = useUiStore()

const keyword = ref('')
const deleting = ref('')

/** 标签编辑弹窗（页内实现，H5 与小程序一致） */
const tagEditor = reactive({
  open: false,
  threadId: '',
  title: '',
  value: '',
  error: '',
  saving: false,
})

// 搜索关键词以 store 为准：切换工作区/刷新列表时同步输入框
watch(
  () => chat.historyQuery,
  (query) => {
    if (query !== keyword.value) keyword.value = query
  },
)

const ALL_TAGS = '所有标签'
const tagOptions = computed(() => [ALL_TAGS, ...chat.historyTags])
const tagIndex = computed(() => {
  if (!chat.historyTag) return 0
  const index = chat.historyTags.indexOf(chat.historyTag)
  return index < 0 ? 0 : index + 1
})

const emptyText = computed(() => {
  if (chat.historyIsError) return chat.historyPlaceholder
  if (chat.historyQuery) return '没有匹配的会话。'
  if (chat.historyFilter === 'favorites') return '收藏夹里还没有会话。'
  return chat.historyPlaceholder || '还没有历史会话。'
})

function refresh() {
  if (keyword.value.trim()) void chat.searchHistory(keyword.value, 50)
  else void chat.loadHistoryTitles(50)
}

let searchTimer: ReturnType<typeof setTimeout> | null = null

/** 输入停顿 300ms 后自动搜索，与 web 端保持一致 */
function onKeywordInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => refresh(), 300)
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  void chat.searchHistory(keyword.value, 50)
}

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

/* ---------- 手机布局专用 ---------- */

const refreshing = ref(false)

async function onPullRefresh() {
  refreshing.value = true
  try {
    if (keyword.value.trim()) await chat.searchHistory(keyword.value, 50)
    else await chat.loadHistoryTitles(50)
  } finally {
    refreshing.value = false
  }
}

function clearSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  keyword.value = ''
  void chat.loadHistoryTitles(50)
}

function pickAll() {
  chat.setHistoryFilter('all')
  chat.setHistoryTag('')
}

/** 卡片「⋯」/ 长按：收藏、标签、删除收进系统菜单，卡片本身只负责“继续对话” */
function openActions(item: ConversationSummary) {
  const actions = [
    { label: item.is_favorite ? '取消收藏' : '收藏', run: () => onToggleFavorite(item) },
    { label: '编辑标签', run: () => onEditTags(item) },
    { label: '删除会话', run: () => remove(item) },
  ]
  uni.showActionSheet({
    itemList: actions.map((action) => action.label),
    success: (res) => {
      void actions[res.tapIndex]?.run()
    },
  })
}

function onTagChange(event: { detail: { value: number | string } }) {
  const index = Number(event.detail.value) || 0
  chat.setHistoryTag(index === 0 ? '' : chat.historyTags[index - 1] || '')
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

async function onToggleFavorite(item: ConversationSummary) {
  await chat.toggleFavorite(item.thread_id)
}

/** 标签编辑：逗号分隔，最多 8 个、每个不超过 24 字（后端限制） */
function onEditTags(item: ConversationSummary) {
  tagEditor.open = true
  tagEditor.threadId = item.thread_id
  tagEditor.title = item.title || '未命名会话'
  tagEditor.value = (item.tags || []).join('，')
  tagEditor.error = ''
}

function closeTagEditor() {
  if (tagEditor.saving) return
  tagEditor.open = false
}

async function saveTags() {
  if (tagEditor.saving) return

  const tags = tagEditor.value
    .split(/[,，、]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
  if (tags.length > 8) {
    tagEditor.error = '最多只能有 8 个标签'
    return
  }
  if (tags.some((tag) => tag.length > 24)) {
    tagEditor.error = '标签长度需为 1 到 24 个字符'
    return
  }

  tagEditor.saving = true
  tagEditor.error = ''
  try {
    await chat.setConversationTags(tagEditor.threadId, tags)
    tagEditor.open = false
    ui.notify('标签已更新')
  } catch (error) {
    tagEditor.error = error instanceof Error ? error.message : '标签更新失败'
  } finally {
    tagEditor.saving = false
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

<style lang="scss" scoped>
.history-workspace-wrap {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.history-workspace {
  width: 100%;
  height: 100%;
}

.tag-editor-input {
  margin-top: 10rpx;
}

/* ==========================================================================
   小程序 / App 手机布局
   顶部固定：搜索 + 横滑筛选；下方列表独立滚动，支持下拉刷新。
   卡片只做一件事（点开继续对话），其他操作收进「⋯」/ 长按菜单。
   ========================================================================== */
.m-history {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f3f5f2;
}

.m-head {
  flex: none;
  padding: 20rpx 24rpx 12rpx;
  background: #fbfcfa;
  border-bottom: 1rpx solid #e3e9e5;
}

.m-search {
  display: flex;
  align-items: center;
  gap: 12rpx;
  height: 76rpx;
  padding: 0 24rpx;
  border-radius: 38rpx;
  background: #eef2ee;
}

.m-search-icon {
  color: #75817d;
  font-size: 32rpx;
}

.m-search-input {
  flex: 1;
  min-width: 0;
  height: 76rpx;
  color: #1e2826;
  font-size: 28rpx;
}

.m-search-clear {
  width: 40rpx;
  height: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: white;
  background: #b6c1bb;
  font-size: 26rpx;
  line-height: 1;
}

.m-chips {
  width: 100%;
  margin-top: 16rpx;
  white-space: nowrap;
}

.m-chips-row {
  display: inline-flex;
  gap: 12rpx;
  padding-right: 24rpx;
}

.m-chip {
  flex: none;
  display: inline-flex;
  align-items: center;
  height: 56rpx;
  padding: 0 24rpx;
  color: #5d6a64;
  border: 1rpx solid #dfe6e1;
  border-radius: 28rpx;
  background: white;
  font-size: 24rpx;
}

.m-chip.on {
  color: white;
  border-color: #28765f;
  background: #28765f;
  font-weight: 600;
}

.m-list {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.m-list-inner {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
  padding: 20rpx 24rpx 40rpx;
}

.m-card {
  width: 100%;
  box-sizing: border-box;
  padding: 26rpx 26rpx 18rpx;
  border: 1rpx solid #e3e9e5;
  border-radius: 20rpx;
  background: white;
  overflow: hidden;
}

.m-card.current {
  border-color: #8ebaa4;
  box-shadow: inset 6rpx 0 0 #28765f;
}

.m-card-hover {
  background: #f6faf7;
}

.m-card-top {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
}

.m-card-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #1e2826;
  font-size: 30rpx;
  font-weight: 700;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.m-star {
  flex: none;
  margin: -10rpx -10rpx 0 0;
  padding: 10rpx;
  color: #b6c1bb;
  font-size: 32rpx;
  line-height: 1;
}

.m-star.on {
  color: #c7962f;
}

.m-card-preview {
  display: -webkit-box;
  margin-top: 10rpx;
  overflow: hidden;
  color: #6b7671;
  font-size: 25rpx;
  line-height: 1.6;
  word-break: break-all;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.m-card-foot {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 14rpx;
}

.m-card-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8rpx 14rpx;
  color: #8a9590;
  font-size: 22rpx;
}

.m-tag {
  color: #1d5a49;
}

.m-pending {
  padding: 2rpx 10rpx;
  color: #7b5524;
  border-radius: 6rpx;
  background: #faf0df;
  font-size: 20rpx;
  font-weight: 700;
}

.m-more {
  flex: none;
  width: 64rpx;
  height: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: -14rpx;
  color: #75817d;
  font-size: 32rpx;
  font-weight: 700;
}

.m-empty {
  margin-top: 40rpx;
  padding: 60rpx 24rpx;
  color: #75817d;
  border: 1rpx dashed #cbd8d0;
  border-radius: 20rpx;
  text-align: center;
  font-size: 26rpx;
}

.m-empty.error {
  color: #a9443b;
}

.m-hint {
  padding: 8rpx 0 0;
  color: #a3ada8;
  text-align: center;
  font-size: 22rpx;
}
</style>
