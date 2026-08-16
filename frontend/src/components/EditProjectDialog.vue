<template>
  <el-dialog
    v-model="visible"
    :title="`编辑项目：${form.project_name || ''}`"
    width="520px"
    @close="onClose"
  >
    <el-form ref="formRef" :model="form" label-width="120px">
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
      <el-form-item label="本月计划出品" prop="monthly_plan">
        <el-input v-model.number="form.monthly_plan" placeholder="必填，整数" />
      </el-form-item>
      <el-form-item label="截止上月出品" prop="last_month_output">
        <el-input v-model.number="form.last_month_output" placeholder="选填，整数" />
      </el-form-item>
      <el-form-item label="计划开工日期" prop="plan_start_date">
        <el-date-picker
          v-model="form.plan_start_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选填"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="计划交付日期" prop="plan_end_date">
        <el-date-picker
          v-model="form.plan_end_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选填"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="备注" prop="remarks">
        <el-input v-model="form.remarks" type="textarea" :rows="2" placeholder="选填" />
      </el-form-item>
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

const emptyForm = () => ({
  project_name: '',
  machine_type: '',
  factory_name: '',
  delivery_person: '',
  monthly_plan: null,
  last_month_output: null,
  plan_start_date: '',
  plan_end_date: '',
  remarks: '',
})
const form = reactive(emptyForm())

// 打开时用当前项目行预填
watch(
  () => props.project,
  (p) => {
    if (!p) return
    Object.assign(form, {
      project_name: p.project_name || '',
      machine_type: p.machine_type || '',
      factory_name: p.factory_name || '',
      delivery_person: p.delivery_person || '',
      monthly_plan: p.monthly_plan ?? null,
      last_month_output: p.last_month_output ?? null,
      plan_start_date: p.plan_start_date || '',
      plan_end_date: p.plan_end_date || '',
      remarks: p.remarks || '',
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
