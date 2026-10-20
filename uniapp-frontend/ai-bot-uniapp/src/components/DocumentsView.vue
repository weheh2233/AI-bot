<template>
  <scroll-view class="documents-workspace" scroll-y>
    <view class="documents-inner">
      <view class="documents-hero">
        <view>
          <view class="documents-eyebrow"><text>知识库</text></view>
          <view class="documents-title"><text>管理你的学习资料</text></view>
          <view class="documents-text">
            <text>上传教材、讲义和笔记。完成解析后，Agent 就能在对话中检索这些内容。</text>
          </view>
        </view>
        <view class="documents-stats">
          <view class="documents-stat">
            <view class="documents-stat-value"><text>{{ docs.loading ? '—' : docs.count }}</text></view>
            <view class="documents-stat-label"><text>份可用资料</text></view>
          </view>
          <view class="documents-stat">
            <view class="documents-stat-value"><text>{{ docs.loading ? '—' : docs.chunkCount }}</text></view>
            <view class="documents-stat-label"><text>个知识片段</text></view>
          </view>
        </view>
      </view>

      <view class="documents-layout">
        <view class="upload-box documents-upload">
          <view class="upload-heading">
            <view class="upload-symbol"><text>＋</text></view>
            <view>
              <view class="panel-heading-title"><text>加入新资料</text></view>
              <view class="panel-heading-text">
                <text>支持 PDF、TXT、Markdown、Word 和 PowerPoint。</text>
              </view>
            </view>
          </view>

          <view class="field-label file-field">
            <text>选择文档</text>
            <view class="file-picker" @click="pickFile">
              <view class="file-picker-button"><text>选择文件</text></view>
              <text class="file-picker-name">{{ picked ? picked.name : '未选择文件' }}</text>
            </view>
            <view class="file-detail" :class="{ ready: Boolean(picked) }">
              <text>{{ fileDetail }}</text>
            </view>
            <!-- #ifdef MP-WEIXIN -->
            <view class="file-detail">
              <text>微信小程序只能从聊天会话选文件：先把文件发到“文件传输助手”，再回到这里选择。</text>
            </view>
            <!-- #endif -->
          </view>

          <view class="field-label">
            <text>资料标题</text>
            <input
              v-model="title"
              class="field-control"
              type="text"
              :maxlength="255"
              placeholder="不填则使用文件名"
            />
          </view>

          <view class="field-label">
            <text>使用范围</text>
            <picker
              class="field-picker"
              mode="selector"
              :range="scopeLabels"
              :value="scopeIndex"
              @change="onScopeChange"
            >
              <view class="field-control field-control-picker">
                <text>{{ scopeLabels[scopeIndex] }}</text>
                <text>▾</text>
              </view>
            </picker>
          </view>

          <view
            class="primary-button upload-submit"
            :class="{ 'is-disabled': docs.uploading }"
            @click="submit"
          >
            <text>{{ docs.uploading ? '正在解析并建立索引…' : '上传并建立索引' }}</text>
          </view>
        </view>

        <view class="documents-library">
          <view class="library-heading">
            <view>
              <view class="panel-heading-title"><text>资料库</text></view>
              <view class="panel-heading-text">
                <text>这里列出当前账号能够检索的全部资料。</text>
              </view>
            </view>
            <view class="quiet-button" @click="refresh"><text>刷新列表</text></view>
          </view>

          <view class="doc-list">
            <view v-if="!docs.items.length" class="empty-docs">
              <text>{{ docs.placeholder }}</text>
            </view>

            <view v-for="doc in docs.items" :key="doc.id" class="doc-item">
              <view class="doc-title"><text>{{ doc.title }}</text></view>
              <view class="doc-meta">
                <view class="scope-tag" :class="{ global: doc.scope === 'global' }">
                  <text>{{ doc.scope === 'global' ? '全局' : '私有' }}</text>
                </view>
                <text>{{ String(doc.file_type).toUpperCase() }} · {{ doc.chunk_count }} 个片段</text>
              </view>
              <view class="doc-actions">
                <view
                  class="delete-doc"
                  :class="{ 'is-disabled': !canDelete(doc) }"
                  @click="remove(doc)"
                >
                  <text>删除资料</text>
                </view>
              </view>
            </view>
          </view>
        </view>
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DocumentItem, UniFileLike } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useDocsStore } from '@/stores/docs'
import type { PickedFile } from '@/stores/docs'
import { useUiStore } from '@/stores/ui'
import {
  SUPPORTED_EXTENSIONS,
  formatFileSize,
  validateUploadFile,
} from '@/utils/format'
// #ifdef APP-PLUS
import { pickAndroidFile } from '@/utils/app-file-picker'
// #endif

const auth = useAuthStore()
const docs = useDocsStore()
const ui = useUiStore()

const picked = ref<PickedFile | null>(null)
const title = ref('')
const scope = ref<'private' | 'global'>('private')

/**
 * 「所有用户可用」只对管理员开放。
 * 接口文档要求前端据 /auth/me 的 is_admin 隐藏该入口，而原站从未调用过
 * /auth/me，普通用户选到这一项只会拿到 403。
 */
