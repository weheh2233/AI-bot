import { defineStore } from 'pinia'
import { getMe, login, register } from '@/api'
import type { AuthResult, User } from '@/api'

/** 与原站保持一致的存储键，方便同一个后端下新旧前端共存。 */
const TOKEN_KEY = 'ai_bot_token'
const USERNAME_KEY = 'ai_bot_username'

function readStorage(key: string): string {
  try {
    const value = uni.getStorageSync(key)
    return typeof value === 'string' ? value : ''
  } catch {
    return ''
  }
}

function writeStorage(key: string, value: string) {
  try {
    if (value) uni.setStorageSync(key, value)
    else uni.removeStorageSync(key)
  } catch {
    // 存储不可用时静默降级为仅内存态
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: '',
    username: '',
    /** 当前用户 ID，用于判断私有资料是否属于自己 */
    userId: 0,
    /**
     * 是否管理员。原站从未调用过 `/auth/me`，因此「所有用户可用」这个上传范围
     * 对普通用户也是可选的，选了只会拿到 403。这里补上文档要求的权限判断。
     */
    isAdmin: false,
  }),

  getters: {
    loggedIn: (state) => Boolean(state.token),
    /** 账号头像里显示的字符，与原站 `state.username?.[0]` 一致。 */
    avatarChar: (state) => (state.username ? state.username.slice(0, 1) : '?'),
  },

  actions: {
    restore() {
      this.token = readStorage(TOKEN_KEY)
      this.username = readStorage(USERNAME_KEY)
    },

    persist() {
      writeStorage(TOKEN_KEY, this.token)
      writeStorage(USERNAME_KEY, this.username)
    },

    applySession(result: AuthResult) {
      this.token = result.access_token
      this.username = result.username
      this.persist()
    },

    clearSession() {
      this.token = ''
      this.username = ''
      this.userId = 0
      this.isAdmin = false
      this.persist()
    },

    async signIn(username: string, password: string) {
      this.applySession(await login(username, password))
      await this.refreshMe()
    },

    async signUp(username: string, password: string) {
      this.applySession(await register(username, password))
      await this.refreshMe()
    },

    async refreshMe(): Promise<User | null> {
      if (!this.token) {
        this.isAdmin = false
        return null
      }
      try {
        const me = await getMe()
        this.isAdmin = Boolean(me.is_admin)
        this.userId = Number(me.user_id) || 0
        if (me.username) {
          this.username = me.username
          this.persist()
        }
        return me
      } catch {
        // /auth/me 失败不影响主流程，保持非管理员的最保守判断
        this.isAdmin = false
        return null
      }
    },
  },
})
