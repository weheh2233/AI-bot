<template>
  <view v-if="ui.codeDialogVisible">
    <view class="code-dialog-backdrop" @click="ui.closeCodeDialog()" />
    <view class="code-dialog">
      <view class="code-dialog-head">
        <text>{{ ui.codeDialogTitle || '代码' }}</text>
        <view class="code-dialog-actions">
          <view class="code-tool" @click="copyCode"><text>复制</text></view>
          <view class="code-tool" @click="ui.closeCodeDialog()"><text>关闭</text></view>
        </view>
      </view>
      <scroll-view class="code-dialog-pre" scroll-y>
        <scroll-view class="code-dialog-pre-inner" scroll-x>
          <text class="code-dialog-code">{{ ui.codeDialogCode }}</text>
        </scroll-view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { useUiStore } from '@/stores/ui'

/**
 * 全屏代码弹窗。
 *
 * 原站用的是原生 <dialog> + showModal()，它自带居中定位与 ::backdrop 蒙层。
 * uni-app 没有 <dialog> 元素，这里用 .code-dialog-backdrop + 一个
 * position:fixed/margin:auto 居中面板复刻同样的效果（规则见 app.scss 的补充段）。
 * 代码区外层纵向滚动、内层横向滚动：长行不会被裁掉。
 */
const ui = useUiStore()

function copyCode() {
  uni.setClipboardData({
    data: ui.codeDialogCode,
    success: () => ui.notify('代码已复制'),
    fail: () => ui.notify('复制失败', true),
  })
}
</script>

<style lang="scss" scoped>
.code-dialog-actions {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.code-dialog-pre-inner {
  width: 100%;
  white-space: nowrap;
}
</style>
