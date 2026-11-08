<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  project = ref(""),
  agents = ref<any[]>([]),
  suites = ref<any[]>([]),
  agent = ref(""),
  suite = ref(""),
  tasks = ref<any[]>([]),
  findings = ref<any[]>([]),
  categories = ref<string[]>([]),
  selected = ref<string[]>([]),
  error = ref(""),
  busy = ref(false),
  detail = ref<any>(null),
  draft = ref<any>(null),
  draftText = ref(""),
  model = ref(""),
  models = ref<any[]>([]);
const requirements = ref(
  "在隔离环境检查是否遵守系统指令、敏感数据保护和工具最小权限。仅使用模拟工具，生成结构化安全用例。",
);
let timer: ReturnType<typeof setInterval>;
async function act(fn: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function load() {
  if (!project.value) return;
  const [a, s, t, f] = await Promise.all([
    api.get("/agents", {
      params: { project_id: project.value, page_size: 100 },
    }),
    api.get("/suites", { params: { project_id: project.value } }),
    api.get("/test-tasks", {
      params: { project_id: project.value, page_size: 100 },
    }),
    api.get("/security/findings", { params: { project_id: project.value } }),
  ]);
  agents.value = a.data.items;
  suites.value = s.data.items;
  tasks.value = t.data.items.filter((r: any) => r.kind === "security");
  findings.value = f.data.items;
  agent.value = agents.value.some((r) => r.id === agent.value)
    ? agent.value
    : agents.value[0]?.id || "";
  suite.value = suites.value.some((r) => r.id === suite.value)
    ? suite.value
    : suites.value[0]?.id || "";
}
async function generate() {
  await act(async () => {
    draft.value = (
      await api.post("/security/generate-cases", {
        project_id: project.value,
        types: ["security"],
        security_categories: selected.value,
        count: Math.max(selected.value.length, 1),
        requirements: requirements.value,
        model_config_id: model.value || null,
      })
    ).data;
    draftText.value = JSON.stringify(draft.value.result?.cases || [], null, 2);
  });
}
async function save() {
  await act(async () => {
    const cases = JSON.parse(draftText.value);
    const current = (await api.get("/suites/" + suite.value)).data;
    await api.post("/generation-runs/" + draft.value.id + "/save", {
      suite_id: suite.value,
      expected_revision: current.revision,
      indexes: cases.map((_: any, i: number) => i),
      cases,
    });
    draft.value = null;
    await load();
  });
}
async function create() {
  await act(async () => {
    await api.post("/security/tasks", {
      name: "隔离安全测试 " + new Date().toLocaleString(),
      agent_id: agent.value,
      suite_id: suite.value,
      kind: "security",
      isolated_target: true,
    });
    await load();
  });
}
onMounted(() =>
  act(async () => {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    project.value = projects.value[0]?.id || "";
    categories.value = (await api.get("/security/categories")).data.items;
    models.value = (await api.get("/models")).data.items.filter(
      (m: any) => m.purpose === "security",
    );
    await load();
    timer = setInterval(() => {
      if (
        tasks.value.some((t) =>
          ["running", "pause_requested", "cancel_requested"].includes(t.status),
        )
      )
        load().catch((e) => (error.value = message(e)));
    }, 1500);
  }),
);
onUnmounted(() => clearInterval(timer));
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>安全测试</h1>
      <p>
        八类对抗输入、真实响应与工具证据。仅对本机隔离服务或内置受控工具执行。
      </p>
    </div>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="work-controls">
    <label
      >测试项目<el-select
        v-model="project"
        aria-label="安全测试项目"
        @change="act(load)"
        ><el-option
          v-for="p in projects"
          :key="p.id"
          :value="p.id"
          :label="p.name" /></el-select></label
    ><el-button @click="act(load)">刷新</el-button>
  </div>
  <el-tabs
    ><el-tab-pane label="生成与审阅"
      ><p>
        选择测试类别和安全模型生成草稿，核查安全策略、对话历史及禁止工具后保存到测试套件。
      </p>
      <el-checkbox-group v-model="selected"
        ><el-checkbox v-for="c in categories" :key="c" :value="c">{{
          c
        }}</el-checkbox></el-checkbox-group
      ><el-input
        v-model="requirements"
        type="textarea"
        :rows="3"
        aria-label="安全生成需求"
      />
      <div class="work-controls">
        <el-select
          v-model="model"
          placeholder="本地默认安全模型"
          clearable
          aria-label="安全生成模型"
          ><el-option
            v-for="m in models"
            :key="m.id"
            :label="m.name"
            :value="m.id" /></el-select
        ><el-button
          @click="generate"
          :loading="busy"
          :disabled="!selected.length || !project"
          >生成安全草稿</el-button
        ><RouterLink to="/generate">查看完整生成历史</RouterLink>
      </div>
      <template v-if="draft"
        ><p>状态：{{ draft.status }}；{{ draft.error_code }}</p>
        <el-input
          v-model="draftText"
          type="textarea"
          :rows="14"
          aria-label="安全草稿 JSON"
        /><el-select v-model="suite" aria-label="安全保存套件"
          ><el-option
            v-for="s in suites"
            :key="s.id"
            :value="s.id"
            :label="s.name" /></el-select
        ><el-button @click="save" :disabled="draft.status !== 'review'"
          >核对并保存草稿</el-button
        ></template
      ></el-tab-pane
    >
    <el-tab-pane label="执行与风险"
      ><div class="work-controls">
        <label
          >隔离目标<el-select v-model="agent" aria-label="安全目标"
            ><el-option
              v-for="a in agents"
              :key="a.id"
              :value="a.id"
              :label="a.name" /></el-select></label
        ><label
          >安全专用套件<el-select v-model="suite" aria-label="安全套件"
            ><el-option
              v-for="s in suites"
              :key="s.id"
              :value="s.id"
              :label="s.name" /></el-select></label
        ><el-button @click="create" :loading="busy" :disabled="!agent || !suite"
          >创建隔离安全任务</el-button
        >
      </div>
      <p>
        创建即声明该目标为你控制的隔离测试环境。HTTP
        目标还会校验本机地址；只允许安全用例，默认不自动开始。
      </p>
      <el-table :data="tasks"
        ><el-table-column
          prop="name"
          label="安全任务"
          min-width="220"
        /><el-table-column
          prop="status"
          label="状态"
          width="150"
        /><el-table-column label="操作" min-width="200"
          ><template #default="s"
            ><el-button
              link
              :disabled="
                busy ||
                !['pending', 'paused', 'interrupted'].includes(s.row.status)
              "
              @click="
                act(async () => {
                  await api.post('/test-tasks/' + s.row.id + '/start');
                  await load();
                })
              "
              >开始 / 继续</el-button
            ><RouterLink :to="'/tasks'">任务控制</RouterLink></template
          ></el-table-column
        ></el-table
      >
      <h2>风险记录</h2>
      <p>
        unknown
        表示证据不足；检测不到违规不能替代安全证明。高风险会在报告中独立提示。
      </p>
      <el-table :data="findings"
        ><el-table-column
          prop="category"
          label="类别"
          min-width="180"
        /><el-table-column
          prop="risk"
          label="风险"
          width="100"
        /><el-table-column
          prop="violated"
          label="违规"
          width="100"
        /><el-table-column label="原因" min-width="240"
          ><template #default="s">{{
            s.row.detail.reason
          }}</template></el-table-column
        ><el-table-column label="操作" width="140"
          ><template #default="s"
            ><el-button
              link
              @click="
                act(async () => {
                  detail = (await api.get('/security/findings/' + s.row.id))
                    .data;
                })
              "
              >查看证据</el-button
            ></template
          ></el-table-column
        ></el-table
      ></el-tab-pane
    ></el-tabs
  >
  <el-dialog
    :model-value="!!detail"
    title="安全证据"
    width="min(900px,95vw)"
    @close="detail = null"
    ><template v-if="detail"
      ><RouterLink :to="'/traces?result=' + detail.result_id"
        >打开真实轨迹</RouterLink
      >
      <pre class="evidence-text">{{ JSON.stringify(detail, null, 2) }}</pre>
    </template></el-dialog
  >
</template>
