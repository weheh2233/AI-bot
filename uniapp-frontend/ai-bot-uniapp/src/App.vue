<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { setUnauthorizedHandler } from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useDocsStore } from '@/stores/docs'
import { useUiStore } from '@/stores/ui'

onLaunch(() => {
  const auth = useAuthStore()
  const chat = useChatStore()
  const docs = useDocsStore()
  const ui = useUiStore()

  // 任何带鉴权的请求收到 401 时统一登出并回到登录页
  setUnauthorizedHandler(() => {
    auth.clearSession()
    chat.resetUserWorkspace()
    docs.reset()
    ui.notify('登录已失效，请重新登录', true)
  })

  auth.restore()
  chat.restoreThread()
  if (auth.token) {
    void auth.refreshMe()
  }
})
</script>

<style lang="scss">
/* 1) 原站 web/index.html 的整份样式表，由 tools/build_styles.py 自动移植。
      桌面尺寸（≥1024px）以它为准，已逐像素验证。 */
@import './styles/app.scss';

/* 2) uni-app 尺寸体系：rpx 移动优先适配层，接管 1024px 以下。
      底部 tab 栏、安全区、触摸目标、气泡宽度都在这里改。 */
@import './styles/adaptive.scss';

/* --------------------------------------------------------------------------
 * 3) 覆盖与修正（放在最后，避免被自动生成的 app.scss 覆盖）
 * ------------------------------------------------------------------------ */

/* 提示条要盖在登录浮层（z-index:10）、审批弹窗（30）、代码弹窗（40）之上 */
.notice {
  z-index: 50;
}

/* 桌面端顶栏有独立的两个导出按钮，「⋯」菜单只给移动端 */
@media (min-width: 1024px) {
  .topbar-more {
    display: none;
  }
}

/* 移动端横向溢出修正（微信小程序历史页内容比屏幕宽、右侧被裁掉）：
   .main 只声明了行、没声明列，隐式列是 auto，会被子组件的内容宽度撑大；
   小程序里组件宿主节点又不受页面样式约束。这里把列锁成屏宽，并逐层允许收缩。 */
@media (max-width: 1023px) {
  .main {
    grid-template-columns: minmax(0, 1fr);
  }

  .history-workspace-wrap,
  .history-workspace,
  .documents-workspace {
    width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }

  .history-inner,
  .history-list,
  .history-item {
    min-width: 0;
    max-width: 100%;
  }

  .history-item > view {
    min-width: 0;
  }

  /* 工具栏：搜索框独占一行，其余按钮换到下一行 */
  .history-tools {
    flex-wrap: wrap;
  }

  .history-search {
    flex: 1 1 100%;
  }

  .history-meta {
    flex-wrap: wrap;
  }
}

/* 字号档位：pages/index/index.vue 在 .app-shell 上写入 --font-scale。
   不能用 `.app-shell.font-large .bubble` 这种后代选择器：微信小程序里
   .bubble 在自定义组件内部，选择器跨不过组件边界；CSS 变量则会继承下去。
   rich-text 内部的字号由 MessageItem 注入到内联样式。 */
@media (max-width: 1023px) {
  .bubble,
  .composer-input {
    font-size: calc(28rpx * var(--font-scale, 1));
  }

  .welcome-text,
  .suggestion {
    font-size: calc(26rpx * var(--font-scale, 1));
  }

  .md-code-text {
    font-size: calc(24rpx * var(--font-scale, 1));
  }
}

@media (min-width: 1024px) {
  .bubble,
  .composer-input,
  .welcome-text {
    font-size: calc(14px * var(--font-scale, 1));
  }

  .md-code-text {
    font-size: calc(12px * var(--font-scale, 1));
  }
}

/* 微信小程序：自定义导航的胶囊按钮固定在右上角，顶栏要让出它的位置。
   基础值 180rpx 是 adaptive.scss 里的兜底，--capsule-space 是启动时按
   真实胶囊坐标算出来的值（pages/index/index.vue 注入）。 */
/* #ifdef MP-WEIXIN */
.topbar {
  padding-right: var(--capsule-space, 180rpx);
}
/* #endif */

/* --------------------------------------------------------------------------
 * 4) 移动端「个人设置」布局修正
 *
 * app.scss 的桌面假设是：进入设置后隐藏左侧栏与顶栏，整页只剩设置面板。
 * 但移动端需要保留顶栏（承载胶囊避让/退出）与底部 tab 栏，同时 .main 只有
 * 一行 grid 时，顶栏会占掉 1fr、设置面板被挤到隐式行，出现“顶部一大片空白、
 * 底部被 tab 栏压住”。这里显式恢复两行并保留 tab 栏的安全区。
 * ------------------------------------------------------------------------ */
@media (max-width: 1023px) {
  .app-shell.settings-mode {
    padding-bottom: calc(100rpx + constant(safe-area-inset-bottom));
    padding-bottom: calc(100rpx + env(safe-area-inset-bottom));
  }

  /* H5 的 > 选择器能穿过组件根节点；小程序端选择器到不了组件内部，
     但组件默认就是显示的，这里的规则不会产生副作用。 */
  .app-shell.settings-mode > .rail {
    display: block;
  }

  .main.settings-active > .topbar {
    display: flex;
  }

  .app-shell.settings-mode .main,
  .main.settings-active {
    grid-template-rows: 96rpx minmax(0, 1fr);
  }
}
</style>
