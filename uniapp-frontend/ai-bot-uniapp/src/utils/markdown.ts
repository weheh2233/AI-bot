/**
 * Markdown 渲染工具（H5 与小程序共用同一套 markdown-it 配置）。
 *
 * - H5：renderMarkdownHtml 返回已转义的 HTML，交给 `<view class="markdown-body" v-html="...">` 渲染；
 * - 微信小程序：renderMarkdownNodes 返回 rich-text 节点树。rich-text 不认 class、也不继承组件外的 CSS，
 *   所以每个元素的样式都必须内联在 `style` 属性里。
 *
 * 安全策略：markdown-it 关闭原始 HTML（html: false），markdown 源码里的 `<script>` 只会被转义成文本输出。
 * 小程序里没有 DOM、也没有 DOMPurify，因此“禁止原始 HTML”是可移植且足够的主防线；
 * 链接另外通过 renderer 规则补上 target/rel，`javascript:` / `vbscript:` / `file:` 等协议
 * 由 markdown-it 自带的 validateLink 默认拦截。
 */

import MarkdownIt from 'markdown-it';
import type { StateCore, Token } from 'markdown-it';

// 只按需注册常用语言，避免把 highlight.js 全量包打进去（微信主包有 2MB 限制）
import hljs from 'highlight.js/lib/core';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import python from 'highlight.js/lib/languages/python';
import json from 'highlight.js/lib/languages/json';
import bash from 'highlight.js/lib/languages/bash';
import sql from 'highlight.js/lib/languages/sql';
import css from 'highlight.js/lib/languages/css';
import xml from 'highlight.js/lib/languages/xml';
import java from 'highlight.js/lib/languages/java';
import go from 'highlight.js/lib/languages/go';
import rust from 'highlight.js/lib/languages/rust';
import cpp from 'highlight.js/lib/languages/cpp';
import markdown from 'highlight.js/lib/languages/markdown';

/** rich-text 节点：微信小程序 `nodes` 数组的元素（缺省 type 时按 node 处理） */
export interface RichTextNode {
  type?: string;
  name?: string;
  attrs?: Record<string, string>;
  children?: RichTextNode[];
  text?: string;
}

hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('json', json);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('css', css);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('java', java);
hljs.registerLanguage('go', go);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('markdown', markdown);

/** 注册别名，让 ```js / ```ts / ```py / ```sh / ```html 这类常见写法也能高亮 */
function registerAliases(names: string[], languageName: string): void {
  try {
    hljs.registerAliases(names, { languageName });
  } catch {
    // 个别构建产物没有 registerAliases：忽略即可，只是少几个别名
  }
}

registerAliases(['js', 'jsx', 'mjs', 'cjs'], 'javascript');
registerAliases(['ts', 'tsx'], 'typescript');
registerAliases(['py'], 'python');
registerAliases(['sh', 'shell', 'zsh', 'console'], 'bash');
registerAliases(['html', 'xhtml', 'svg'], 'xml');
registerAliases(['c', 'h', 'hpp', 'cc', 'c++'], 'cpp');
registerAliases(['md'], 'markdown');

/* -------------------------------------------------------------------------- */
/* 内联样式（视觉上等价于 H5 的 .markdown-body 规则）                          */
/* -------------------------------------------------------------------------- */

/** 气泡本身继承的字号/行高/颜色：rich-text 拿不到外部 CSS，只能挂在根节点上 */
const STYLE_ROOT = 'font-size:14px;line-height:1.75;color:#1e2826;white-space:normal;';

const STYLE_P = 'margin:0 0 10px;';

/** 标题公共样式，h1~h6 各自只差 font-size */
const STYLE_HEADING_BASE = 'margin:18px 0 8px;color:#24332d;line-height:1.35;font-weight:bold;';

const HEADING_STYLES: Record<string, string> = {
  h1: STYLE_HEADING_BASE + 'font-size:20px;',
  h2: STYLE_HEADING_BASE + 'padding-bottom:5px;border-bottom:1px solid #e3e9e5;font-size:17px;',
  h3: STYLE_HEADING_BASE + 'font-size:15px;',
  h4: STYLE_HEADING_BASE + 'font-size:14px;',
  h5: STYLE_HEADING_BASE + 'font-size:14px;',
  h6: STYLE_HEADING_BASE + 'font-size:14px;',
};

