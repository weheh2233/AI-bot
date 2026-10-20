<template>
  <scroll-view class="persona-workspace" scroll-y>
    <view class="persona-inner">
      <view class="persona-hero">
        <view class="documents-eyebrow"><text>对话风格</text></view>
        <view class="persona-title"><text>角色设定</text></view>
        <view class="persona-text">
          <text>创建适合不同任务的角色。角色定义只调整表达和互动方式，不会改变助手的安全规则或工具权限。修改角色不会追溯影响已有会话。</text>
        </view>
      </view>

      <view class="persona-layout">
        <view class="persona-editor">
          <view class="persona-panel-heading">
            <view>
              <view class="persona-panel-title">
                <text>{{ editing ? '编辑角色' : '新建角色' }}</text>
              </view>
              <view class="persona-panel-text">
                <text>填写定位和表达偏好，创建后可设为新会话默认角色。</text>
              </view>
            </view>
            <view class="icon-button" @click="startCreate"><text>＋</text></view>
          </view>

          <view class="persona-form">
            <view class="persona-field">
              <text>角色名称</text>
              <input
                v-model="form.name"
                class="persona-field-input persona-name-input"
                type="text"
                :maxlength="80"
                placeholder="例如：耐心的数学导师"
              />
            </view>

            <view class="persona-field">
              <text>角色定位</text>
              <textarea
                v-model="form.role_definition"
                class="persona-field-textarea"
                :maxlength="4000"
                placeholder="描述这个角色是谁、主要帮助用户做什么"
              />
            </view>

            <view class="persona-field">
              <text>语气</text>
              <textarea
                v-model="form.tone"
                class="persona-field-textarea"
                :maxlength="4000"
                placeholder="例如：平和、严谨，遇到错误时先指出问题再解释原因"
              />
            </view>

            <view class="persona-field">
              <text>回答风格</text>
              <textarea
                v-model="form.style_rules"
                class="persona-field-textarea"
                :maxlength="4000"
                placeholder="例如：先给结论，再给步骤和例子"
              />
            </view>

            <view class="persona-field">
              <text>行为边界</text>
              <textarea
                v-model="form.constraints"
                class="persona-field-textarea"
                :maxlength="4000"
                placeholder="例如：不确定时说明不确定，不虚构资料来源"
              />
            </view>

            <view class="persona-form-actions">
              <view
                class="primary-button persona-form-button"
                :class="{ 'is-disabled': saving }"
                @click="submit"
              >
                <text>{{ editing ? '保存修改' : '创建角色' }}</text>
              </view>
              <view
                v-if="editing"
                class="quiet-button persona-form-button"
                :class="{ 'is-disabled': saving }"
                @click="startCreate"
              >
                <text>取消编辑</text>
              </view>
            </view>
          </view>

          <view class="persona-preview">
            <view class="persona-preview-label"><text>角色设定预览</text></view>
            <view class="persona-preview-text"><text>{{ preview }}</text></view>
          </view>
        </view>

        <view class="persona-library">
          <view class="persona-panel-heading">
            <view>
              <view class="persona-panel-title"><text>可用角色</text></view>
              <view class="persona-panel-text">
                <text>系统预设可复制，自建角色仅当前账号可见。</text>
              </view>
            </view>
            <view class="quiet-button" :class="{ 'is-disabled': persona.loading }" @click="refresh">
              <text>刷新</text>
            </view>
          </view>

          <view class="persona-list">
            <view v-if="!persona.list.length" class="persona-empty">
              <text>{{ persona.placeholder }}</text>
            </view>

            <view
              v-for="item in persona.list"
              :key="item.id === null ? item.name : String(item.id)"
              class="persona-item"
            >
              <view class="persona-item-heading">
                <view class="persona-item-name"><text>{{ item.name }}</text></view>
                <view class="persona-kind" :class="{ custom: !item.is_system }">
                  <text>{{ item.is_system ? '系统' : '自定义' }}</text>
                </view>
              </view>

              <view class="persona-item-desc"><text>{{ excerpt(item.role_definition) }}</text></view>

              <view class="persona-item-actions">
                <view v-if="!item.is_system" class="quiet-button" @click="edit(item)">
                  <text>编辑</text>
                </view>
                <view class="quiet-button" @click="copyPersona(item)"><text>复制</text></view>
                <view
                  class="quiet-button"
                  :class="{ 'is-disabled': isDefault(item) }"
                  @click="makeDefault(item)"
                >
                  <text>{{ isDefault(item) ? '当前默认' : '设为默认' }}</text>
                </view>
                <view
                  v-if="!item.is_system"
                  class="quiet-button persona-delete"
                  @click="remove(item)"
                >
                  <text>删除</text>
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
import { computed, onMounted, reactive, ref } from 'vue'
import type { Persona, PersonaInput } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { usePersonaStore } from '@/stores/persona'
import { useUiStore } from '@/stores/ui'

/** 表单里五个字段都是字符串，和后端要求的全量字段一一对应 */
interface PersonaForm {
  name: string
  role_definition: string
  tone: string
  style_rules: string
  constraints: string
}

const persona = usePersonaStore()
const auth = useAuthStore()
const ui = useUiStore()

