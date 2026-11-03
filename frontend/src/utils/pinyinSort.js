/**
 * 姓名拼音排序（前端唯一实现，2026-11 抽出为公共工具）。
 *
 * 为什么在前端排：后端 `ORDER BY CONVERT(x USING gbk)` 只能在 SQL 侧做；而部分接口
 * （如项目列表随行返回的负责人）不带排序能力，且不同页面若各自实现会出现顺序不一致。
 * 抽出本文件后，**首页「生产进度总览」与「排产计划总览」共用同一份排序规则**。
 *
 * 实现：`Intl.Collator('zh-CN')` 浏览器原生支持拼音比较，无需引入拼音库；
 * Collator 实例会缓存排序规则，列表较长时比逐次 localeCompare 更快。
 */

const zhNameCollator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

/**
 * 多音姓氏修正：ICU 拼音库对多音字只取**常用读音**，与姓氏读音不一致（会排错位置）。
 * 做法是把首字换成**同音常用字**再交给 collator 比较——只影响排序 key，绝不改变显示文本。
 * 典型：曾(céng→zēng，否则排到 C)、乐(lè→yuè，姓氏读岳)、单(shàn)、解(xiè)、查(zhā)…
 * 未列出的姓氏走 collator 默认读音，通常正确。
 */
const SURNAME_HOMOPHONE = {
  曾: '增', 乐: '岳', 单: '山', 解: '谢', 查: '扎', 仇: '求', 区: '欧',
  朴: '瓢', 翟: '宅', 覃: '秦', 缪: '妙', 盖: '葛', 员: '云', 种: '崇',
  折: '舌', 召: '邵', 秘: '必', 尉: '玉', 祭: '债', 阚: '看',
}

/**
 * 生成用于拼音比较的排序 key（仅替换首字为同音字，其它字符原样保留）。
 * @param {string} name 姓名
 * @returns {string} 排序 key（不改显示文本）
 */
export function nameSortKey(name) {
  const s = String(name ?? '')
  if (!s) return s
  const mapped = SURNAME_HOMOPHONE[s.charAt(0)]
  return mapped ? mapped + s.slice(1) : s
}

/**
 * 按姓名拼音升序排序（不修改入参，返回新数组）。
 * @param {string[]|null|undefined} arr 姓名数组
 * @returns {string[]} 排序后的新数组（入参为空时返回 []）
 */
export function sortByNamePinyin(arr) {
  return [...(arr || [])].sort((a, b) => zhNameCollator.compare(nameSortKey(a), nameSortKey(b)))
}
