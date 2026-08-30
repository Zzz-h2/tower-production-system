/**
 * 跨标签页空闲会话同步工具。
 *
 * 优先使用 BroadcastChannel('tower_auth_idle')；浏览器不支持时降级为
 * localStorage 的 storage 事件（约定 key: tower_idle_broadcast）。
 *
 * 消息类型：
 *  - { type: 'activity' }            某个标签页有用户操作 —— 其他标签重置自己的空闲计时
 *  - { type: 'logout', reason: '...' } 某个标签页已登出 —— 其他标签同步登出
 *
 * 所有消息都带 tabId，订阅者会丢弃自己发出的消息（BroadcastChannel 本身不回传自己，
 * 但 localStorage 降级方案会在本页触发 storage 事件，必须靠 tabId 去重，避免回环）。
 */

const CHANNEL_NAME = 'tower_auth_idle'
const STORAGE_KEY = 'tower_idle_broadcast'

// 本标签页唯一标识
const TAB_ID = `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`

const handlers = new Set()

/** @type {BroadcastChannel | null} */
let channel = null
/** @type {((e: StorageEvent) => void) | null} */
let storageListener = null
let inited = false

function normalize(raw) {
  if (!raw || typeof raw !== 'object') return null
  if (raw.type !== 'activity' && raw.type !== 'logout') return null
  return {
    type: raw.type,
    reason: raw.reason || '',
    ts: raw.ts || Date.now(),
  }
}

/** 分发给所有订阅者；丢弃自己发出的消息与非法消息 */
function dispatch(raw) {
  if (!raw || raw.tabId === TAB_ID) return
  const msg = normalize(raw)
  if (!msg) return
  handlers.forEach((handler) => {
    try {
      handler(msg)
    } catch (e) {
      // 单个订阅者抛错不影响其他订阅者
    }
  })
}

function init() {
  if (inited || typeof window === 'undefined') return
  inited = true

  if (typeof BroadcastChannel !== 'undefined') {
    try {
      channel = new BroadcastChannel(CHANNEL_NAME)
      channel.onmessage = (e) => dispatch(e.data)
      return
    } catch (e) {
      channel = null
    }
  }

  // 降级方案：storage 事件只在其他标签页触发，但保险起见仍走 tabId 去重
  storageListener = (e) => {
    if (e.key !== STORAGE_KEY || !e.newValue) return
    try {
      dispatch(JSON.parse(e.newValue))
    } catch (err) {
      // 非法 JSON 忽略
    }
  }
  window.addEventListener('storage', storageListener)
}

function post(payload) {
  init()
  if (typeof window === 'undefined') return
  const msg = { ...payload, tabId: TAB_ID, ts: Date.now() }

  if (channel) {
    try {
      channel.postMessage(msg)
      return
    } catch (e) {
      // 通道异常时退回 localStorage 方案
    }
  }
  try {
    // _nonce 保证每次写入都是新值，storage 事件必定触发（即使消息内容相同）
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...msg, _nonce: `${Date.now()}-${Math.random()}` }))
  } catch (e) {
    // localStorage 不可用（隐私模式/配额满）时静默降级：仅本标签生效
  }
}

/** 广播「本标签有用户操作」，其他标签收到后重置自己的空闲计时 */
export function postActivity() {
  post({ type: 'activity' })
}

/**
 * 广播「本标签已登出」，其他标签收到后同步登出
 * @param {'manual' | 'idle' | 'expired'} reason
 */
export function postLogout(reason = 'manual') {
  post({ type: 'logout', reason })
}

/**
 * 订阅跨标签消息
 * @param {(msg: { type: 'activity' | 'logout', reason: string, ts: number }) => void} handler
 * @returns {() => void} 取消订阅函数
 */
export function subscribe(handler) {
  if (typeof handler !== 'function') return () => {}
  init()
  handlers.add(handler)
  return () => {
    handlers.delete(handler)
  }
}
