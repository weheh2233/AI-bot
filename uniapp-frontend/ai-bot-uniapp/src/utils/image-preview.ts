/**
 * 图片预览。
 *
 * App 端（APP-PLUS）的 uni.previewImage 底层走原生预览器，不识别 base64 data URL，
 * 直接传 data URL 会表现为“点了没反应”。这里先把 data URL 落盘成本地文件再预览。
 * H5 / 小程序直接交给 uni.previewImage。
 */

/**
 * 微信小程序里预览失败时，把 base64 写成临时文件再预览的成本比较高；
 * 当前只在 App 端做转换，其它端保持原逻辑。
 */
function writeDataUrlToLocalFile(dataUrl: string, index: number): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    type PlusIo = {
      resolveLocalFileSystemURL: (url: string, ok: (entry: any) => void, fail: () => void) => void;
    };
    const plusIo = (globalThis as { plus?: { io?: PlusIo } }).plus?.io;
    if (!plusIo) {
      reject(new Error('当前环境不支持图片预览'));
      return;
    }

    const match = /^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/.exec(dataUrl);
    if (!match) {
      reject(new Error('图片格式不支持'));
      return;
    }
    const mime = match[1];
    const base64 = match[2];
    const ext = mime === 'image/png' ? 'png' : mime === 'image/webp' ? 'webp' : 'jpg';
    // 固定文件名：同一位置反复覆盖，避免预览文件越攒越多。
    const fileName = `ai-bot-preview-${index}.${ext}`;

    plusIo.resolveLocalFileSystemURL(
      '_doc/',
      (root: any) => {
        root.getFile(
          fileName,
          { create: true },
          (entry: any) => {
            entry.createWriter(
              (writer: any) => {
                writer.onwrite = () => resolve(entry.toLocalURL());
                writer.onerror = () => reject(new Error('写入图片失败'));
                // HTML5+ 的二进制写入接口，参数就是去掉前缀的 base64 字符串。
                writer.writeAsBinary(base64);
              },
              () => reject(new Error('创建图片文件失败')),
            );
          },
          () => reject(new Error('创建图片文件失败')),
        );
      },
      () => reject(new Error('访问本地存储失败')),
    );
  });
}

// #ifdef MP-WEIXIN
/** 微信小程序：把 data URL 写入用户目录下的临时文件，previewImage 只认文件路径 */
function writeDataUrlToMiniProgramFile(dataUrl: string, index: number): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const match = /^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/.exec(dataUrl);
    if (!match) {
      reject(new Error('图片格式不支持'));
      return;
    }
    const mime = match[1];
    const base64 = match[2];
    const ext = mime === 'image/png' ? 'png' : mime === 'image/webp' ? 'webp' : 'jpg';
    const filePath = `${wx.env.USER_DATA_PATH}/ai-bot-preview-${index}.${ext}`;

    uni.getFileSystemManager().writeFile({
      filePath,
      data: base64,
      encoding: 'base64',
      success: () => resolve(filePath),
      fail: () => reject(new Error('写入图片失败')),
    });
  });
}
// #endif

/**
 * 预览一组图片。
 * @param urls    图片地址列表（data URL 或本地/网络路径）
 * @param current 当前点击的图片，需是 urls 中的一项
 */
export async function previewImages(urls: string[], current?: string): Promise<void> {
  if (!urls.length) return;
  const target = current || urls[0];

  // #ifdef APP-PLUS
  try {
    const localUrls: string[] = [];
    for (let i = 0; i < urls.length; i += 1) {
      const url = urls[i];
      localUrls.push(url.startsWith('data:') ? await writeDataUrlToLocalFile(url, i) : url);
    }
    const index = Math.max(0, urls.indexOf(target));
    uni.previewImage({ urls: localUrls, current: localUrls[index] });
  } catch {
    uni.showToast({ title: '图片预览失败', icon: 'none' });
  }
  return;
  // #endif

  // #ifdef MP-WEIXIN
  try {
    const localUrls: string[] = [];
    for (let i = 0; i < urls.length; i += 1) {
      const url = urls[i];
      localUrls.push(url.startsWith('data:') ? await writeDataUrlToMiniProgramFile(url, i) : url);
    }
    const index = Math.max(0, urls.indexOf(target));
    uni.previewImage({ urls: localUrls, current: localUrls[index] });
  } catch {
    uni.showToast({ title: '图片预览失败', icon: 'none' });
  }
  return;
  // #endif

  // #ifndef APP-PLUS
  // #ifndef MP-WEIXIN
  uni.previewImage({ urls, current: target });
  // #endif
  // #endif
}
