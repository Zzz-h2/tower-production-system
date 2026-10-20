<template>
  <el-dialog
    v-model="visible"
    :title="`编辑项目：${form.project_name || ''}`"
    width="560px"
    @close="onClose"
  >
    <el-form ref="formRef" :model="form" label-width="130px" class="edit-project-form">
      <el-form-item label="项目名称" prop="project_name">
        <el-input v-model="form.project_name" placeholder="必填" />
      </el-form-item>
      <el-form-item label="机型" prop="machine_type">
        <el-input v-model="form.machine_type" placeholder="必填" />
      </el-form-item>
      <el-form-item label="钢塔厂家" prop="factory_name">
        <el-input v-model="form.factory_name" placeholder="必填" />
      </el-form-item>
      <el-form-item label="交付负责人" prop="delivery_person">
        <el-input v-model="form.delivery_person" placeholder="必填" />
      </el-form-item>
      <el-form-item label="大区负责人" prop="big_area_person">
        <el-input v-model="form.big_area_person" placeholder="选填" />
      </el-form-item>
      <el-form-item label="合同总数" prop="contract_count">
        <el-input v-model.number="form.contract_count" placeholder="选填，整数" />
      </el-form-item>
      <el-form-item label="本月计划出品" prop="monthly_plan">
        <el-input v-model.number="form.monthly_plan" placeholder="必填，整数" />
      </el-form-item>
      <el-form-item label="截止上月出品" prop="last_month_output">
        <el-input v-model.number="form.last_month_output" placeholder="选填，整数" />
      </el-form-item>
      <!-- 2026-11 需求：编辑弹窗精简，移除「两个日期项 + 备注」共三个表单项（两个日期项后已全局下线）。
           仅删前端表单项 —— 数据库列与后端 ProjectUpdateRequest 均保留，历史数据原样留存；
           因为 form 与提交 payload 里已不含这三个 key，PUT 不会携带它们（后端 model_dump 后
           按非 None 过滤），故不会被清空。 -->
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { updateProject as updateProjectApi } from '../api/node'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  project: { type: Object, default: null },   // 被编辑的项目行（进入详情前的最新数据）
})
const emit = defineEmits(['update:modelValue', 'updated'])

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => { visible.value = v })

const formRef = ref(null)
const submitting = ref(false)

// 表单字段 = 弹窗当前展示的 8 项（2026-11：移除两个日期项与备注，日期项已全局下线）。
// 这三个字段不再进入 form → 既不会被表单重置，也不会随 payload 提交（避免空值覆盖历史数据）。
const emptyForm = () => ({
  project_name: '',
  machine_type: '',
  factory_name: '',
  delivery_person: '',
  big_area_person: '',
  contract_count: null,
  monthly_plan: null,
  last_month_output: null,
})
const form = reactive(emptyForm())

// 打开时用当前项目行预填（只回填展示中的 8 个字段；
// 两个日期项与备注不回填 → 不参与编辑，也不会被提交覆盖）
watch(
  () => props.project,
  (p) => {
    if (!p) return
    Object.assign(form, {
      project_name: p.project_name || '',
      machine_type: p.machine_type || '',
      factory_name: p.factory_name || '',
      delivery_person: p.delivery_person || '',
      big_area_person: p.big_area_person || '',
      contract_count: p.contract_count ?? null,
      monthly_plan: p.monthly_plan ?? null,
      last_month_output: p.last_month_output ?? null,
    })
  },
  { immediate: true },
)

function onClose() {
  formRef.value?.clearValidate?.()
}

async function submit() {
  submitting.value = true
  try {
    // payload 只含 form 里的 8 个字段；两个日期项与备注**不带 key**（不是传 undefined/null），
    // 后端按「提交即更新」处理其余字段，这三个字段的历史值保持不变。
    await updateProjectApi(props.project.id, { ...form })
    ElMessage.success('保存成功')
    emit('updated')
    emit('update:modelValue', false)
  } catch (e) {
    // 400/404 已由 axios 拦截器统一提示
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 与添加项目弹窗保持一致的标头间距，避免两个弹窗视觉割裂 */
.edit-project-form :deep(.el-form-item) {
  margin-bottom: 22px;
}
.edit-project-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.edit-project-form :deep(.el-dialog__body) {
  padding-top: 16px;
  padding-bottom: 12px;
}
</style>
