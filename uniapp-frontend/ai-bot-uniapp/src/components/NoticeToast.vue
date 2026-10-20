<template>
  <view v-if="ui.noticeVisible" class="notice" :class="{ error: ui.noticeError }" role="status">
    <text>{{ ui.noticeText }}</text>
  </view>
</template>

<script setup lang="ts">
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
</script>
