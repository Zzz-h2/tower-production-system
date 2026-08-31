<template>
  <el-dialog
    v-model="visible"
    title="手动添加项目"
    width="560px"
    @close="onClose"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="130px" class="add-project-form">
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
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { addProject as addProjectApi } from '../api/node'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'added'])

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => { visible.value = v })

const formRef = ref(null)
const submitting = ref(false)

// 表单初始值（5 必填 + 5 选填）
const emptyForm = () => ({
  project_name: '',
  machine_type: '',
  factory_name: '',
  delivery_person: '',
  big_area_person: '',
  contract_count: null,
  monthly_plan: null,
  last_month_output: null,
  plan_start_date: '',
  plan_end_date: '',
})
const form = reactive(emptyForm())

// 仅 5 个必填字段做前端校验（后端仍会再次校验并返回 400/409）
const rules = {
  project_name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  machine_type: [{ required: true, message: '请输入机型', trigger: 'blur' }],
  factory_name: [{ required: true, message: '请输入钢塔厂家', trigger: 'blur' }],
  delivery_person: [{ required: true, message: '请输入交付负责人', trigger: 'blur' }],
  monthly_plan: [{ required: true, message: '请输入本月计划出品数量', trigger: 'blur' }],
}

function onClose() {
  Object.assign(form, emptyForm())
  formRef.value?.clearValidate?.()
}

async function submit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch (e) {
    return   // 前端校验未通过
  }
  submitting.value = true
  try {
    await addProjectApi({ ...form })
    ElMessage.success('添加成功')
    emit('added')
    emit('update:modelValue', false)
  } catch (e) {
    // 409 重复 / 400 字段错误已由 axios 拦截器统一提示
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 合理规划各标头与输入框之间的间距，避免堆叠过密 */
.add-project-form :deep(.el-form-item) {
  margin-bottom: 22px;
}
.add-project-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.add-project-form :deep(.el-dialog__body) {
  padding-top: 16px;
  padding-bottom: 12px;
}
</style>
