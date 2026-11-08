<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { ElMessage } from "element-plus";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  agents = ref<any[]>([]),
  suites = ref<any[]>([]),
  tasks = ref<any[]>([]),
  cases = ref<any[]>([]);
const project = ref(""),
  error = ref(""),
  busy = ref(false),
  selected = ref<any>(null),
  results = ref<any[]>([]),
  detail = ref<any>(null);
const page = ref(1),
  total = ref(0),
  resultPage = ref(1),
  resultTotal = ref(0),
  dialog = ref(false),
  versions = ref<any[]>([]),
  revisions = ref<any[]>([]);
const form = ref<any>({}),
  models = ref<any[]>([]),
  knowledgeBases = ref<any[]>([]),
  creating = ref(false);
const labels: Record<string, string> = {
  pending: "待执行",
  running: "运行中",
  pause_requested: "暂停中",
  paused: "已暂停",
  cancel_requested: "终止中",
  cancelled: "已取消",
  completed: "已完成",
  interrupted: "已中断",
  passed: "通过",
  failed: "失败",
  error: "异常",
  inconclusive: "待判定",
  unavailable: "不可用",
};
const label = (s: string) => labels[s] || s;
const active = (s: string) =>
  ["running", "pause_requested", "cancel_requested"].includes(s);
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false;
async function load() {
  if (!project.value) return;
  const data = (
    await api.get("/test-tasks", {
      params: { project_id: project.value, page: page.value },
    })
  ).data;
  tasks.value = data.items;
  total.value = data.total;
}
async function changeProject() {
  selected.value = null;
  results.value = [];
  page.value = 1;
  error.value = "";
  busy.value = true;
  try {
    const [a, s] = await Promise.all([
      api.get("/agents", {
        params: { project_id: project.value, page_size: 100 },
      }),
      api.get("/suites", {
        params: { project_id: project.value, page_size: 100 },
      }),
    ]);
    agents.value = a.data.items;
    suites.value = s.data.items;
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function openCreate() {
  form.value = {
    name: "质量测试任务",
    agent_id: agents.value[0]?.id || "",
    suite_id: suites.value[0]?.id || "",
    concurrency: 2,
    timeout_seconds: 60,
    retries: 0,
    case_ids: [],
  };
  dialog.value = true;
  error.value = "";
  try {
    models.value = (await api.get("/models")).data.items;
    knowledgeBases.value = (
      await api.get("/rag/knowledge-bases", {
        params: { project_id: project.value },
      })
    ).data.items;
  } catch {
    models.value = [];
  }
  await Promise.all([agentVersions(), suiteVersions()]);
}
async function agentVersions() {
  versions.value = [];
  form.value.agent_version = undefined;
  if (!form.value.agent_id) return;
  try {
    versions.value = (
      await api.get(`/agents/${form.value.agent_id}/versions`)
    ).data.items;
    form.value.agent_version = versions.value[0]?.version;
  } catch (e) {
    error.value = message(e);
  }
}
async function suiteVersions() {
  revisions.value = [];
  form.value.suite_revision = undefined;
  cases.value = [];
  form.value.case_ids = [];
  if (!form.value.suite_id) return;
  try {
    revisions.value = (
      await api.get(`/suites/${form.value.suite_id}/versions`)
    ).data.items;
    form.value.suite_revision = revisions.value[0]?.revision;
    selectRevision();
  } catch (e) {
    error.value = message(e);
  }
}
function selectRevision() {
  cases.value =
    revisions.value.find((v) => v.revision === form.value.suite_revision)
      ?.snapshot.cases || [];
  form.value.case_ids = [];
}
async function create() {
  creating.value = true;
  try {
    const d = (await api.post("/test-tasks", form.value)).data;
    dialog.value = false;
    await load();
    await inspect(d);
    ElMessage.success("任务已创建，点击开始执行");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    creating.value = false;
  }
}
async function inspect(task: any) {
  selected.value = task;
  resultPage.value = 1;
  await refreshDetail();
}
async function refreshDetail() {
  if (!selected.value) return;
  const id = selected.value.id;
  const [t, r] = await Promise.all([
    api.get(`/test-tasks/${id}/progress`),
    api.get(`/test-tasks/${id}/results`, {
      params: { page: resultPage.value },
    }),
  ]);
  if (selected.value?.id !== id) return;
  selected.value = t.data;
  results.value = r.data.items;
  resultTotal.value = r.data.total;
}
async function action(task: any, name: string) {
  busy.value = true;
  try {
    const r = await api.post(`/test-tasks/${task.id}/${name}`);
    await load();
    if (name === "retry-failed") await inspect(r.data);
    else if (selected.value?.id === task.id) await refreshDetail();
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    busy.value = false;
  }
}
async function poll() {
  try {
    if (
      tasks.value.some((t) => active(t.status)) ||
      active(selected.value?.status)
    ) {
      await load();
      await refreshDetail();
    }
  } catch (e) {
    error.value = message(e);
  }
  if (!disposed) timer = setTimeout(poll, 1500);
}
onMounted(async () => {
  try {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    project.value = projects.value[0]?.id || "";
    await changeProject();
  } catch (e) {
    error.value = message(e);
  } finally {
    poll();
  }
});
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(timer);
});
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>测试执行</h1>
      <p class="muted">
        固定 Agent 与用例版本，逐条保存回答、判定依据和执行证据。
      </p>
    </div>
    <el-button
      type="primary"
      :disabled="!agents.length || !suites.length"
      @click="openCreate"
      >创建任务</el-button
    >
  </div>
  <div class="case-toolbar">
    <label
      >测试项目<el-select
        v-model="project"
        aria-label="测试项目"
        @change="changeProject"
        ><el-option
          v-for="p in projects"
          :key="p.id"
          :label="p.name"
          :value="p.id" /></el-select></label
    ><el-button
      :loading="busy"
      @click="load().catch((e) => (error = message(e)))"
      >刷新任务</el-button
    >
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-empty v-if="!projects.length" description="请先创建测试项目" />
  <p v-else-if="!agents.length || !suites.length" class="muted">
    请先接入 Agent，并创建包含用例的测试套件。
  </p>
  <div class="task-table">
    <el-table
      :data="tasks"
      v-loading="busy"
      empty-text="还没有测试任务，创建任务后即可执行"
      row-key="id"
    >
      <el-table-column label="任务 / 版本" min-width="210"
        ><template #default="{ row }"
          ><button
            class="task-name"
            @click="inspect(row).catch((e) => (error = message(e)))"
          >
            {{ row.name }}
          </button>
          <div class="muted">
            Agent v{{ row.agent_version }} · 套件 r{{ row.suite_revision }}
          </div></template
        ></el-table-column
      >
      <el-table-column label="执行状态" min-width="110"
        ><template #default="{ row }">{{
          label(row.status)
        }}</template></el-table-column
      >
      <el-table-column label="进度" width="100" align="right"
        ><template #default="{ row }"
          >{{ row.completed }} / {{ row.total }}</template
        ></el-table-column
      >
      <el-table-column label="操作" min-width="255"
        ><template #default="{ row }">
          <el-button
            v-if="['pending', 'paused', 'interrupted'].includes(row.status)"
            link
            type="primary"
            :disabled="busy"
            @click="action(row, 'start')"
            >{{ row.status === "pending" ? "开始" : "继续" }}</el-button
          >
          <el-button
            v-if="row.status === 'running'"
            link
            :disabled="busy"
            @click="action(row, 'pause')"
            >暂停</el-button
          >
          <el-button
            v-if="
              [
                'pending',
                'running',
                'pause_requested',
                'paused',
                'interrupted',
              ].includes(row.status)
            "
            link
            type="danger"
            :disabled="busy"
            @click="action(row, 'cancel')"
            >取消</el-button
          >
          <el-button
            v-if="
              ['completed', 'cancelled', 'error', 'interrupted'].includes(
                row.status,
              )
            "
            link
            :disabled="busy"
            @click="action(row, 'retry-failed')"
            >重跑未通过</el-button
          >
          <el-button
            link
            @click="inspect(row).catch((e) => (error = message(e)))"
            >查看结果</el-button
          >
        </template></el-table-column
      >
    </el-table>
  </div>
  <el-pagination
    v-if="total > 20"
    v-model:current-page="page"
    :total="total"
    :page-size="20"
    layout="prev,pager,next"
    @current-change="load"
  />
  <section v-if="selected" class="review-section" aria-label="任务结果">
    <h2>{{ selected.name }} · {{ label(selected.status) }}</h2>
    <p>
      已结束 {{ selected.completed }} / {{ selected.total }} · 通过
      {{ selected.counts.passed }} · 失败 {{ selected.counts.failed }} · 异常
      {{ selected.counts.error }} · 待判定 {{ selected.counts.inconclusive }} ·
      已取消 {{ selected.counts.cancelled }}
    </p>
    <el-progress
      :percentage="
        selected.total
          ? Math.round((selected.completed / selected.total) * 100)
          : 0
      "
      :show-text="false"
    />
    <p class="muted">
      暂停和取消会等待当前调用结束。缺少模型或执行证据时标记待判定；Token
      未提供时显示“—”。进度每 1.5 秒自动刷新。
    </p>
    <p v-if="selected.error_code">错误码：{{ selected.error_code }}</p>
    <div class="task-table">
      <el-table :data="results" empty-text="没有结果">
        <el-table-column prop="case_name" label="测试用例" min-width="180" />
        <el-table-column label="判定" width="95"
          ><template #default="{ row }">{{
            label(row.status)
          }}</template></el-table-column
        >
        <el-table-column label="响应时间 ms" width="140" align="right"
          ><template #default="{ row }">{{
            row.duration_ms?.toFixed(1) ?? "—"
          }}</template></el-table-column
        >
        <el-table-column
          prop="attempts"
          label="调用次数"
          width="100"
          align="right"
        />
        <el-table-column label="Token" width="100" align="right"
          ><template #default="{ row }">{{
            row.usage?.total_tokens ?? "—"
          }}</template></el-table-column
        >
        <el-table-column label="依据" width="110"
          ><template #default="{ row }"
            ><el-button link type="primary" @click="detail = row"
              >结果详情</el-button
            ></template
          ></el-table-column
        >
      </el-table>
    </div>
    <p class="mobile-table-hint muted">
      表格可左右滑动，查看响应时间、调用次数和结果详情。
    </p>
    <el-pagination
      v-if="resultTotal > 20"
      v-model:current-page="resultPage"
      :total="resultTotal"
      :page-size="20"
      layout="prev,pager,next"
      @current-change="refreshDetail"
    />
  </section>
  <el-dialog v-model="dialog" title="创建测试任务" width="720px">
    <el-form label-position="top">
      <el-form-item label="任务名称"
        ><el-input v-model="form.name" aria-label="任务名称" maxlength="160"
      /></el-form-item>
      <el-form-item label="企业助手检索知识库"
        ><el-select
          v-model="form.knowledge_base_id"
          clearable
          aria-label="任务知识库"
          placeholder="未选则使用本地关键词样例"
          ><el-option
            v-for="k in knowledgeBases"
            :key="k.id"
            :value="k.id"
            :label="k.name" /></el-select
      ></el-form-item>
      <el-form-item label="演示缺陷"
        ><el-select
          v-model="form.demo_defect"
          clearable
          aria-label="任务演示缺陷"
          ><el-option
            v-for="d in [
              'none',
              'wrong_tool_description',
              'missing_knowledge',
              'conflicting_knowledge',
              'bad_prompt',
              'tool_timeout',
            ]"
            :key="d"
            :value="d"
            :label="d" /></el-select
      ></el-form-item>
      <div class="task-form-grid">
        <el-form-item label="待测 Agent"
          ><el-select
            v-model="form.agent_id"
            aria-label="待测 Agent"
            @change="agentVersions"
            ><el-option
              v-for="a in agents"
              :key="a.id"
              :value="a.id"
              :label="a.name" /></el-select
        ></el-form-item>
        <el-form-item label="Agent 版本"
          ><el-select v-model="form.agent_version" aria-label="Agent 版本"
            ><el-option
              v-for="v in versions"
              :key="v.version"
              :value="v.version"
              :label="`版本 ${v.version}`" /></el-select
        ></el-form-item>
        <el-form-item label="测试套件"
          ><el-select
            v-model="form.suite_id"
            aria-label="测试套件"
            @change="suiteVersions"
            ><el-option
              v-for="s in suites"
              :key="s.id"
              :value="s.id"
              :label="s.name" /></el-select
        ></el-form-item>
        <el-form-item label="套件版本"
          ><el-select
            v-model="form.suite_revision"
            aria-label="套件版本"
            @change="selectRevision"
            ><el-option
              v-for="v in revisions"
              :key="v.revision"
              :value="v.revision"
              :label="`修订 ${v.revision}`" /></el-select
        ></el-form-item>
      </div>
      <el-form-item label="执行用例（留空执行所选版本全部用例）"
        ><el-select v-model="form.case_ids" multiple aria-label="执行用例"
          ><el-option
            v-for="c in cases"
            :key="c.id"
            :value="c.id"
            :label="c.name" /></el-select
      ></el-form-item>
      <div class="task-form-grid">
        <el-form-item label="并发数量"
          ><el-input-number
            v-model="form.concurrency"
            aria-label="并发数量"
            :min="1"
            :max="10"
        /></el-form-item>
        <el-form-item label="单次调用超时（秒）"
          ><el-input-number
            v-model="form.timeout_seconds"
            aria-label="单次调用超时"
            :min="1"
            :max="180"
        /></el-form-item>
        <el-form-item label="失败重试次数"
          ><el-input-number
            v-model="form.retries"
            aria-label="失败重试次数"
            :min="0"
            :max="3"
        /></el-form-item>
        <el-form-item label="语义 / DeepEval 评估模型"
          ><el-select
            v-model="form.judge_model_id"
            clearable
            aria-label="评估模型"
            placeholder="使用本地默认配置"
            ><el-option
              v-for="m in models.filter((m) => m.purpose === 'judge')"
              :key="m.id"
              :value="m.id"
              :label="m.name" /></el-select
        ></el-form-item>
        <el-form-item label="企业演示 Agent 模型"
          ><el-select
            v-model="form.demo_model_id"
            clearable
            aria-label="演示模型"
            placeholder="使用本地默认配置"
            ><el-option
              v-for="m in models.filter((m) => m.purpose === 'demo')"
              :key="m.id"
              :value="m.id"
              :label="m.name" /></el-select
        ></el-form-item>
      </div>
      <p class="muted">
        最多同时运行三个任务。创建后配置和用例内容固定，后续编辑不会改变历史任务。协议回显适配器仅用于验证平台流程。
      </p>
    </el-form>
    <template #footer
      ><el-button @click="dialog = false">返回</el-button
      ><el-button
        type="primary"
        :loading="creating"
        :disabled="!cases.length || !form.agent_id || !form.name.trim()"
        @click="create"
        >保存任务</el-button
      ></template
    >
  </el-dialog>
  <el-dialog
    :model-value="!!detail"
    title="用例执行结果"
    width="760px"
    @close="detail = null"
  >
    <template v-if="detail"
      ><h2>{{ detail.case_name }} · {{ label(detail.status) }}</h2>
      <p v-if="detail.error_code">错误码：{{ detail.error_code }}</p>
      <h3>输入与期望</h3>
      <pre class="json-view">{{ JSON.stringify(detail.case, null, 2) }}</pre>
      <h3>实际回答</h3>
      <pre class="json-view">{{ detail.output ?? "尚未收到回答" }}</pre>
      <h3>评估依据</h3>
      <article v-for="e in detail.evaluations" :key="e.evaluator">
        <strong>{{ e.evaluator }} · {{ label(e.status) }}</strong>
        <pre class="json-view">{{ JSON.stringify(e.detail, null, 2) }}</pre>
      </article>
      <p v-if="!detail.evaluations.length" class="muted">暂无评估记录。</p>
      <details>
        <summary>执行元数据</summary>
        <pre class="json-view">{{
          JSON.stringify(
            {
              attempts: detail.attempts,
              usage: detail.usage,
              events_observable: detail.events_observable,
              contexts: detail.contexts,
              tool_call_count: detail.tool_call_count,
            },
            null,
            2,
          )
        }}</pre>
      </details></template
    >
  </el-dialog>
</template>
<style scoped>
.page-heading {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
}
.task-name {
  border: 0;
  background: none;
  padding: 0;
  color: #294b9b;
  text-align: left;
  overflow-wrap: anywhere;
}
.task-table {
  overflow-x: auto;
  margin-top: 16px;
}
.task-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
}
.el-select {
  width: 100%;
}
.el-progress {
  margin-top: 16px;
}
h3 {
  margin-top: 18px;
}
article {
  padding-top: 12px;
}
.mobile-table-hint {
  display: none;
}
@media (max-width: 640px) {
  .mobile-table-hint {
    display: block;
  }
  .page-heading {
    flex-wrap: wrap;
  }
  .task-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
