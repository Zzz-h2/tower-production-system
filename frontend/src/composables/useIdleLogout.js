import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../store/auth'
import { subscribe, postActivity, postLogout } from '../utils/idleBroadcast'
import { setSessionExpired } from '../api'

/**
 * 会话无操作自动登出（空闲检测 + 倒计时 + 强制登出 + 多标签同步）。
 *
 * 状态机：IDLE（正常计时） → WARNING（剩余 ≤ 提前量，弹窗倒计时） → EXPIRED（已失效，登出）
 *
 * 计时口径（关键）：
 *  - 空闲倒计时**只**由「真实用户操作」和「点击『继续使用』」重置；
 *  - IDLE 期间每 5 分钟自动调一次 /api/auth/touch，仅用于续期 token（并让后端有机会
 *    提前以 401 IDLE_TIMEOUT 拒绝）**不会**重置本倒计时，否则 30 分钟空闲永远不会触发。
 *  - 前端不解析 token 过期时间，一律以后端 401 为准。
 */

const DEFAULT_IDLE_MINUTES = 30
const DEFAULT_WARNING_SECONDS = 60
/** IDLE 状态下自动续期间隔：5 分钟 */
const TOUCH_INTERVAL_MS = 5 * 60 * 1000
const TOUCH_INTERVAL_SECONDS = TOUCH_INTERVAL_MS / 1000
/** 活动事件节流：距上次重置不足 5 秒不重复重置，避免 mousemove 高频打爆 */
const RESET_THROTTLE_MS = 5000

const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart']

function readIdleSeconds() {
  const minutes = Number(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES)
  const safe = Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_IDLE_MINUTES
  return Math.max(1, Math.floor(safe * 60))
}

function readWarningSeconds() {
  const seconds = Number(import.meta.env.VITE_IDLE_WARNING_SECONDS)
  return Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : DEFAULT_WARNING_SECONDS
}

/**
 * 在根组件 setup() 中调用一次。
 * @returns {{ state: import('vue').Ref<'IDLE'|'WARNING'|'EXPIRED'>, remaining: import('vue').Ref<number>, warningVisible: import('vue').ComputedRef<boolean>, reset: Function, extend: Function, logoutNow: Function }}
 */
