<template>
  <view class="rail">
    <view class="brand">
      <view class="brand-mark"><text>知</text></view>
      <view>
        <view class="brand-name"><text>知序</text></view>
        <view class="brand-sub"><text>学习助手</text></view>
      </view>
    </view>

    <view class="rail-nav">
      <view class="nav-caption"><text>工作区</text></view>
      <view class="nav-list">
        <view
          v-for="item in NAV_ITEMS"
          :key="item.key"
          class="nav-item"
          :class="{ active: ui.view === item.key }"
          @click="go(item.key)"
        >
          <text class="nav-icon">{{ item.icon }}</text>
          <text>{{ item.label }}</text>
        </view>
      </view>
    </view>

    <view class="rail-bottom">
      <view class="account-box">
        <view class="account-row">
          <view class="avatar"><text>{{ auth.avatarChar }}</text></view>
          <view>
            <view class="account-name">
              <text>{{ auth.loggedIn ? auth.username : '尚未登录' }}</text>
            </view>
            <view class="account-status">
              <text>{{ auth.loggedIn ? '会话与资料已同步' : '登录以同步会话和资料' }}</text>
            </view>
          </view>
        </view>
        <view v-if="auth.loggedIn" class="quiet-button logout-button" @click="onLogout">
          <text>退出登录</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useDocsStore } from '@/stores/docs'
import { usePersonaStore } from '@/stores/persona'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import type { WorkspaceView } from '@/stores/ui'

/** v2 导航从 3 项扩到 5 项，顺序与原站一致 */
const NAV_ITEMS: Array<{ key: WorkspaceView; icon: string; label: string }> = [
  { key: 'chat', icon: '◌', label: '学习对话' },
  { key: 'history', icon: '↶', label: '历史会话' },
  { key: 'docs', icon: '▤', label: '我的资料' },
  { key: 'personas', icon: '✳', label: '角色设定' },
  { key: 'settings', icon: '⚙', label: '个人设置' },
]

const auth = useAuthStore()
const chat = useChatStore()
const docs = useDocsStore()
const persona = usePersonaStore()
const settings = useSettingsStore()
const ui = useUiStore()

/**
 * 与原站 focusWorkspace 一致：即便未登录也会切换 view，
 * 由登录浮层盖在上面并给出提示。
 *
 * 各工作区的数据加载由页面统一监听 ui.view 触发，这里不重复请求。
 */
function go(view: WorkspaceView) {
  ui.focusWorkspace(view)
  if (auth.loggedIn) return

  const hint: Partial<Record<WorkspaceView, string>> = {
    docs: '请先登录后查看资料',
    history: '请先登录后查看历史会话',
    personas: '请先登录后管理角色',
    settings: '请先登录后打开设置',
  }
  const message = hint[view]
  if (message) ui.notify(message, true)
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
</script>