const STYLE_LIST = 'margin:7px 0 11px;padding-left:22px;';
const STYLE_LIST_ITEM = 'margin:3px 0;';
const STYLE_BLOCKQUOTE =
  'margin:10px 0;padding:7px 12px;color:#5e6b65;border-left:3px solid #91b9a6;background:#f3f7f4;';
const STYLE_CODE =
  'padding:2px 5px;border-radius:4px;background:#edf2ef;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;line-height:1.55;';
const STYLE_PRE =
  'max-width:100%;margin:11px 0;padding:12px;overflow:auto;color:#e8eee9;border-radius:6px;background:#27352f;';
const STYLE_PRE_CODE =
  'padding:0;color:inherit;background:transparent;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;line-height:1.55;';
// border-collapse 在小程序里支持较差：即使失效，单元格自身的边框也能撑住表格外观
const STYLE_TABLE = 'width:100%;margin:11px 0;border-collapse:collapse;font-size:12px;';
const STYLE_TH = 'padding:7px 9px;border:1px solid #dfe6e1;background:#f2f6f3;text-align:left;';
const STYLE_TD = 'padding:7px 9px;border:1px solid #dfe6e1;text-align:left;';
// text-decoration-thickness / text-underline-offset 小程序不支持，退化成普通下划线
const STYLE_LINK = 'color:#477a94;text-decoration:underline;';
const STYLE_HR = 'margin:16px 0;border:0;border-top:1px solid #e3e9e5;';
const STYLE_IMAGE = 'max-width:100%;height:auto;border-radius:6px;';

/** 需要内联样式的 token 类型 → 样式 */
const TOKEN_STYLES: Record<string, string> = {
  paragraph_open: STYLE_P,
  bullet_list_open: STYLE_LIST,
  ordered_list_open: STYLE_LIST,
  list_item_open: STYLE_LIST_ITEM,
  blockquote_open: STYLE_BLOCKQUOTE,
  code_inline: STYLE_CODE,
  table_open: STYLE_TABLE,
  th_open: STYLE_TH,
  td_open: STYLE_TD,
  link_open: STYLE_LINK,
  image: STYLE_IMAGE,
  hr: STYLE_HR,
};

/** HTML 转义的兜底表（markdown-it 的 escapeHtml 只转义 & < > "） */
const ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
};

