/**
 * 图片压缩工具
 * 压缩图片到指定尺寸和质量，返回 base64 data URL
 *
 * 各端差异：
 * - H5：uni.chooseImage 的 tempFiles 是 File，直接用 FileReader + canvas 压缩；
 * - 小程序 / App：拿到的是临时文件路径，走页面上的隐藏 canvas + 文件系统读取。
 */

interface CompressOptions {
  maxWidth?: number;
  maxHeight?: number;
  quality?: number;
}

/** 计算等比缩放后的尺寸（长边不超过上限） */
function fitSize(
  width: number,
  height: number,
  maxWidth: number,
  maxHeight: number
): { width: number; height: number } {
  if (width >= height) {
    if (width <= maxWidth) return { width, height };
    return { width: maxWidth, height: Math.round((height * maxWidth) / width) };
  }
  if (height <= maxHeight) return { width, height };
  return { width: Math.round((width * maxHeight) / height), height: maxHeight };
}

/** H5：读文件 → 画到离屏 canvas → 导出 jpeg data URL */
async function compressOnH5(file: File, options: CompressOptions): Promise<string> {
  const { maxWidth = 1280, maxHeight = 1280, quality = 0.8 } = options;

  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取图片失败'));
    reader.readAsDataURL(file);
  });

  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error('图片解码失败'));
    el.src = dataUrl;
  });

  const size = fitSize(image.naturalWidth, image.naturalHeight, maxWidth, maxHeight);
  const canvas = document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('当前浏览器不支持 canvas 压缩');
  ctx.drawImage(image, 0, 0, size.width, size.height);
  return canvas.toDataURL('image/jpeg', quality);
}

/**
 * 压缩单张图片
 * @param source H5 传 File；小程序 / App 传临时文件路径
 * @returns base64 data URL
 */
export async function compressImage(
  source: string | File,
  options: CompressOptions = {}
): Promise<string> {
  // #ifdef H5
  if (typeof File !== 'undefined' && source instanceof File) {
    return compressOnH5(source, options);
  }
  // #endif

  const filePath = source as string;
  const { maxWidth = 1280, maxHeight = 1280, quality = 0.8 } = options;

  // 1. 获取图片信息
  const info = await uni.getImageInfo({ src: filePath });
  const size = fitSize(info.width, info.height, maxWidth, maxHeight);

  // 2. 微信小程序使用新版 Canvas 2D，其他平台用旧版 API
  let tempFilePath: string;

  // #ifdef MP-WEIXIN
  // 微信小程序新版 Canvas 2D
  const canvasId = 'image-compress-canvas';
  const query = uni.createSelectorQuery();
  const canvas = await new Promise<any>((resolve, reject) => {
    query
      .select(`#${canvasId}`)
      .fields({ node: true, size: true })
      .exec((res) => {
        if (res && res[0] && res[0].node) {
          resolve(res[0].node);
        } else {
          reject(new Error('获取 canvas 节点失败'));
        }
      });
  });

  canvas.width = size.width;
  canvas.height = size.height;
  const ctx = canvas.getContext('2d');
  
  const img = canvas.createImage();
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error('图片加载失败'));
    img.src = filePath;
  });
  
  ctx.clearRect(0, 0, size.width, size.height);
  ctx.drawImage(img, 0, 0, size.width, size.height);

  tempFilePath = await new Promise<string>((resolve, reject) => {
    uni.canvasToTempFilePath({
      canvas,
      x: 0,
      y: 0,
      width: size.width,
      height: size.height,
      destWidth: size.width,
      destHeight: size.height,
      fileType: 'jpg',
      quality,
      success: (res) => resolve(res.tempFilePath),
      fail: reject,
    } as any); // 微信小程序新版 Canvas 2D 传 canvas 节点，uni-app 类型定义尚未完全支持
  });
  // #endif

  // #ifndef MP-WEIXIN
  // App / 其他小程序：使用旧版 API
  const canvasId = 'image-compress-canvas';
  const ctx = uni.createCanvasContext(canvasId);

  ctx.clearRect(0, 0, size.width, size.height);
  ctx.drawImage(filePath, 0, 0, size.width, size.height);

  await new Promise<void>((resolve) => {
    ctx.draw(false, () => resolve());
  });

  tempFilePath = await new Promise<string>((resolve, reject) => {
    uni.canvasToTempFilePath({
      canvasId,
      x: 0,
      y: 0,
      width: size.width,
      height: size.height,
      destWidth: size.width,
      destHeight: size.height,
      fileType: 'jpg',
      quality,
      success: (res) => resolve(res.tempFilePath),
      fail: reject,
    });
  });
  // #endif

  // 4. 读取为 data URL。
  // uni.getFileSystemManager 是微信小程序 API，App（APP-PLUS）端不存在，
  // 直接调用会得到 undefined，`fs.readFile` 随即抛错。必须按平台分支。
  // #ifdef APP-PLUS
  return readAsDataUrlOnApp(tempFilePath);
  // #endif
  // #ifndef APP-PLUS
  const base64 = await readAsBase64ByFileSystem(tempFilePath);
  return `data:image/jpeg;base64,${base64}`;
  // #endif
}

/** 微信小程序：用文件系统管理器把临时文件读成 base64 */
function readAsBase64ByFileSystem(filePath: string): Promise<string> {
  const fs = uni.getFileSystemManager();
  return new Promise<string>((resolve, reject) => {
    fs.readFile({
      filePath,
      encoding: 'base64',
      success: (res) => resolve(res.data as string),
      fail: reject,
    });
  });
}

/**
 * App（APP-PLUS）：用 plus.io 的 FileReader 读取本地文件。
 * readAsDataURL 会直接返回完整的 `data:image/jpeg;base64,...`。
 */
function readAsDataUrlOnApp(filePath: string): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    type PlusIo = {
      resolveLocalFileSystemURL: (url: string, ok: (entry: any) => void, fail: () => void) => void;
      FileReader: new () => {
        onloadend: ((event: { target?: { result?: unknown } }) => void) | null;
        onerror: (() => void) | null;
        readAsDataURL: (file: unknown) => void;
      };
    };
    const plusIo = (globalThis as { plus?: { io?: PlusIo } }).plus?.io;
    if (!plusIo) {
      reject(new Error('当前环境不支持读取本地文件'));
      return;
    }
    plusIo.resolveLocalFileSystemURL(
      filePath,
      (entry: any) => {
        entry.file(
          (file: any) => {
            const reader = new plusIo.FileReader();
            reader.onloadend = (event) => {
              const result = event?.target?.result;
              if (typeof result === 'string' && result.startsWith('data:')) {
                resolve(result);
              } else {
                reject(new Error('读取图片失败'));
              }
            };
            reader.onerror = () => reject(new Error('读取图片失败'));
            reader.readAsDataURL(file);
          },
          () => reject(new Error('读取图片失败')),
        );
      },
      () => reject(new Error('读取图片失败')),
    );
  });
}

/**
 * 批量压缩图片
 * @param sources H5 为 File[]，小程序 / App 为临时路径数组
 */
export async function compressImages(
  sources: Array<string | File>,
  options?: CompressOptions
): Promise<string[]> {
  const results: string[] = [];
  for (const source of sources) {
    results.push(await compressImage(source, options));
  }
  return results;
}
