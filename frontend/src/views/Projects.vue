<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, message, type Project, type Page } from "../api";
const items = ref<Project[]>([]),
  total = ref(0),
  page = ref(1),
  busy = ref(false),
  error = ref(""),
  dialog = ref(false),
  saving = ref(false),
  editing = ref(""),
  router = useRouter();
const form = ref({ name: "", description: "", business_type: "通用助手" });
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const { data } = await api.get<Page<Project>>("/projects", {
      params: { page: page.value },
    });
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
function open(item?: Project) {
  editing.value = item?.id || "";
  form.value = {
    name: item?.name || "",
    description: item?.description || "",
    business_type: item?.business_type || "通用助手",
  };
  dialog.value = true;
}
async function save() {
  saving.value = true;
  try {
    if (editing.value) await api.put(`/projects/${editing.value}`, form.value);
    else await api.post("/projects", form.value);
    dialog.value = false;
    await load();
    ElMessage.success("项目已保存");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    saving.value = false;
  }
}
async function remove(item: Project) {
  try {
    await ElMessageBox.confirm(
      `删除“${item.name}”？如有关联 Agent，需要先删除 Agent。`,
      "删除项目",
      {
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api.delete(`/projects/${item.id}`);
    if (items.value.length === 1 && page.value > 1) page.value--;
    await load();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>测试项目</h1>
      <p>按业务组织待测 Agent，建立可追溯的测试起点。</p>
    </div>
    <el-button type="primary" @click="open()">创建项目</el-button>
  </div>
  <div class="content-grid">
    <section class="list-section">
      <div class="section-toolbar">
        <h2>
          项目列表 <span class="muted">{{ total }} 个</span>
        </h2>
        <el-button @click="load" :loading="busy">刷新</el-button>
      </div>
      <div v-if="error" class="inline-error" role="alert">
        {{ error }} <button @click="load">重试</button>
      </div>
      <div v-loading="busy" class="project-list">
        <div v-if="!busy && !error && !items.length" class="empty">
          <h3>还没有测试项目</h3>
          <p>创建第一个项目，然后接入需要测试的 Agent。</p>
          <el-button @click="open()">创建第一个项目</el-button>
        </div>
        <article v-for="item in items" :key="item.id" class="project-row">
          <div>
            <h3>
              <button
                class="name-link"
                @click="
                  router.push({
                    path: '/agents',
                    query: { project_id: item.id },
                  })
                "
              >
                {{ item.name }}
              </button>
            </h3>
            <p>{{ item.description || "尚未填写项目描述" }}</p>
            <small
              >{{ item.business_type }} · 更新于
              {{
                new Date(item.updated_at + "Z").toLocaleDateString("zh-CN")
              }}</small
            >
          </div>
          <div class="row-actions">
            <button @click="open(item)">编辑</button
            ><button @click="remove(item)">删除</button>
          </div>
        </article>
      </div>
      <el-pagination
        v-if="total > 20"
        layout="prev,pager,next"
        :total="total"
        :page-size="20"
        v-model:current-page="page"
        @current-change="load"
      />
    </section>
    <section class="guide">
      <h2>从项目到真实连接</h2>
      <ol>
        <li>
          <strong>建立项目</strong>
          <p>用业务名称归类，例如企业知识助手或客服问答。</p>
        </li>
        <li>
          <strong>接入 Agent</strong>
          <p>选择 HTTP 接口，或已注册的受控 Python 适配器。</p>
        </li>
        <li>
          <strong>验证并留存版本</strong>
          <p>确认字段映射和连接状态，修改配置会保存新的版本快照。</p>
        </li>
      </ol>
      <p class="guide-note">
        连接测试只验证协议。回答质量、工具行为和安全性需要后续测试任务评估。
      </p>
    </section>
  </div>
  <el-dialog
    v-model="dialog"
    :title="editing ? '编辑项目' : '创建项目'"
    width="560px"
    ><form @submit.prevent="save">
      <label for="project-name">项目名称</label
      ><el-input
        id="project-name"
        v-model="form.name"
        maxlength="120"
        required
      /><label for="business-type">业务类型</label
      ><el-input
        id="business-type"
        v-model="form.business_type"
        maxlength="50"
        required
      /><label for="description">项目描述</label
      ><el-input
        id="description"
        v-model="form.description"
        type="textarea"
        :rows="4"
        maxlength="5000"
      />
      <div class="form-actions">
        <el-button @click="dialog = false">取消</el-button
        ><el-button type="primary" native-type="submit" :loading="saving"
          >保存项目</el-button
        >
      </div>
    </form></el-dialog
  >
</template>