const scopeOptions = computed<Array<{ value: 'private' | 'global'; label: string }>>(() =>
  auth.isAdmin
    ? [
        { value: 'private', label: '仅自己可用' },
        { value: 'global', label: '所有用户可用' },
      ]
    : [{ value: 'private', label: '仅自己可用' }],
)

const scopeLabels = computed(() => scopeOptions.value.map((item) => item.label))
const scopeIndex = computed(() => {
  const index = scopeOptions.value.findIndex((item) => item.value === scope.value)
  return index >= 0 ? index : 0
})

const fileDetail = computed(() =>
  picked.value
    ? `已选择：${picked.value.name} · ${formatFileSize(picked.value.size)}`
    : '尚未选择文件，单个文件大小以服务端配置为准。',
)

function onScopeChange(event: { detail: { value: number | string } }) {
  const index = Number(event.detail.value) || 0
  const option = scopeOptions.value[index]
  if (option) scope.value = option.value
}

function fileNameFromPath(path: string): string {
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1] || '未命名文件'
}

/** App 端：uni.chooseFile 不存在，改用 Native.js 调系统选择器（见 utils/app-file-picker.ts） */
async function pickAppFile() {
  // #ifdef APP-PLUS
  try {
    const result = await pickAndroidFile()
    if (!result) return
    const candidate: PickedFile = {
      name: result.name,
      path: result.path,
      tempFilePath: result.path,
      size: result.size,
    }
    const invalid = validateUploadFile(candidate)
    if (invalid) {
      ui.notify(invalid, true)
      return
    }
    picked.value = candidate
    ui.notify(`已选择：${candidate.name}`)
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '选择文件失败', true)
  }
  // #endif
}

function pickFile() {
  // #ifdef APP-PLUS
  void pickAppFile()
  return
  // #endif

  const extension = SUPPORTED_EXTENSIONS.map((item) => `.${item}`)

  /**
   * uni.chooseFile 的 tempFiles 在不同端、不同版本下形态不一：
   * 可能是对象数组（含 path / name / size / file），也可能直接是原生 File。
   * 这里统一归一化，避免 H5 拿到原生 File 时取不到 path 而上传失败。
   */
  const onSuccess = (res: { tempFiles?: unknown }) => {
    const raw = res.tempFiles
    const first = Array.isArray(raw) ? raw[0] : raw
    if (!first) return

    const isNativeFile = typeof File !== 'undefined' && first instanceof File
    const entry = first as UniFileLike

    const path = isNativeFile ? '' : entry.path || entry.tempFilePath || ''
    const candidate: PickedFile = {
      name: (isNativeFile ? (first as File).name : entry.name) || fileNameFromPath(path),
      path,
      tempFilePath: isNativeFile ? '' : entry.tempFilePath || path,
      size: typeof entry.size === 'number' ? entry.size : 0,
      file: isNativeFile ? (first as File) : entry.file,
    }
    // 接口文档把扩展名与大小预校验列为前端职责
    const invalid = validateUploadFile(candidate)
    if (invalid) {
      ui.notify(invalid, true)
      return
    }
    picked.value = candidate
  }

  // #ifdef MP-WEIXIN
  // 不用 extension 过滤：微信不同版本对“是否带点”的处理不一致，
  // 选完后再用 validateUploadFile 做扩展名校验，避免把可上传文件也过滤掉。
  uni.chooseMessageFile({ count: 1, type: 'file', success: onSuccess, fail: () => {} })
  // #endif

  // #ifdef H5
  uni.chooseFile({ count: 1, extension, success: onSuccess, fail: () => {} })
  // #endif
}

function refresh() {
  void docs.load().catch((error: unknown) => {
    ui.notify(error instanceof Error ? error.message : '资料读取失败', true)
  })
}

async function submit() {
  if (!picked.value) {
    ui.notify('请先点击“选择文件”选取一份资料', true)
    return
  }
  try {
    const created = await docs.upload(picked.value, {
      scope: scope.value,
      title: title.value.trim() || undefined,
    })
    ui.notify(`已加入“${created.title}”，共 ${created.chunk_count} 个片段`)
    picked.value = null
    title.value = ''
    scope.value = 'private'
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '上传失败', true)
  }
}

/** 私有文档只有本人能删，全局文档只有管理员能删（后端也会 403 兜底） */
function canDelete(doc: DocumentItem): boolean {
  if (doc.scope === 'global') return auth.isAdmin
  return doc.owner_id === auth.userId
}

async function remove(doc: DocumentItem) {
  if (!canDelete(doc)) {
    ui.notify('没有权限删除这份资料', true)
    return
  }
  const confirmed = await new Promise<boolean>((resolve) => {
    uni.showModal({
      title: '删除资料',
      content: `删除“${doc.title}”？`,
      confirmText: '删除',
      cancelText: '取消',
      success: (res) => resolve(Boolean(res.confirm)),
      fail: () => resolve(false),
    })
  })
  if (!confirmed) return
  try {
    await docs.remove(doc)
    ui.notify('资料已删除')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '删除失败', true)
  }
}
</script>