/** null 表示「新建」，否则是正在编辑的自建角色 id（系统预设不可编辑） */
const editingId = ref<number | null>(null)
const saving = ref(false)

const form = reactive<PersonaForm>({
  name: '',
  role_definition: '',
  tone: '',
  style_rules: '',
  constraints: '',
})

const editing = computed(() => editingId.value !== null)

/** 预览用实际填写的内容拼装；全部为空时给出说明文案 */
const preview = computed(() => {
  const parts: string[] = []
  const name = form.name.trim()
  const role = form.role_definition.trim()
  const tone = form.tone.trim()
  const style = form.style_rules.trim()
  const constraints = form.constraints.trim()
  if (name) parts.push(`角色：${name}`)
  if (role) parts.push(`定位：${role}`)
  if (tone) parts.push(`表达方式：${tone}`)
  if (style) parts.push(`回答风格：${style}`)
  if (constraints) parts.push(`行为边界：${constraints}`)
  return parts.length ? parts.join('\n') : '填写角色信息后，这里会显示注入到助手上下文中的内容。'
})

/** 把表单整理成请求体：PATCH 是整体替换，五个字段始终全量发送 */
function readForm(): PersonaInput {
  return {
    name: form.name.trim(),
    role_definition: form.role_definition.trim(),
    tone: form.tone.trim(),
    style_rules: form.style_rules.trim(),
    constraints: form.constraints.trim(),
  }
}

function validate(input: PersonaInput): string {
  if (!input.name) return '请填写角色名称'
  if (input.name.length > 80) return '角色名称最多 80 个字'
  if (!input.role_definition) return '请填写角色定位'
  if (!input.tone) return '请填写语气'
  return ''
}

function resetForm() {
  form.name = ''
  form.role_definition = ''
  form.tone = ''
  form.style_rules = ''
  form.constraints = ''
}

/** ＋ / 取消编辑：回到新建模式 */
function startCreate() {
  editingId.value = null
  resetForm()
}

function edit(item: Persona) {
  // 系统预设后端会回 404 角色不存在或不可修改，入口直接隐藏；这里再兜一层
  if (item.is_system || item.id === null) return
  editingId.value = item.id
  form.name = item.name
  form.role_definition = item.role_definition
  form.tone = item.tone
  form.style_rules = item.style_rules
  form.constraints = item.constraints
}

/** 角色定位的首行摘要，用于列表里的简短说明 */
function excerpt(value: string): string {
  const text = (value || '').replace(/\s+/g, ' ').trim()
  if (!text) return '未填写角色定位'
  return text.length > 56 ? `${text.slice(0, 56)}…` : text
}

function isDefault(item: Persona): boolean {
  return item.id !== null && persona.defaultPersonaId === item.id
}

function confirmModal(title: string, content: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    uni.showModal({
      title,
      content,
      confirmText: '确定',
      cancelText: '取消',
      success: (res) => resolve(Boolean(res.confirm)),
      fail: () => resolve(false),
    })
  })
}

async function submit() {
  if (saving.value) return
  const input = readForm()
  const invalid = validate(input)
  if (invalid) {
    ui.notify(invalid, true)
    return
  }

  saving.value = true
  try {
    if (editingId.value === null) {
      const created = await persona.create(input)
      ui.notify(`已创建角色“${created.name}”`)
      startCreate()
    } else {
      const updated = await persona.update(editingId.value, input)
      // 保存后停留在编辑态，方便继续微调同一个角色
      ui.notify(`已保存“${updated.name}”的修改`)
    }
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '保存角色失败', true)
  } finally {
    saving.value = false
  }
}

/** load() 内部已兜底不抛错；失败信息会落在 placeholder 里，这里一并提示出去 */
async function refresh() {
  if (persona.loading) return
  try {
    await persona.load()
    ui.notify(persona.list.length ? '角色列表已刷新' : persona.placeholder || '还没有可用角色')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '角色读取失败', true)
  }
}

async function copyPersona(item: Persona) {
  try {
    const created = await persona.duplicate(item)
    ui.notify(`已复制为“${created.name}”`)
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '复制角色失败', true)
  }
}

async function makeDefault(item: Persona) {
  const id = item.id
  if (id === null) return
  if (isDefault(item)) return
  const confirmed = await confirmModal('设为默认角色', `新会话将默认使用“${item.name}”，确定吗？`)
  if (!confirmed) return
  try {
    await persona.makeDefault(id)
    ui.notify(`已把“${item.name}”设为默认角色`)
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '设置默认角色失败', true)
  }
}

async function remove(item: Persona) {
  if (item.is_system) {
    ui.notify('系统预设不可修改，可以复制成自己的角色后再调整', true)
    return
  }
  if (item.id === null) return
  const confirmed = await confirmModal('删除角色', `删除角色“${item.name}”？删除后无法恢复。`)
  if (!confirmed) return
  try {
    await persona.remove(item)
    if (editingId.value === item.id) startCreate()
    ui.notify('角色已删除')
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : '删除角色失败', true)
  }
}

onMounted(() => {
  // 未登录时 /personas 只会拿到 401，request.ts 会把它当成「登录失效」弹错，
  // 而登录后页面会按工作区统一拉取角色，所以这里先按登录态兜一层。
  if (!auth.loggedIn) return
  if (!persona.list.length) void persona.load()
})
</script>
