/**
 * 本地缓存清理。
 *
 * 只清理客户端可以安全重建的内容：
 * - 本地存储里的设置与登录凭证；
 * - 图片预览时落盘的临时文件。
 * 服务端的聊天记录、会话标题、长期记忆不属于缓存，这里不会触碰。
 */

/** 需要清理的本地存储键；以后新增缓存键时同步到这里 */
const CACHE_STORAGE_KEYS = [
  'ai_bot_token',
  'ai_bot_username',
  'ai_bot_appearance',
  'ai_bot_mock_mode',
]

/** 与 image-preview.ts 中的预览文件名保持一致 */
const PREVIEW_PREFIX = 'ai-bot-preview-'

function removeStorageKeys(): void {
  for (const key of CACHE_STORAGE_KEYS) {
    try {
      uni.removeStorageSync(key)
    } catch {
      // 存储不可用时忽略，内存态由调用方重置
    }
  }
}

// #ifdef APP-PLUS
/** App：删除 _doc 下由预览生成的临时图片 */
function clearPreviewFilesOnApp(): Promise<void> {
  return new Promise<void>((resolve) => {
    const plusIo = (globalThis as { plus?: { io?: any } }).plus?.io
    if (!plusIo) {
      resolve()
      return
    }
    plusIo.resolveLocalFileSystemURL(
      '_doc/',
      (root: any) => {
        root.createReader().readEntries(
          (entries: any[]) => {
            const targets = entries.filter(
              (entry) => entry?.isFile && String(entry.name).startsWith(PREVIEW_PREFIX),
            )
            if (!targets.length) {
              resolve()
              return
            }
            let pending = targets.length
            const done = () => {
              pending -= 1
              if (pending === 0) resolve()
            }
            for (const entry of targets) entry.remove(done, done)
          },
          () => resolve(),
        )
      },
      () => resolve(),
    )
  })
}
// #endif

// #ifdef MP-WEIXIN
/** 微信小程序：删除用户目录下由预览生成的临时图片 */
function clearPreviewFilesOnMiniProgram(): Promise<void> {
  return new Promise<void>((resolve) => {
    const userDataPath = (globalThis as { wx?: { env?: { USER_DATA_PATH?: string } } }).wx?.env
      ?.USER_DATA_PATH
    if (!userDataPath) {
      resolve()
      return
    }
    const fs = uni.getFileSystemManager()
    fs.readdir({
      dirPath: userDataPath,
      success: (res) => {
        const targets = (res.files || []).filter((name) => name.startsWith(PREVIEW_PREFIX))
        if (!targets.length) {
          resolve()
          return
        }
        let pending = targets.length
        const done = () => {
          pending -= 1
          if (pending === 0) resolve()
        }
        for (const name of targets) {
          fs.unlink({ filePath: `${userDataPath}/${name}`, success: done, fail: done })
        }
      },
      fail: () => resolve(),
    })
  })
}
// #endif

/** 清理图片预览临时文件；H5 没有落盘文件，直接返回 */
async function clearPreviewFiles(): Promise<void> {
  // #ifdef APP-PLUS
  await clearPreviewFilesOnApp()
  // #endif
  // #ifdef MP-WEIXIN
  await clearPreviewFilesOnMiniProgram()
  // #endif
}

/** 清除缓存：本地存储 + 图片预览临时文件 */
export async function clearAppCache(): Promise<void> {
  removeStorageKeys()
  await clearPreviewFiles()
}
