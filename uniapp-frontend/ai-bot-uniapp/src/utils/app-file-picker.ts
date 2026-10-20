/**
 * Android App 端文件选择。
 *
 * uni.chooseFile 在 App 端不存在（基座 4.76 报 `uni.chooseFile is not a function`），
 * 这里用 Native.js 调起系统选择器（Intent.ACTION_GET_CONTENT），
 * 再通过 ContentResolver 把 content:// 内容复制到 _doc/ai-bot-upload/，
 * 返回 `_doc/...` 路径交给 uni.uploadFile。后端无需改动。
 *
 * 仅在 APP-PLUS 条件编译下被引用；其余端不会打包本文件的调用。
 */

export interface PickedAppFile {
  /** 供 uni.uploadFile 使用的路径（_doc/ai-bot-upload/xxx） */
  path: string
  name: string
  size: number
}

const REQUEST_CODE = 27183
const RESULT_OK = -1
const UPLOAD_DIR = '_doc/ai-bot-upload/'
/** transferFrom 单次最多搬运的字节数 */
const CHUNK = 1024 * 1024

// Native.js 的类型在 @dcloudio/types 里很不完整，这里统一按 any 处理
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

function getPlus(): Any {
  return (globalThis as Any).plus
}

/** 调起系统文件选择器；用户取消时 resolve(null) */
export function pickAndroidFile(): Promise<PickedAppFile | null> {
  return new Promise((resolve, reject) => {
    const plus = getPlus()
    if (!plus || !plus.android) {
      reject(new Error('当前环境不支持选择文件'))
      return
    }
    if (plus.os.name !== 'Android') {
      reject(new Error('当前仅支持 Android 选择文件'))
      return
    }

    const main: Any = plus.android.runtimeMainActivity()
    const Intent: Any = plus.android.importClass('android.content.Intent')
    const intent: Any = new Intent(Intent.ACTION_GET_CONTENT)
    intent.setType('*/*')
    intent.addCategory(Intent.CATEGORY_OPENABLE)

    // 保存并在回调后恢复原 onActivityResult，避免影响其他插件
    const previous = main.onActivityResult
    main.onActivityResult = (requestCode: number, resultCode: number, data: Any) => {
      if (requestCode !== REQUEST_CODE) {
        if (typeof previous === 'function') previous.call(main, requestCode, resultCode, data)
        return
      }
      main.onActivityResult = previous
      if (resultCode !== RESULT_OK || !data) {
        resolve(null)
        return
      }
      try {
        const uri = plus.android.invoke(data, 'getData')
        if (!uri) throw new Error('未获取到文件')
        resolve(copyToDoc(plus, main, uri))
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)))
      }
    }

    try {
      main.startActivityForResult(intent, REQUEST_CODE)
    } catch (error) {
      main.onActivityResult = previous
      reject(new Error('无法打开系统文件选择器'))
    }
  })
}

function queryDisplayName(plus: Any, resolver: Any, uri: Any): string {
  let name = ''
  let cursor: Any = null
  try {
    cursor = plus.android.invoke(resolver, 'query', uri, null, null, null, null)
    if (cursor && plus.android.invoke(cursor, 'moveToFirst')) {
      const index = plus.android.invoke(cursor, 'getColumnIndex', '_display_name')
      if (index >= 0) name = plus.android.invoke(cursor, 'getString', index) || ''
    }
  } catch {
    // 个别文件管理器不支持 query，退回默认名
  } finally {
    if (cursor) plus.android.invoke(cursor, 'close')
  }
  if (!name) {
    const last = String(plus.android.invoke(uri, 'getLastPathSegment') || '')
    name = last.split('/').pop() || ''
  }
  return name || `file_${Date.now()}`
}

function copyToDoc(plus: Any, main: Any, uri: Any): PickedAppFile {
  const resolver: Any = plus.android.invoke(main, 'getContentResolver')
  const name = queryDisplayName(plus, resolver, uri).replace(/[\\/:*?"<>|]/g, '_')

  const File: Any = plus.android.importClass('java.io.File')
  const FileOutputStream: Any = plus.android.importClass('java.io.FileOutputStream')

  const dirPath: string = plus.io.convertLocalFileSystemURL(UPLOAD_DIR)
  const dir: Any = new File(dirPath)
  if (!plus.android.invoke(dir, 'exists')) plus.android.invoke(dir, 'mkdirs')
  const target: Any = new File(dirPath, name)
  const targetPath = String(plus.android.invoke(target, 'getAbsolutePath'))

  let input: Any = null
  let output: Any = null
  try {
    input = plus.android.invoke(resolver, 'openInputStream', uri)
    if (!input) throw new Error('无法读取所选文件（openInputStream 为空）')
    output = new FileOutputStream(targetPath)
    copyStream(plus, input, output)
    plus.android.invoke(output, 'flush')
  } catch (error) {
    console.error('[app-file-picker] copy failed', error)
    throw new Error(`文件复制失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    try {
      if (output) plus.android.invoke(output, 'close')
    } catch {}
    try {
      if (input) plus.android.invoke(input, 'close')
    } catch {}
  }

  // 不信任各复制 API 的返回值（Java long 经 Native.js 桥接后可能不是数字），直接量文件
  const size = Number(plus.android.invoke(target, 'length')) || 0
  console.log('[app-file-picker] copied', targetPath, size)
  if (size <= 0) {
    plus.android.invoke(target, 'delete')
    throw new Error('文件复制后为空，请换一个文件或从“文件管理”中选择')
  }
  return { path: UPLOAD_DIR + name, name, size }
}

/**
 * InputStream → OutputStream。
 * Android 10+ 用 android.os.FileUtils.copy（一次调用完成，最稳）；
 * 更旧的系统退回 Channels + transferFrom 循环。
 */
function copyStream(plus: Any, input: Any, output: Any) {
  const VERSION: Any = plus.android.importClass('android.os.Build$VERSION')
  const sdk = Number(VERSION.SDK_INT) || 0
  if (sdk >= 29) {
    const FileUtils: Any = plus.android.importClass('android.os.FileUtils')
    FileUtils.copy(input, output)
    return
  }
  const Channels: Any = plus.android.importClass('java.nio.channels.Channels')
  const inChannel: Any = Channels.newChannel(input)
  const outChannel: Any = plus.android.invoke(output, 'getChannel')
  let position = 0
  // 防御：返回值异常时最多循环 2048 次（约 2GB），避免死循环
  for (let i = 0; i < 2048; i += 1) {
    const moved = Number(plus.android.invoke(outChannel, 'transferFrom', inChannel, position, CHUNK))
    if (!moved || moved <= 0) break
    position += moved
  }
  plus.android.invoke(inChannel, 'close')
}