/** 转义 HTML：优先用 markdown-it 自己的实现，保证与渲染器内部一致 */
function escapeHtmlText(str: string): string {
  try {
    return mdHtml.utils.escapeHtml(str);
  } catch {
    return str.replace(/[&<>"]/g, (ch) => ESCAPE_MAP[ch] ?? ch);
  }
}

/** 与原始实现一致：只接受字符串，其它类型统一 String() 兜底 */
function coerceSource(source: unknown): string {
  if (typeof source === 'string') return source;
  try {
    return String(source ?? '');
  } catch {
    // 极端情况（例如自定义 toString 抛错）也不向上抛
    return '';
  }
}

/** 纯文本兜底：换行转 <br>，其余转义（解析/高亮整体失败时使用） */
function toPlainHtml(text: string): string {
  return escapeHtmlText(text).replace(/\r\n|\r|\n/g, '<br>');
}

/**
 * highlight.js 高亮。
 * 未知语言或高亮异常时一律退回 markdown-it 的 escapeHtml，绝不抛错。
 * 注意：markdown-it 的 highlight 选项要求返回「已转义」的 HTML。
 */
function highlightCode(code: string, lang: string): string {
  const text = typeof code === 'string' ? code : String(code ?? '');
  const name = typeof lang === 'string' ? lang.trim().toLowerCase() : '';

  if (name) {
    try {
      if (hljs.getLanguage(name)) {
        return hljs.highlight(text, { language: name, ignoreIllegals: true }).value;
      }
    } catch {
      // 落到下面的纯文本兜底
    }
  }

  return escapeHtmlText(text);
}

/** markdown-it 构造选项：GFM（表格、删除线、自动链接）在默认 preset 里已开启，gfm 仅为语义声明 */
interface MdOptions {
  html: boolean;
  linkify: boolean;
  breaks: boolean;
  gfm: boolean;
  highlight: (str: string, lang: string, attrs: string) => string;
}

/** 只用到 highlight 的选项形状，便于 renderer 规则里取类型 */
interface MdHighlightOptions {
  highlight?: ((str: string, lang: string, attrs: string) => string) | null;
}

const MD_OPTIONS: MdOptions = {
  html: false, // 关闭原始 HTML：XSS 的主防线（小程序里没有 DOMPurify / DOM）
  linkify: true,
  breaks: true, // 单个换行 → <br>，与原站 marked 的 breaks: true 一致
  gfm: true,
  highlight: highlightCode,
};

/**
 * 代码块规则。
 * `forNodes` 为 true 时输出带内联样式的 pre/code（小程序用），
 * 否则输出普通 HTML 并带上 hljs class（H5 用，样式交给 .markdown-body）。
 */
function createFenceRule(
  forNodes: boolean
): (tokens: Token[], idx: number, options: MdHighlightOptions) => string {
  return (tokens, idx, options) => {
    const token = tokens[idx];
    const info = token.info ? token.info.trim() : '';
    const lang = info ? info.split(/\s+/)[0] : '';

    let inner: string;
    try {
      const highlight = options.highlight;
      inner = (highlight ? highlight(token.content, lang, '') : '') || escapeHtmlText(token.content);
    } catch {
      inner = escapeHtmlText(token.content);
    }

    if (forNodes) {
      return `<pre style="${STYLE_PRE}"><code style="${STYLE_PRE_CODE}">${inner}</code></pre>\n`;
    }
    const cls = lang ? ` class="hljs language-${escapeHtmlText(lang)}"` : ' class="hljs"';
    return `<pre><code${cls}>${inner}</code></pre>\n`;
  };
}

/** 缩进式代码块（无语言，不做高亮） */
function createCodeBlockRule(forNodes: boolean): (tokens: Token[], idx: number) => string {
  return (tokens, idx) => {
    const content = escapeHtmlText(tokens[idx].content);
    if (forNodes) {
      return `<pre style="${STYLE_PRE}"><code style="${STYLE_PRE_CODE}">${content}</code></pre>\n`;
    }
    return `<pre><code class="hljs">${content}</code></pre>\n`;
  };
}

/** 把内联样式合并到 token 的 style 属性上（表格对齐等情况已有 style，需要拼接而不是覆盖） */
function styleToken(token: Token): void {
  const style =
    token.type === 'heading_open' ? HEADING_STYLES[token.tag] : TOKEN_STYLES[token.type];
  if (!style) return;

  const prev = token.attrGet('style');
  // 已有样式（表格单元格的 text-align）必须放在后面才能生效：同一条声明里后写的胜出。
  // 不能用 attrJoin：它用空格连接，会拼出非法 CSS。
  const base = style.replace(/;+\s*$/, '');
  token.attrSet('style', prev ? base + ';' + prev.replace(/;+\s*$/, '') : style);
}

/** core 规则：渲染前给块级 token 与行内 token 全部补上内联样式 */
function applyInlineStyles(state: StateCore): void {
  const blocks = state.tokens;
  for (let i = 0; i < blocks.length; i++) {
    const token = blocks[i];
    styleToken(token);

    const children = token.children;
    if (children) {
      for (let j = 0; j < children.length; j++) styleToken(children[j]);
    }
  }
}

/** H5：用 link_open 规则给链接补 target/rel（小程序里没有 DOM，不能事后遍历 a 标签） */
function applyLinkSafety(md: MarkdownIt): void {
  md.renderer.rules.link_open = (tokens, idx, options) => {
    const token = tokens[idx];
    token.attrSet('target', '_blank');
    token.attrSet('rel', 'noopener noreferrer');
    return md.renderer.renderToken(tokens, idx, options);
  };
}

/* -------------------------------------------------------------------------- */
/* 模块级缓存：两个实例各配置一次，渲染时不再重建                              */
/* -------------------------------------------------------------------------- */

/** H5 实例：普通 HTML，靠 .markdown-body 的 CSS 生效 */
const mdHtml = new MarkdownIt(MD_OPTIONS);
applyLinkSafety(mdHtml);
mdHtml.renderer.rules.fence = createFenceRule(false);
mdHtml.renderer.rules.code_block = createCodeBlockRule(false);

/** 小程序实例：所有元素自带内联 style */
const mdNodes = new MarkdownIt(MD_OPTIONS);
mdNodes.renderer.rules.fence = createFenceRule(true);
mdNodes.renderer.rules.code_block = createCodeBlockRule(true);
mdNodes.core.ruler.push('inline_styles', applyInlineStyles);

/* -------------------------------------------------------------------------- */
/* HTML → rich-text 节点树                                                     */
/* -------------------------------------------------------------------------- */

/** rich-text 支持的标签；白名单之外的标签（连同子树）会被平台丢弃 */
const ALLOWED_TAGS = new Set([
  'div',
  'section',
  'p',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'ul',
  'ol',
  'li',
  'blockquote',
  'pre',
  'code',
  'span',
  'strong',
  'b',
  'em',
  'i',
  'u',
  's',
  'del',
  'mark',
  'sub',
  'sup',
  'a',
  'img',
  'br',
  'hr',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
]);

/** 自闭合标签 */
const VOID_TAGS = new Set(['br', 'hr', 'img']);

/** rich-text 只保留 style，以及 href / src / alt，其余属性都会被丢掉 */
const ALLOWED_ATTRS = new Set(['style', 'href', 'src', 'alt']);

/**
 * 这些容器里出现的“纯空白 + 换行”只是 markdown-it 在块级元素之间插入的排版换行，删掉以免多出空白。
 * 行内的单个空格（例如 `**粗体** 和 \`code\``）必须保留，所以只处理带换行的空白。
 */
const BLOCK_CONTAINERS = new Set(['div', 'ul', 'ol', 'table', 'thead', 'tbody', 'tr', 'blockquote']);

// 属性值里的引号在 markdown-it 输出中已被转义（&quot;），因此这里按引号切分是安全的
const TAG_RE = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
const ATTR_RE = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;

/** 解析标签属性，只保留白名单内的属性 */
function parseAttrs(raw: string): Record<string, string> | undefined {
  if (!raw) return undefined;

  const attrs: Record<string, string> = {};
  ATTR_RE.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = ATTR_RE.exec(raw)) !== null) {
    const name = match[1].toLowerCase();
    if (!ALLOWED_ATTRS.has(name)) continue;
    // markdown-it 的 renderAttrs 会把 URL 里的 & 转义成 &amp;，而 rich-text 只会对“文本节点”解码实体，
    // 属性值会原样使用（H5 的 normalizeAttrs 直接透传），所以这里把 &amp; 还原，
    // 否则 ?a=1&amp;b=2 这类链接/图片地址会出错。只还原 &amp;：引号与尖括号保持转义更安全，
    // 也不会影响协议校验（javascript: 之类早已被 markdown-it 的 validateLink 拦掉）。
    attrs[name] = (match[3] ?? match[4] ?? match[5] ?? '').replace(/&amp;/g, '&');
  }

  return Object.keys(attrs).length ? attrs : undefined;
}

