<template>
  <view v-if="payload" class="approval-modal" role="dialog" aria-modal="true">
    <view class="approval-backdrop" />
    <view class="approval-dialog">
      <view class="approval-header">
        <view class="approval-shield"><text>◇</text></view>
        <view>
          <view class="approval-kicker"><text>HUMAN IN THE LOOP</text></view>
          <view class="approval-heading"><text>Agent 请求执行操作</text></view>
          <view class="approval-subheading">
            <text>模型已暂停运行。请检查下面的内容，再决定是否继续。</text>
          </view>
        </view>
      </view>

      <view class="approval-request-list">
        <view
          v-for="(request, index) in requests"
          :key="`${index}-${request.name}`"
          class="approval-request"
        >
          <view class="approval-request-heading">
            <view class="approval-request-title"><text>{{ titleFor(request) }}</text></view>
            <view class="approval-tool-name"><text>{{ request.name || 'unknown_tool' }}</text></view>
          </view>

          <view class="approval-description">
            <text>{{ request.description || '该操作需要你的确认。' }}</text>
          </view>

          <view class="approval-fields">
            <view v-for="field in fieldsFor(request)" :key="field.key" class="approval-field">
              <view class="approval-field-key"><text>{{ field.label }}</text></view>
              <view class="approval-field-value"><text>{{ field.value }}</text></view>
            </view>
          </view>

          <view class="approval-decision">
            <view class="approval-decision-label"><text>这条操作如何处理？</text></view>
            <view class="decision-options">
              <view
                v-for="option in optionsFor(index)"
                :key="option.value"
                class="decision-option"
                :class="{
                  'is-active': decisions[index]?.choice === option.value,
                  other: option.value === 'other',
                  'is-disabled': !option.allowed,
                }"
                @click="choose(index, option.value, option.allowed)"
              >
                <view class="decision-dot" />
                <text>{{ option.label }}</text>
              </view>
            </view>

            <view v-if="decisions[index]?.choice === 'other'" class="approval-other-wrap">
              <view class="approval-other-label">
                <text>告诉 Agent 你希望如何处理</text>
              </view>
              <textarea
                v-model="decisions[index].message"
                class="approval-other"
                :maxlength="500"
                placeholder="例如：不要记住这一条；或者请把内容改成……"
                placeholder-class="approval-other-placeholder"
              />
            </view>
          </view>
        </view>
      </view>

      <view class="approval-status"><text>{{ status }}</text></view>

      <view class="approval-footer">
        <view class="approval-note">
          <text>每条操作都会按各自选择分别处理；“其他”内容会原样反馈给 Agent。</text>
        </view>
        <view class="approval-buttons">
          <view
            class="modal-approve modal-submit"
            :class="{ 'is-disabled': submitting }"
            @click="submit"
          >
            <text>按以上决定继续</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ActionRequest, Decision, ReviewConfig } from '@/api'
import { useChatStore } from '@/stores/chat'

type Choice = 'approve' | 'reject' | 'other'

interface DecisionState {
  choice: Choice
  message: string
}

const chat = useChatStore()

const decisions = ref<DecisionState[]>([])
const status = ref('')
const submitting = ref(false)

const payload = computed(() => chat.pendingApproval)
const requests = computed<ActionRequest[]>(() => payload.value?.action_requests || [])
const reviewConfigs = computed<ReviewConfig[]>(() => payload.value?.review_configs || [])

/** 原站的字段名中文化映射 */
const FIELD_LABELS: Record<string, string> = {
  key: '记忆分类',
  value: '记忆内容',
  query: '查询内容',
  url: '目标地址',
}

/** 每个动作允许的决定，取自 review_configs（按 action_name 匹配，退化为按下标） */
function allowedFor(index: number): string[] | null {
  const request = requests.value[index]
  const configs = reviewConfigs.value
  if (!configs.length) return null
  const byName = configs.find(
    (item) => (item as { action_name?: string }).action_name === request?.name,
  )
  const config = byName || configs[index] || configs[0]
  const allowed = (config as { allowed_decisions?: unknown }).allowed_decisions
  return Array.isArray(allowed) ? allowed.map((item) => String(item)) : null
}

/**
 * 原站把「允许 / 拒绝 / 其他」三个按钮写死了，完全忽略了后端的
 * review_configs[].allowed_decisions，导致后端不允许的决定也能点。
 * 这里按后端返回的 allowed_decisions 决定哪些选项可用；后端没给就全部可用。
 */
function optionsFor(index: number) {
  const allowed = allowedFor(index)
  const can = (name: string, fallbackFrom: string[] = []) =>
    allowed === null ? true : allowed.includes(name) || fallbackFrom.some((f) => allowed.includes(f))

  return [
    { value: 'approve' as Choice, label: '允许', allowed: can('approve') },
    { value: 'reject' as Choice, label: '拒绝', allowed: can('reject') },
    // 「其他」提交的是带理由的 reject，所以 reject 权限即可覆盖
    { value: 'other' as Choice, label: '其他', allowed: can('other', ['reject', 'edit']) },
  ]
}

function titleFor(request: ActionRequest): string {
  return request.name === 'save_user_memory' ? '写入长期记忆' : '执行工具操作'
}

function fieldsFor(request: ActionRequest) {
  return Object.entries(request.args || {}).map(([key, value]) => ({
    key,
    label: FIELD_LABELS[key] || key,
    value: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
  }))
}

function defaultChoice(index: number): Choice {
  const preferred = optionsFor(index).find((option) => option.allowed && option.value === 'approve')
  if (preferred) return 'approve'
  const first = optionsFor(index).find((option) => option.allowed)
  return first ? first.value : 'approve'
}

function reset() {
  status.value = ''
  submitting.value = false
  decisions.value = requests.value.map((_, index) => ({
    choice: defaultChoice(index),
    message: '',
  }))
}

function choose(index: number, choice: Choice, allowed: boolean) {
  if (!allowed) return
  const target = decisions.value[index]
  if (target) target.choice = choice
}

async function submit() {
  if (submitting.value) return

  for (let index = 0; index < decisions.value.length; index += 1) {
    const decision = decisions.value[index]
    if (decision.choice === 'other' && !decision.message.trim()) {
      status.value = '选择“其他”时，请填写要告诉 Agent 的内容。'
      return
    }
  }

  const payloadDecisions: Decision[] = decisions.value.map((decision) =>
    decision.choice === 'other'
      ? { type: 'reject', message: decision.message.trim() }
      : { type: decision.choice as 'approve' | 'reject' },
  )

  submitting.value = true
  status.value = '正在按你的决定继续执行……'
  try {
    await chat.submitDecisions(payloadDecisions)
  } catch (error) {
    status.value = error instanceof Error ? error.message : '提交失败'
    submitting.value = false
  }
}

watch(payload, (value) => {
  if (value) reset()
})
</script>
