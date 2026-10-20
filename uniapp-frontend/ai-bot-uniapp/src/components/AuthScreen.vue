<template>
  <view v-if="!auth.loggedIn" class="auth-screen">
    <view class="auth-card">
      <view class="auth-title"><text>进入知序</text></view>
      <view class="auth-subtitle"><text>登录后继续保存会话和个人资料。</text></view>

      <view class="auth-tabs">
        <view class="auth-tab" :class="{ active: mode === 'login' }" @click="setMode('login')">
          <text>登录</text>
        </view>
        <view class="auth-tab" :class="{ active: mode === 'register' }" @click="setMode('register')">
          <text>注册</text>
        </view>
      </view>

      <view class="auth-form">
        <view class="auth-field">
          <text>用户名</text>
          <input
            v-model="username"
            class="auth-input"
            type="text"
            autocomplete="username"
            :minlength="2"
            :maxlength="50"
          />
        </view>
        <view class="auth-field">
          <text>密码</text>
          <input
            v-model="password"
            class="auth-input"
            password
            autocomplete="current-password"
            :minlength="6"
            :maxlength="128"
          />
        </view>
        <view
          class="primary-button auth-submit"
          :class="{ 'is-disabled': submitting }"
          @click="submit"
        >
          <text>{{ mode === 'login' ? '登录' : '创建账号' }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'

type AuthMode = 'login' | 'register'

const auth = useAuthStore()
const chat = useChatStore()
const ui = useUiStore()

const mode = ref<AuthMode>('login')
const username = ref('')
const password = ref('')
const submitting = ref(false)

function setMode(next: AuthMode) {
  mode.value = next
}

async function submit() {
  if (submitting.value) return
  const name = username.value.trim()
  // 后端约束：用户名 2~50、密码 6~128，先本地拦一道
  if (name.length < 2) {
    ui.notify('用户名至少 2 个字符', true)
    return
  }
  if (password.value.length < 6) {
    ui.notify('密码至少 6 个字符', true)
    return
  }

  submitting.value = true
  try {
    if (mode.value === 'login') await auth.signIn(name, password.value)
    else await auth.signUp(name, password.value)
    chat.resetUserWorkspace()
    password.value = ''
    ui.notify(mode.value === 'login' ? '登录成功' : '账号已创建')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '登录失败', true)
  } finally {
    submitting.value = false
  }
}
</script>
