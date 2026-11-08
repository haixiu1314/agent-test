<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  suites = ref<any[]>([]),
  items = ref<any[]>([]),
  project = ref(""),
  suite = ref(""),
  error = ref(""),
  busy = ref(false),
  total = ref(0),
  page = ref(1);
const dialog = ref(false),
  editing = ref<any>(null),
  form = ref<any>({}),
  advanced = ref(""),
  importDialog = ref(false),
  importContent = ref(""),
  format = ref("json"),
  versions = ref<any[]>([]),
  versionDialog = ref(false);
const types = [
  ["functional", "功能"],
  ["boundary", "边界"],
  ["planning", "规划"],
  ["memory", "记忆"],
  ["tool", "工具"],
  ["rag", "RAG"],
  ["security", "安全"],
  ["exception", "异常"],
];
const selectedSuite = () => suites.value.find((s) => s.id === suite.value);
async function readImport(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (file.size > 800000) {
    ElMessage.error("导入文件不能超过 800 KB");
    return;
  }
  try {
    importContent.value = await file.text();
    format.value = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
  } catch (e) {
    ElMessage.error(message(e));
  }
}
async function loadSuites() {
  try {
    suites.value = (
      await api.get("/suites", { params: { project_id: project.value } })
    ).data.items;
    if (!suites.value.some((s) => s.id === suite.value))
      suite.value = suites.value[0]?.id || "";
    await load();
  } catch (e) {
    error.value = message(e);
  }
}
async function load() {
  error.value = "";
  items.value = [];
  total.value = 0;
  if (!suite.value) return;
  busy.value = true;
  try {
    const d = (
      await api.get("/cases", {
        params: { suite_id: suite.value, page: page.value },
      })
    ).data;
    items.value = d.items;
    total.value = d.total;
    if (!d.items.length && d.total > 0 && page.value > 1) {
      page.value--;
      await load();
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function createSuite() {
  try {
    const { value } = await ElMessageBox.prompt(
      "为一组测试用例命名",
      "创建测试套件",
      { inputValidator: (v) => !!v?.trim() || "请输入名称" },
    );
    await api.post("/suites", { project_id: project.value, name: value });
    await loadSuites();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
async function renameSuite() {
  try {
    const s = selectedSuite();
    const { value } = await ElMessageBox.prompt("套件名称", "编辑测试套件", {
      inputValue: s.name,
      inputValidator: (v) => !!v?.trim() || "请输入名称",
    });
    await api.put(`/suites/${s.id}`, {
      project_id: project.value,
      name: value,
      description: s.description,
      expected_revision: s.revision,
    });
    await loadSuites();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
async function removeSuite() {
  try {
    const s = selectedSuite();
    await ElMessageBox.confirm(
      "将删除套件及全部用例和套件快照，确认继续？",
      "删除测试套件",
    );
    await api.delete(`/suites/${s.id}`, {
      params: { expected_revision: s.revision },
    });
    await loadSuites();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
function open(item?: any) {
  editing.value = item || null;
  form.value = item
    ? { ...item }
    : {
        name: "",
        test_type: "functional",
        scenario: "",
        preconditions: "",
        user_input: "",
        expected_behavior: "",
        expected_result: "",
        priority: "P1",
      };
  advanced.value = JSON.stringify(
    item
      ? { history: item.history, rules: item.rules, tags: item.tags }
      : {
          history: [],
          rules: {
            evaluators: ["rules"],
            rubric: "按预期结果逐项核对",
            must_include: [],
            must_not_include: [],
          },
          tags: [],
        },
    null,
    2,
  );
  dialog.value = true;
}
async function save() {
  busy.value = true;
  try {
    const {
      name,
      test_type,
      scenario,
      preconditions,
      user_input,
      expected_behavior,
      expected_result,
      priority,
    } = form.value;
    const payload = {
      name,
      test_type,
      scenario,
      preconditions,
      user_input,
      expected_behavior,
      expected_result,
      priority,
      ...JSON.parse(advanced.value),
    };
    if (editing.value)
      await api.put(`/cases/${editing.value.id}`, {
        ...payload,
        expected_revision: editing.value.revision,
      });
    else
      await api.post(
        "/cases",
        { ...payload, suite_id: suite.value },
        { params: { expected_revision: selectedSuite().revision } },
      );
    dialog.value = false;
    await loadSuites();
    ElMessage.success("用例已保存");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    busy.value = false;
  }
}
async function remove(item: any) {
  try {
    await ElMessageBox.confirm(`删除用例“${item.name}”？`, "删除用例");
    await api.delete(`/cases/${item.id}`, {
      params: { expected_revision: item.revision },
    });
    await loadSuites();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
async function exportFile() {
  try {
    const d = (
      await api.get(`/suites/${suite.value}/export`, {
        params: { format: format.value },
      })
    ).data;
    const u = URL.createObjectURL(
      new Blob([d.content], { type: "text/plain;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = u;
    a.download = `test-cases.${format.value}`;
    a.click();
    URL.revokeObjectURL(u);
  } catch (e) {
    ElMessage.error(message(e));
  }
}
async function importFile() {
  busy.value = true;
  try {
    await api.post(`/suites/${suite.value}/import`, {
      format: format.value,
      content: importContent.value,
      expected_revision: selectedSuite().revision,
    });
    importDialog.value = false;
    await loadSuites();
    ElMessage.success("整批导入成功");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    busy.value = false;
  }
}
async function showVersions() {
  try {
    versions.value = (
      await api.get(`/suites/${suite.value}/versions`)
    ).data.items;
    versionDialog.value = true;
  } catch (e) {
    ElMessage.error(message(e));
  }
}
onMounted(async () => {
  try {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    project.value = projects.value[0]?.id || "";
    if (project.value) await loadSuites();
  } catch (e) {
    error.value = message(e);
  }
});
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>测试用例</h1>
      <p>将输入、预期行为和判定依据保存在同一份用例中。</p>
    </div>
    <el-button type="primary" :disabled="!suite" @click="open()"
      >新增用例</el-button
    >
  </div>
  <section class="list-section">
    <div class="case-toolbar">
      <label
        >测试项目
        <el-select
          v-model="project"
          aria-label="测试项目"
          @change="
            suite = '';
            page = 1;
            loadSuites();
          "
          ><el-option
            v-for="p in projects"
            :key="p.id"
            :label="p.name"
            :value="p.id" /></el-select></label
      ><label
        >测试套件
        <el-select
          v-model="suite"
          aria-label="测试套件"
          @change="
            page = 1;
            load();
          "
          ><el-option
            v-for="s in suites"
            :key="s.id"
            :label="`${s.name} · v${s.revision}`"
            :value="s.id" /></el-select></label
      ><el-button :disabled="!project" @click="createSuite">创建套件</el-button
      ><el-button :disabled="!suite" @click="renameSuite">编辑套件</el-button
      ><el-button :disabled="!suite" @click="removeSuite">删除套件</el-button>
    </div>
    <div class="section-toolbar">
      <h2>
        用例列表 <span class="muted">{{ total }} 条</span>
      </h2>
      <div class="row-actions">
        <button :disabled="!suite" @click="showVersions">版本记录</button
        ><button :disabled="!suite" @click="importDialog = true">
          导入 / 导出</button
        ><button @click="loadSuites">刷新</button>
      </div>
    </div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <div v-loading="busy">
      <p v-if="!items.length" class="empty">
        {{
          suite
            ? "还没有用例。新增一条，或导入已有的 JSON / CSV 文件。"
            : "请先选择项目并创建测试套件。"
        }}
      </p>
      <article v-for="c in items" :key="c.id" class="project-row">
        <div>
          <h3>{{ c.name }}</h3>
          <p>{{ c.scenario }}</p>
          <small
            >{{ types.find((t) => t[0] === c.test_type)?.[1] }} ·
            {{ c.priority }} ·
            {{
              c.source === "ai"
                ? "AI 生成后审阅"
                : c.source === "import"
                  ? "文件导入"
                  : "人工编写"
            }}
            · v{{ c.revision }}</small
          >
        </div>
        <div class="row-actions">
          <button @click="open(c)">编辑</button
          ><button @click="remove(c)">删除</button>
        </div>
      </article>
    </div>
    <el-pagination
      v-if="total > 20"
      v-model:current-page="page"
      :total="total"
      :page-size="20"
      layout="prev,pager,next"
      @current-change="load"
    />
  </section>
  <el-dialog
    v-model="dialog"
    :title="editing ? '编辑用例' : '新增用例'"
    width="760px"
    ><form @submit.prevent="save">
      <label for="case-name">用例名称</label
      ><el-input id="case-name" v-model="form.name" required maxlength="160" />
      <div class="case-toolbar">
        <label
          >测试类型
          <el-select v-model="form.test_type" aria-label="测试类型"
            ><el-option
              v-for="t in types"
              :key="t[0]"
              :value="t[0]"
              :label="t[1]" /></el-select></label
        ><label
          >优先级
          <el-select v-model="form.priority" aria-label="优先级"
            ><el-option
              v-for="p in ['P0', 'P1', 'P2', 'P3']"
              :key="p"
              :value="p" /></el-select
        ></label>
      </div>
      <label for="case-scenario">测试场景</label
      ><el-input
        id="case-scenario"
        v-model="form.scenario"
        required
        type="textarea"
      /><label for="case-preconditions">前置条件</label
      ><el-input id="case-preconditions" v-model="form.preconditions" /><label
        for="case-input"
        >用户输入（边界测试可留空）</label
      ><el-input
        id="case-input"
        v-model="form.user_input"
        type="textarea"
      /><label for="case-behavior">预期行为</label
      ><el-input
        id="case-behavior"
        v-model="form.expected_behavior"
        required
        type="textarea"
      /><label for="case-result">预期结果</label
      ><el-input
        id="case-result"
        v-model="form.expected_result"
        required
        type="textarea"
      /><label for="case-rules">判定规则、历史对话与标签（JSON）</label>
      <p class="muted">
        工具用例需工具轨迹与结果依据；记忆用例需历史对话；安全用例需安全策略与语义判断。详见操作文档。
      </p>
      <el-input id="case-rules" v-model="advanced" type="textarea" :rows="10" />
      <div class="form-actions">
        <el-button @click="dialog = false">取消</el-button
        ><el-button type="primary" native-type="submit" :loading="busy"
          >保存用例</el-button
        >
      </div>
    </form></el-dialog
  >
  <el-dialog v-model="importDialog" title="用例导入与导出" width="720px"
    ><label
      >文件格式
      <el-select v-model="format" aria-label="文件格式"
        ><el-option value="json" label="JSON" /><el-option
          value="csv"
          label="CSV（单元格为 JSON 编码）" /></el-select
    ></label>
    <p>先导出已有用例作为模板。每批可导入 1–100 条，全部有效后才保存。</p>
    <label for="import-file">选择 JSON / CSV 文件</label>
    <input
      id="import-file"
      type="file"
      accept=".json,.csv"
      @change="readImport"
    />
    <label for="import-content">文件内容</label
    ><el-input
      id="import-content"
      v-model="importContent"
      type="textarea"
      :rows="12"
    />
    <div class="form-actions">
      <el-button @click="exportFile">导出当前套件</el-button
      ><el-button type="primary" :loading="busy" @click="importFile"
        >校验并导入</el-button
      >
    </div></el-dialog
  >
  <el-dialog v-model="versionDialog" title="套件版本记录" width="760px"
    ><article v-for="v in versions" :key="v.revision">
      <h3>版本 {{ v.revision }} · {{ v.snapshot.cases.length }} 条用例</h3>
      <details>
        <summary>查看不可变快照</summary>
        <pre class="json-view">{{ JSON.stringify(v.snapshot, null, 2) }}</pre>
      </details>
    </article></el-dialog
  >
</template>