function pushChild(parent: RichTextNode, child: RichTextNode): void {
  if (!parent.children) parent.children = [];
  parent.children.push(child);
}

/**
 * 文本节点原样保留：markdown-it 已经做过 HTML 转义，而 rich-text（H5 与微信）会在文本节点里解码实体，
 * 并且文本节点是按纯文本渲染（不是 innerHTML）的，所以 `<script>` 之类不会变成活标签。
 */
function appendText(parent: RichTextNode, raw: string): void {
  if (!raw) return;
  if (raw.indexOf('\n') >= 0 && /^\s+$/.test(raw) && BLOCK_CONTAINERS.has(parent.name ?? '')) {
    return;
  }
  pushChild(parent, { type: 'text', text: raw });
}

/** 把 markdown-it 生成的 HTML 解析成 rich-text 节点数组（标签是良构的，无需容错 HTML 解析器） */
function htmlToNodes(html: string): RichTextNode[] {
  const root: RichTextNode = { type: 'node', name: 'div', children: [] };
  const stack: RichTextNode[] = [root];
  let cursor = 0;
  let match: RegExpExecArray | null;

  TAG_RE.lastIndex = 0;

  while ((match = TAG_RE.exec(html)) !== null) {
    if (match.index > cursor) {
      appendText(stack[stack.length - 1], html.slice(cursor, match.index));
    }
    cursor = TAG_RE.lastIndex;

    const closing = match[1] === '/';
    const name = match[2].toLowerCase();
    const selfClosing = match[4] === '/' || VOID_TAGS.has(name);

    if (closing) {
      // 回退到匹配的开标签；找不到就忽略（理论上不会发生）
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].name === name) {
          stack.length = i;
          break;
        }
      }
      continue;
    }

    if (!ALLOWED_TAGS.has(name)) continue;

    const node: RichTextNode = { type: 'node', name, attrs: parseAttrs(match[3]) };
    pushChild(stack[stack.length - 1], node);
    if (!selfClosing) stack.push(node);
  }

  if (cursor < html.length) {
    appendText(stack[stack.length - 1], html.slice(cursor));
  }

  return root.children ?? [];
}

