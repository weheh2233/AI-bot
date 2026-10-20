import { defineStore } from 'pinia'

export type WorkspaceView = 'chat' | 'history' | 'docs' | 'personas' | 'settings'

/** 个人设置里的二级页 */
export type SettingsDetail = 'overview' | 'model' | 'password' | 'appearance'

/** 原站的通知条 4.2 秒后自动消失。 */
const NOTICE_DURATION = 4200
let noticeTimer: ReturnType<typeof setTimeout> | null = null

export const useUiStore = defineStore('ui', {
  state: () => ({
    /** 当前工作区：对话 / 历史 / 资料 / 角色设定 / 个人设置 */
    view: 'chat' as WorkspaceView,
    /** 设置页的二级页；原站用 .settings-detail 的 hidden 切换 */
    settingsDetail: 'overview' as SettingsDetail,
    noticeText: '',
    noticeError: false,
    noticeVisible: false,
    /** 审批弹窗是否打开；页面根节点据此加 modal-open 阻止背景滚动 */
    approvalVisible: false,
    /** 全屏代码弹窗 */
    codeDialogVisible: false,
    codeDialogTitle: '代码',
    codeDialogCode: '',
  }),

  getters: {
    /** 原站：进入个人设置会隐藏左侧 rail 与顶栏，整页变成设置面板 */
    settingsMode: (state) => state.view === 'settings',
  },

  actions: {
    focusWorkspace(view: WorkspaceView) {
      this.view = view
      if (view === 'settings') this.settingsDetail = 'overview'
    },

    openSettingsDetail(detail: SettingsDetail) {
      this.settingsDetail = detail
    },

    backToSettingsOverview() {
      this.settingsDetail = 'overview'
    },

    openCodeDialog(title: string, code: string) {
      this.codeDialogTitle = title
      this.codeDialogCode = code
      this.codeDialogVisible = true
    },

    closeCodeDialog() {
      this.codeDialogVisible = false
    },

    notify(text: string, isError = false) {
      this.noticeText = text
      this.noticeError = isError
      this.noticeVisible = true
      if (noticeTimer) clearTimeout(noticeTimer)
      noticeTimer = setTimeout(() => {
        this.noticeVisible = false
      }, NOTICE_DURATION)
    },

    setApprovalVisible(visible: boolean) {
      this.approvalVisible = visible
    },
  },
})
