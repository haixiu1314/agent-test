<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  suites = ref<any[]>([]),
  models = ref<any[]>([]),
  runs = ref<any[]>([]),
  project = ref(""),
  suite = ref(""),
  model = ref("__environment__"),
  requirements = ref(""),
  systemPrompt = ref(""),
  interfaceInfo = ref(""),
  tools = ref("[]"),
  types = ref(["functional", "boundary"]),
  count = ref(8),
  busy = ref(false),
  error = ref(""),
  current = ref<any>(null),
  drafts = ref<any[]>([]),
  environmentReady = ref(false);
const typeOptions = [
  ["functional", "功能"],
  ["boundary", "边界"],
  ["planning", "规划"],
  ["memory", "记忆"],
  ["tool", "工具"],
  ["rag", "RAG"],
  ["security", "安全"],
  ["exception", "异常"],
];
async function readPrompt(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (file.size > 80000) {
    ElMessage.error("提示词文件不能超过 80 KB");
    return;
  }
  try {
    const text = await file.text();
    if (text.length > 20000) throw new Error("提示词最多 20000 字符");
    systemPrompt.value = text;
  } catch (e) {
    ElMessage.error(message(e));
  }
}
function review(run: any) {
  current.value = run;
  drafts.value = (run.result?.cases || []).map((c: any, i: number) => ({
    index: i,
    selected: !run.saved_indexes.includes(i),
    text: JSON.stringify(c, null, 2),
  }));
}
async function load() {
  error.value = "";
  try {
    suites.value = (
      await api.get("/suites", { params: { project_id: project.value } })
    ).data.items;
    suite.value = suites.value[0]?.id || "";
    runs.value = (
      await api.get("/generation-runs", {
        params: { project_id: project.value },
      })
    ).data.items;
    current.value = null;
    drafts.value = [];
  } catch (e) {
    error.value = message(e);
  }
}
async function generate() {
  busy.value = true;
  error.value = "";
  try {
    const r = (
      await api.post("/generation-runs", {
        project_id: project.value,
        model_config_id: model.value === "__environment__" ? null : model.value,
        requirements: requirements.value,
        system_prompt: systemPrompt.value,
        interface_info: interfaceInfo.value,
        tools: JSON.parse(tools.value),
        types: types.value,
        count: count.value,
      })
    ).data;
    runs.value.unshift(r);
    review(r);
    if (r.status === "failed")
      error.value = `生成失败：${r.error_code}。请检查模型配置或生成记录。`;
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function save() {
  busy.value = true;
  try {
    const chosen = drafts.value.filter((d) => d.selected);
    const s = suites.value.find((s) => s.id === suite.value);
    await api.post(`/generation-runs/${current.value.id}/save`, {
      suite_id: suite.value,
      expected_revision: s.revision,
      indexes: chosen.map((d) => d.index),
      cases: chosen.map((d) => JSON.parse(d.text)),
    });
    const id = current.value.id;
    await load();
    review(runs.value.find((r) => r.id === id));
    ElMessage.success("审阅用例已入库");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  try {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    const d = (await api.get("/models")).data;
    models.value = d.items.filter((m: any) => m.purpose === "generation");
    environmentReady.value = d.environment_ready;
    project.value = projects.value[0]?.id || "";
    if (project.value) await load();
  } catch (e) {
    error.value = message(e);
  }
});
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>AI 生成用例</h1>
      <p>提供业务需求，审阅模型生成的草稿，再选择保存。</p>
    </div>
  </div>
  <div class="content-grid">
    <section class="list-section">
      <h2>生成要求</h2>
      <form @submit.prevent="generate">
        <label
          >测试项目
          <el-select v-model="project" aria-label="测试项目" @change="load"
            ><el-option
              v-for="p in projects"
              :key="p.id"
              :value="p.id"
              :label="p.name" /></el-select></label
        ><label
          >生成模型
          <el-select v-model="model" aria-label="生成模型"
            ><el-option
              value="__environment__"
              :label="
                environmentReady ? '本地环境模型' : '本地环境模型（未配置）'
              " /><el-option
              v-for="m in models"
              :key="m.id"
              :value="m.id"
              :label="m.name" /></el-select
        ></label>
        <p v-if="!environmentReady && !models.length" class="inline-error">
          请先在“模型配置”添加并测试你的模型，再返回选择生成模型。
        </p>
        <label for="generation-requirements">业务需求</label
        ><el-input
          id="generation-requirements"
          v-model="requirements"
          type="textarea"
          :rows="5"
          required
          minlength="5"
          maxlength="10000"
        /><label>覆盖类型</label
        ><el-checkbox-group v-model="types"
          ><el-checkbox v-for="t in typeOptions" :key="t[0]" :value="t[0]">{{
            t[1]
          }}</el-checkbox></el-checkbox-group
        ><label
          >用例数量
          <el-input-number
            v-model="count"
            :min="Math.max(types.length, 1)"
            :max="30"
            aria-label="用例数量"
        /></label>
        <details>
          <summary>待测 Agent 的提示词、工具与接口</summary>
          <label for="prompt-file">从 TXT / Markdown 文件读取提示词</label>
          <input
            id="prompt-file"
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            @change="readPrompt"
          />
          <label for="generation-system">系统提示词（作为待测数据）</label
          ><el-input
            id="generation-system"
            v-model="systemPrompt"
            type="textarea"
            :rows="3"
          /><label for="generation-tools">工具描述（JSON 数组）</label
          ><el-input
            id="generation-tools"
            v-model="tools"
            type="textarea"
            :rows="3"
          /><label for="generation-interface">接口说明</label
          ><el-input
            id="generation-interface"
            v-model="interfaceInfo"
            type="textarea"
            :rows="3"
          />
        </details>
        <div class="form-actions">
          <el-button
            type="primary"
            native-type="submit"
            :disabled="!project || !types.length"
            :loading="busy"
            >调用模型生成草稿</el-button
          >
        </div>
      </form>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    </section>
    <section class="guide">
      <h2>生成记录</h2>
      <p v-if="!runs.length">本项目还没有生成记录。</p>
      <article v-for="r in runs" :key="r.id" class="generation-record">
        <button class="name-link" @click="review(r)">
          {{ r.request_data.requirements.slice(0, 45) }}
        </button>
        <p>
          {{
            r.status === "review"
              ? "待审阅"
              : r.status === "saved"
                ? "已保存部分或全部"
                : r.status === "failed"
                  ? "生成失败"
                  : "生成中"
          }}
          · {{ r.error_code || r.model_snapshot.model || "尚未调用模型" }}
        </p>
      </article>
      <p class="guide-note">生成完成后请核查用例内容，确认后保存到测试套件。</p>
    </section>
  </div>
  <section v-if="current" class="list-section review-section">
    <h2>草稿审阅</h2>
    <p v-if="!drafts.length">
      {{ current.error_code || "当前没有可审阅草稿" }}
    </p>
    <template v-else
      ><p>{{ current.result.capability_analysis }}</p>
      <ul>
        <li v-for="risk in current.result.risks" :key="risk">{{ risk }}</li>
      </ul>
      <p>展开草稿可修改完整字段。已入库的草稿不能重复保存。</p>
      <article v-for="d in drafts" :key="d.index">
        <el-checkbox
          v-model="d.selected"
          :disabled="current.saved_indexes.includes(d.index)"
          >{{ current.result.cases[d.index].name
          }}{{
            current.saved_indexes.includes(d.index) ? "（已入库）" : ""
          }}</el-checkbox
        >
        <details>
          <summary>查看与编辑草稿</summary>
          <el-input
            v-model="d.text"
            type="textarea"
            :rows="14"
            :disabled="current.saved_indexes.includes(d.index)"
          />
        </details>
      </article>
      <div class="case-toolbar">
        <label
          >保存到套件
          <el-select v-model="suite" aria-label="保存到套件"
            ><el-option
              v-for="s in suites"
              :key="s.id"
              :label="s.name"
              :value="s.id" /></el-select></label
        ><el-button
          type="primary"
          :disabled="!suite || !drafts.some((d) => d.selected)"
          :loading="busy"
          @click="save"
          >保存选中的审阅用例</el-button
        >
      </div></template
    >
  </section>
</template>
