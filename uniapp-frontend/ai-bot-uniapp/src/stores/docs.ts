import { defineStore } from 'pinia'
import { deleteDocument, listDocuments, uploadDocument } from '@/api'
import type { DocumentItem } from '@/api'

export interface PickedFile {
  name: string
  path: string
  /** 小程序临时文件路径 */
  tempFilePath: string
  size: number
  /** H5 下 uni.chooseFile 会带上原始 File 对象 */
  file?: File
}

export const useDocsStore = defineStore('docs', {
  state: () => ({
    items: [] as DocumentItem[],
    loading: false,
    /** 原站用「正在读取资料…」和错误文案占位，这里保留同样的三态 */
    placeholder: '登录后查看你的资料。',
    uploading: false,
  }),

  getters: {
    count: (state) => state.items.length,
    chunkCount: (state) => state.items.reduce((sum, doc) => sum + (Number(doc.chunk_count) || 0), 0),
  },

  actions: {
    reset() {
      this.items = []
      this.loading = false
      this.uploading = false
      this.placeholder = '登录后查看你的资料。'
    },

    async load() {
      this.loading = true
      this.placeholder = '正在读取资料…'
      try {
        this.items = await listDocuments()
        this.placeholder = this.items.length
          ? ''
          : '还没有资料。先从左侧上传一份教材或笔记，Agent 就能开始检索。'
      } catch (error) {
        this.items = []
        this.placeholder = error instanceof Error ? error.message : '资料读取失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async upload(file: PickedFile, options: { scope: 'private' | 'global'; title?: string }) {
      this.uploading = true
      try {
        const created = await uploadDocument(file, options)
        await this.load()
        return created
      } finally {
        this.uploading = false
      }
    },

    async remove(doc: DocumentItem) {
      await deleteDocument(doc.id)
      await this.load()
    },
  },
})