export function useIdleLogout() {
  const auth = useAuthStore()
  const router = useRouter()

  const idleSeconds = readIdleSeconds()
  // 提前量不允许吃掉整个空闲窗口，至少留 1 秒倒计时
  const warnSeconds = Math.min(readWarningSeconds(), Math.max(1, idleSeconds - 1))
  const idleToWarningMs = Math.max(1000, (idleSeconds - warnSeconds) * 1000)
  // 续期截止时间：距「最后一次真实用户操作」超过该时长后不再 touch。
  // 否则后端 iat 会被机械地刷新到「最后操作 + 阈值 + 5 分钟」，后端兜底（token 被复制到别处
  // 使用等无前端 touch 的场景）会明显晚于前端判定；停 touch 后后端窗口即可贴近真实空闲时长。
  // 阈值小于一个续期间隔时不做限制（Infinity = 永不跳过）。
  const skipTouchAfterMs =
    idleSeconds > TOUCH_INTERVAL_SECONDS ? (idleSeconds - TOUCH_INTERVAL_SECONDS) * 1000 : Infinity

  /** @type {import('vue').Ref<'IDLE'|'WARNING'|'EXPIRED'>} */
  const state = ref('IDLE')
  /** 弹窗剩余秒数（仅 WARNING 期间递减） */
  const remaining = ref(warnSeconds)
  const warningVisible = computed(() => state.value === 'WARNING' && auth.isLoggedIn)

  let idleTimer = null // IDLE → WARNING
  let tickTimer = null // WARNING 每秒递减
  let touchTimer = null // IDLE 期间每 5 分钟续期
  let lastResetAt = 0
  let unsubscribe = null
  let running = false

  function clearTimer(name) {
    if (name === 'idle' && idleTimer) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
    if (name === 'tick' && tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
    if (name === 'touch' && touchTimer) {
      clearInterval(touchTimer)
      touchTimer = null
    }
  }

  function clearAllTimers() {
    clearTimer('idle')
    clearTimer('tick')
    clearTimer('touch')
  }

  function scheduleWarning() {
    clearTimer('idle')
    idleTimer = setTimeout(() => {
      idleTimer = null
      enterWarning()
    }, idleToWarningMs)
  }

  function startTouchLoop() {
    clearTimer('touch')
    touchTimer = setInterval(() => {
      touch()
    }, TOUCH_INTERVAL_MS)
  }

  function enterWarning() {
    if (!auth.isLoggedIn || state.value === 'EXPIRED') return
    state.value = 'WARNING'
    remaining.value = warnSeconds
    // WARNING/EXPIRED 期间不再自动续期，交由用户点「继续使用」决定
    clearTimer('touch')
    clearTimer('tick')
    tickTimer = setInterval(() => {
      remaining.value -= 1
      if (remaining.value <= 0) {
        remaining.value = 0
        logoutNow('idle')
      }
    }, 1000)
  }

  /**
   * IDLE 期间定时续期：刷新 token（后端 iat 同步刷新）。
   * 网络异常等非 401 失败不登出（避免弱网误伤）；401（含 IDLE_TIMEOUT）立即登出。
   */
  async function touch() {
    if (!auth.isLoggedIn || state.value !== 'IDLE' || document.hidden) return
    // 已接近空闲阈值：停止续期，把后端空闲窗口留给后端自己判定（见 skipTouchAfterMs 注释）
    if (Date.now() - lastResetAt >= skipTouchAfterMs) return
    try {
      await auth.extendSession()
    } catch (e) {
      const status = e?.response?.status
      if (status === 401) {
        // 后端已判定空闲失效：立即登出（401 拦截器会同步给出后端文案）
        logoutNow('idle')
      }
      // 其他错误（断网/超时/5xx）：保持本地计时，等下次续期或用户操作
    }
  }

  /**
   * 重置空闲计时的统一实现（关弹窗 → 回 IDLE → 重排定时器 → 可选广播）
   * @param {boolean} broadcast 是否广播给其他标签（收到其他标签广播时传 false，避免回环）
   */
  function doReset(broadcast) {
    if (state.value === 'EXPIRED' || !auth.isLoggedIn) return
    lastResetAt = Date.now()
    state.value = 'IDLE'
    remaining.value = warnSeconds
    clearTimer('tick')
    scheduleWarning()
    startTouchLoop()
    if (broadcast) postActivity()
  }

  /** 重置空闲计时（用户有操作 / 续期成功） */
  function reset() {
    doReset(true)
  }

  /**
   * 点「继续使用」：调 /auth/touch 续期。
   * 成功 → 关弹窗、重置计时、广播；失败（含 401 IDLE_TIMEOUT）→ 立即转 EXPIRED 登出，
   * 不等待剩余秒数。
   */
  async function extend() {
    if (!auth.isLoggedIn) return
    try {
      await auth.extendSession()
      doReset(true)
    } catch (e) {
      if (state.value === 'EXPIRED') return
      logoutNow('idle')
    }
  }

  /** 登出 + 跳登录页的统一实现 */
  function doLogout(reason, broadcast) {
    // 登出幂等：已登出即直接返回。重复调用来源包括本地计时到点、401 拦截器、其他标签广播。
    // 只依赖 isLoggedIn，不依赖 state 粘性（防止 state 被别处迁移后守卫失效）。
    if (!auth.isLoggedIn) return
    clearAllTimers()
    state.value = 'EXPIRED'
    // 置位后 axios 请求拦截器会直接 reject，拦截登出后的一切在途请求
    setSessionExpired(true)
    // 走到这里 isLoggedIn 仍为 true（见上方守卫），无需再判
    if (broadcast) postLogout(reason)
    auth.logout(reason)
    const current = router.currentRoute.value
    // 主动退出沿用既有的无回跳行为；超时失效则带上 redirect，重登后回到原页面
    const redirect = reason === 'manual' ? '' : current && current.name !== 'login' ? current.fullPath : ''
    router
      .replace({ path: '/login', query: redirect ? { redirect } : {} })
      .catch(() => {
        // 已在登录页时 replace 可能被路由守卫中断，忽略
      })
  }

  /**
   * 立即登出并跳登录页
   * @param {'manual' | 'idle' | 'expired'} reason
   */
  function logoutNow(reason = 'manual') {
    doLogout(reason, true)
  }

  /** 活动事件回调：节流 5 秒，避免高频事件打爆 */
  function onActivity() {
    if (!auth.isLoggedIn || state.value === 'EXPIRED') return
    if (Date.now() - lastResetAt < RESET_THROTTLE_MS) return
    reset()
  }

  /** 其他标签页广播 */
  function onBroadcast(msg) {
    if (!msg || !auth.isLoggedIn) return
    if (msg.type === 'activity') {
      // 其他标签有操作：重置自己的计时（不再回播，避免 A→B→A 回环）
      doReset(false)
    } else if (msg.type === 'logout') {
      // 其他标签已登出（超时或主动）：本标签同步登出，不再回播
      doLogout(msg.reason === 'manual' ? 'manual' : 'idle', false)
    }
  }

  function start() {
    if (running) return
    running = true
    setSessionExpired(false)
    state.value = 'IDLE'
    remaining.value = warnSeconds
    lastResetAt = Date.now()
    ACTIVITY_EVENTS.forEach((evt) => window.addEventListener(evt, onActivity, { passive: true }))
    unsubscribe = subscribe(onBroadcast)
    scheduleWarning()
    startTouchLoop()
  }

  function stop() {
    if (!running) return
    running = false
    ACTIVITY_EVENTS.forEach((evt) => window.removeEventListener(evt, onActivity, { passive: true }))
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    clearAllTimers()
    // EXPIRED 是终态：不能被 stop() 抹掉，否则登出幂等守卫失效导致二次跳转清空 redirect
    if (state.value !== 'EXPIRED') state.value = 'IDLE'
    remaining.value = warnSeconds
  }

  // 仅在已登录时启用：登录成功启动，登出/会话失效后停止（不残留任何定时器）
  watch(() => auth.isLoggedIn, (loggedIn) => (loggedIn ? start() : stop()), { immediate: true })

  onBeforeUnmount(stop)

  return { state, remaining, warningVisible, reset, extend, logoutNow }
}

export default useIdleLogout