/** 根节点：rich-text 不继承外部 CSS，字号/行高/颜色只能挂在这里 */
function createRootNode(children: RichTextNode[], scale = 1): RichTextNode {
  const root: RichTextNode = { type: 'node', name: 'div', attrs: { style: STYLE_ROOT }, children };
  if (Number.isFinite(scale) && scale > 0 && scale !== 1) scaleFontSizes(root, scale);
  return root;
}

/**
 * 字号档位：把节点树里所有内联的 `font-size:Npx` 按比例缩放。
 * 标题、行内代码、表格都写死了 px，只改根节点的话它们不会跟着变。
 */
function scaleFontSizes(node: RichTextNode, scale: number): void {
  const style = node.attrs?.style;
  if (style && node.attrs) {
    node.attrs.style = style.replace(
      /font-size:\s*(\d+(?:\.\d+)?)px/g,
      (_all, size: string) => `font-size:${Math.round(Number(size) * scale * 100) / 100}px`,
    );
  }
  node.children?.forEach((child) => scaleFontSizes(child, scale));
}

/* -------------------------------------------------------------------------- */
/* 导出                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * 渲染为 HTML（H5 用）。
 * 配合 `<view class="markdown-body" v-html="renderMarkdownHtml(text)">` 使用；
 * 原始 HTML 已在 markdown-it 层关闭，输出的 `<script>` 只会是转义后的文本。
 */
export function renderMarkdownHtml(source: unknown): string {
  const text = coerceSource(source);
  if (!text) return '';

  try {
    return mdHtml.render(text);
  } catch {
    return toPlainHtml(text);
  }
}

/**
 * 消息分段：普通 Markdown 段 / 代码块段。
 * 非 H5 端用 rich-text 渲染整段消息时，代码块的「复制 / 全屏」按钮无法绑定事件，
 * 因此把代码块单独拆出来，用原生 view 渲染并在容器上绑定按钮。
 */
export interface MarkdownSegment {
  type: 'markdown' | 'code'
  /** markdown 源码，或代码块正文 */
  content: string
  /** 代码块语言（markdown 段为空串） */
  lang: string
}

/**
 * 按顶层代码块切分 markdown 源码。
 * 依赖 markdown-it 的 token.map（源码行范围），因此切分点与渲染器完全一致，
 * 不会出现正则误判 ``` 出现在行内的情况。
 */
export function splitMarkdownSegments(source: unknown): MarkdownSegment[] {
  const text = coerceSource(source);
  if (!text) return [];

  let tokens: Token[];
  try {
    tokens = mdNodes.parse(text, {});
  } catch {
    return [{ type: 'markdown', content: text, lang: '' }];
  }

  const lines = text.split(/\r?\n/);
  const segments: MarkdownSegment[] = [];
  let cursor = 0;

  const pushMarkdown = (start: number, end: number): void => {
    if (end <= start) return;
    const chunk = lines.slice(start, end).join('\n').trim();
    if (chunk) segments.push({ type: 'markdown', content: chunk, lang: '' });
  };

  for (const token of tokens) {
    if (token.type !== 'fence' && token.type !== 'code_block') continue;
    if (!token.map) continue;

    const [start, end] = token.map;
    if (start < cursor) continue;

    pushMarkdown(cursor, start);
    const info = token.info ? token.info.trim() : '';
    segments.push({
      type: 'code',
      content: token.content.replace(/\n$/, ''),
      lang: info ? info.split(/\s+/)[0] : '',
    });
    cursor = end;
  }

  pushMarkdown(cursor, lines.length);
  return segments.length ? segments : [{ type: 'markdown', content: text, lang: '' }];
}

/**
 * 渲染为 rich-text 节点数组（微信小程序 / App 用）。
 * 返回单个根 `div`，其下是从同一套 markdown-it 配置生成的节点树，所有样式均已内联。
 */
export function renderMarkdownNodes(source: unknown, scale = 1): RichTextNode[] {
  const text = coerceSource(source);
  if (!text) return [];

  let html: string;
  try {
    html = mdNodes.render(text);
  } catch {
    html = toPlainHtml(text);
  }

  try {
    return [createRootNode(htmlToNodes(html), scale)];
  } catch {
    // 解析兜底：最坏情况退化成一段纯文本（文本节点不会被当作 HTML 解析）
    return [createRootNode([{ type: 'text', text }], scale)];
  }
}
