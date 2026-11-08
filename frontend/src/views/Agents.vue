<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, message, type Agent, type Project, type Page } from "../api";
const route = useRoute(),
  items = ref<Agent[]>([]),
  projects = ref<Project[]>([]),
  total = ref(0),
  page = ref(1),
  projectId = ref(String(route.query.project_id || "")),
  busy = ref(false),
  error = ref(""),
  dialog = ref(false),
  editing = ref(""),
  saving = ref(false),
  connecting = ref(""),
  result = ref<Record<string, unknown> | null>(null),
  versionDialog = ref(false),
  versions = ref<{ version: number; snapshot: Agent }[]>([]),
  versionTotal = ref(0),
  versionPage = ref(1),
  versionAgent = ref(""),
  versionBusy = ref(false),
  versionError = ref("");
function initial() {
  return {
    project_id: projectId.value,
    name: "",
    kind: "http" as "http" | "python",
    endpoint: "",
    method: "POST" as "POST" | "GET",
    request_template: {},
    input_field: "input",
    output_field: "output",
    history_field: null as string | null,
    trace_field: null as string | null,
    usage_field: null as string | null,
    contexts_field: null as string | null,
    adapter_name: "protocol_echo",
    timeout_seconds: 15,
    retries: 0,
    auth_header: "Authorization",
    version_label: "初始配置",
    expected_version: undefined as number | undefined,
  };
}
const form = ref(initial()),
  template = ref("{}"),
  headers = ref(""),
  apiKey = ref(""),
  clearKey = ref(false),
  clearHeaders = ref(false);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const { data } = await api.get<Page<Agent>>("/agents", {
      params: { page: page.value, project_id: projectId.value || undefined },
    });
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function loadProjects() {
  let p = 1;
  projects.value = [];
  while (true) {
    const { data } = await api.get<Page<Project>>("/projects", {
      params: { page: p, page_size: 100 },
    });
    projects.value.push(...data.items);
    if (projects.value.length >= data.total) break;
    p++;
  }
}
function open(item?: Agent) {
  editing.value = item?.id || "";
  form.value = item
    ? { ...initial(), ...item, expected_version: item.version }
    : { ...initial() };
  template.value = JSON.stringify(item?.request_template || {}, null, 2);
  headers.value = "";
  apiKey.value = "";
  clearKey.value = false;
  clearHeaders.value = false;
  dialog.value = true;
}
function parseObject(text: string) {
  const value = JSON.parse(text);
  if (!value || Array.isArray(value) || typeof value !== "object")
    throw new Error("JSON 必须是对象");
  return value;
}
async function save() {
  saving.value = true;
  try {
    const f = form.value;
    const payload = {
      project_id: f.project_id,
      name: f.name,
      kind: f.kind,
      endpoint: f.endpoint,
      method: f.method,
      request_template: parseObject(template.value),
      input_field: f.input_field,
      output_field: f.output_field,
      history_field: f.history_field || null,
      trace_field: f.trace_field || null,
      usage_field: f.usage_field || null,
      contexts_field: f.contexts_field || null,
      adapter_name: f.adapter_name,
      timeout_seconds: f.timeout_seconds,
      retries: f.retries,
      auth_header: f.auth_header,
      version_label: f.version_label,
      ...(editing.value ? { expected_version: f.expected_version } : {}),
      ...(apiKey.value || clearKey.value ? { api_key: apiKey.value } : {}),
      ...(headers.value.trim()
        ? { headers: parseObject(headers.value) }
        : clearHeaders.value
          ? { headers: {} }
          : {}),
    };
    if (editing.value) await api.put(`/agents/${editing.value}`, payload);
    else await api.post("/agents", payload);
    dialog.value = false;
    await load();
    ElMessage.success("Agent 配置与版本已保存");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    saving.value = false;
  }
}
async function remove(item: Agent) {
  try {
    await ElMessageBox.confirm(
      `删除“${item.name}”及其配置版本？`,
      "删除 Agent",
      { confirmButtonText: "确认删除", cancelButtonText: "取消" },
    );
    await api.delete(`/agents/${item.id}`);
    if (items.value.length === 1 && page.value > 1) page.value--;
    await load();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(message(e));
  }
}
async function connect(item: Agent) {
  connecting.value = item.id;
  result.value = null;
  try {
    result.value = {
      name: item.name,
      ...(
        await api.post(`/agents/${item.id}/test-connection`, {
          input: "连接验证",
          history: [],
        })
      ).data,
    };
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    connecting.value = "";
  }
}
async function showVersions(item?: Agent) {
  if (item) {
    versionAgent.value = item.id;
    versionPage.value = 1;
  }
  versionDialog.value = true;
  versionBusy.value = true;
  versionError.value = "";
  try {
    const { data } = await api.get(`/agents/${versionAgent.value}/versions`, {
      params: { page: versionPage.value },
    });
    versions.value = data.items;
    versionTotal.value = data.total;
  } catch (e) {
    versionError.value = message(e);
  } finally {
    versionBusy.value = false;
  }
}
onMounted(async () => {
  await load();
  try {
    await loadProjects();
  } catch (e) {
    error.value = message(e);
  }
});
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>Agent 接入</h1>
      <p>统一连接不同接口，保留每次配置变更。</p>
    </div>
    <el-button type="primary" @click="open()">接入 Agent</el-button>
  </div>
  <section>
    <div class="section-toolbar">
      <div class="filter">
        <label for="project-filter">所属项目</label
        ><el-select
          id="project-filter"
          v-model="projectId"
          placeholder="全部项目"
          clearable
          @change="
            page = 1;
            load();
          "
          ><el-option
            v-for="p in projects"
            :key="p.id"
            :label="p.name"
            :value="p.id"
        /></el-select>
      </div>
      <span class="muted">{{ total }} 个 Agent</span
      ><el-button @click="load" :loading="busy">刷新</el-button>
    </div>
    <p v-if="error" class="inline-error" role="alert">
      {{ error }} <button @click="load">重试</button>
    </p>
    <div v-loading="busy">
      <div v-if="!busy && !error && !items.length" class="empty">
        <h2>接入你的第一个 Agent</h2>
        <p>
          先创建项目，再配置真实 HTTP 地址，或选择受控协议适配器进行连接验证。
        </p>
        <el-button @click="open()">配置 Agent</el-button>
      </div>
      <article v-for="a in items" :key="a.id" class="agent-row">
        <div>
          <h2>
            {{ a.name }} <span class="version">v{{ a.version }}</span>
          </h2>
          <p>
            {{
              a.kind === "http"
                ? a.endpoint
                : "受控 Python · 协议回声适配器（非 AI）"
            }}
          </p>
          <small
            >{{
              a.kind === "http"
                ? `${a.method} · ${a.input_field} → ${a.output_field}`
                : a.adapter_name === "enterprise_demo"
                  ? "企业助手 · 需要真实模型"
                  : "仅验证平台接入协议"
            }}
            · 超时 {{ a.timeout_seconds }} 秒 ·
            {{ a.has_api_key ? "已配置密钥" : "未配置密钥" }}</small
          >
        </div>
        <div class="row-actions">
          <button @click="connect(a)" :disabled="!!connecting">
            {{ connecting === a.id ? "验证中…" : "测试连接" }}</button
          ><button @click="open(a)">编辑</button
          ><button @click="showVersions(a)">版本</button
          ><button @click="remove(a)">删除</button>
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
  <section v-if="result" class="connection-result" aria-live="polite">
    <h2>{{ result.name }} · {{ result.success ? "连接成功" : "连接失败" }}</h2>
    <p>
      {{
        result.success
          ? "已收到符合输出字段映射的文本响应。"
          : `错误类型：${result.error_code}`
      }}
    </p>
    <dl>
      <div>
        <dt>响应耗时</dt>
        <dd>{{ result.duration_ms }} ms</dd>
      </div>
      <div>
        <dt>请求次数</dt>
        <dd>{{ result.attempts ?? "—" }}</dd>
      </div>
      <div>
        <dt>工具事件</dt>
        <dd>{{ result.tool_events }}</dd>
      </div>
    </dl>
    <p class="muted">
      连接成功不代表回答质量通过。为避免敏感数据回显，此处仅显示协议验证状态。
    </p>
  </section>
  <el-dialog
    v-model="dialog"
    :title="editing ? '编辑 Agent 配置' : '接入 Agent'"
    width="760px"
    ><form @submit.prevent="save" class="agent-form">
      <div class="form-grid">
        <div>
          <label for="agent-name">Agent 名称</label
          ><el-input
            id="agent-name"
            v-model="form.name"
            maxlength="120"
            required
          />
        </div>
        <div>
          <label for="agent-project">所属项目</label
          ><el-select
            id="agent-project"
            v-model="form.project_id"
            :disabled="!!editing"
            placeholder="选择项目"
            ><el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
          /></el-select>
        </div>
      </div>
      <label for="agent-kind">接入方式</label
      ><el-select id="agent-kind" v-model="form.kind"
        ><el-option label="HTTP API" value="http" /><el-option
          label="受控 Python 协议验证（非 AI）"
          value="python" /></el-select
      ><template v-if="form.kind === 'http'"
        ><label for="endpoint">接口地址</label
        ><el-input
          id="endpoint"
          v-model="form.endpoint"
          placeholder="http://127.0.0.1:8001/chat"
          required
        />
        <div class="form-grid">
          <div>
            <label for="method">请求方法</label
            ><el-select id="method" v-model="form.method"
              ><el-option label="POST" value="POST" /><el-option
                label="GET"
                value="GET"
            /></el-select>
          </div>
          <div>
            <label for="auth-header">鉴权请求头名称</label
            ><el-input id="auth-header" v-model="form.auth_header" />
          </div>
        </div>
        <label for="api-key">鉴权值</label
        ><el-input
          id="api-key"
          v-model="apiKey"
          type="password"
          show-password
          autocomplete="off"
          placeholder="例如 Bearer 加密钥；编辑时留空保留"
        /><el-checkbox v-model="clearKey">清除已保存鉴权值</el-checkbox
        ><label for="headers">自定义请求头（JSON 对象）</label
        ><el-input
          id="headers"
          v-model="headers"
          type="textarea"
          :rows="2"
          placeholder='{"X-Client": "AgentTestLab"}'
        />
        <p class="field-hint">
          请求头值加密保存，不回显。留空保留；填写时替换全部自定义请求头。
        </p>
        <el-checkbox v-model="clearHeaders">清除已保存自定义请求头</el-checkbox
        ><label for="request-template">请求参数模板（JSON 对象）</label
        ><el-input
          id="request-template"
          v-model="template"
          type="textarea"
          :rows="3"
        />
        <p class="field-hint">
          不要在地址或参数模板中填写密钥，请使用上方加密字段。
        </p>
        <div class="form-grid">
          <div>
            <label for="input-field">输入字段路径</label
            ><el-input
              id="input-field"
              v-model="form.input_field"
              placeholder="input"
            />
          </div>
          <div>
            <label for="output-field">输出字段路径</label
            ><el-input
              id="output-field"
              v-model="form.output_field"
              placeholder="data.answer"
            />
          </div>
        </div>
        <label for="history-field">对话历史字段路径（可选）</label
        ><el-input
          id="history-field"
          v-model="form.history_field"
          placeholder="不传递历史时留空"
        />
        <label for="trace-field">工具事件字段路径（可选）</label
        ><el-input
          id="trace-field"
          v-model="form.trace_field"
          placeholder="例如 events；未提供时标记不可观测"
        />
        <label for="usage-field">Token 用量字段路径（可选）</label
        ><el-input
          id="usage-field"
          v-model="form.usage_field"
          placeholder="例如 usage；对象中的 total_tokens 为总用量"
        />
        <label for="contexts-field">实际检索上下文字段路径（可选）</label
        ><el-input
          id="contexts-field"
          v-model="form.contexts_field"
          placeholder="例如 contexts，值为字符串数组"
        />
      </template>
      <template v-else
        ><label for="adapter-name">受控适配器</label
        ><el-select id="adapter-name" v-model="form.adapter_name"
          ><el-option
            label="协议回显（非 AI，仅验证流程）"
            value="protocol_echo" /><el-option
            label="企业助手（需要真实模型配置）"
            value="enterprise_demo" /></el-select
      ></template>
      <div class="form-grid">
        <div>
          <label for="timeout">单次超时（秒）</label
          ><el-input-number
            id="timeout"
            v-model="form.timeout_seconds"
            :min="0.1"
            :step="0.1"
            :max="60"
          />
        </div>
        <div>
          <label for="retries">失败重试次数</label
          ><el-input-number
            id="retries"
            v-model="form.retries"
            :min="0"
            :max="3"
          />
        </div>
      </div>
      <p class="field-hint">
        重试可能重复发送请求，仅对已确认无副作用的待测接口开启。
      </p>
      <label for="version-label">版本说明</label
      ><el-input
        id="version-label"
        v-model="form.version_label"
        maxlength="120"
      />
      <div class="form-actions">
        <el-button @click="dialog = false">取消</el-button
        ><el-button
          type="primary"
          native-type="submit"
          :loading="saving"
          :disabled="!form.project_id"
          >保存配置</el-button
        >
      </div>
    </form></el-dialog
  ><el-dialog v-model="versionDialog" title="Agent 配置版本" width="680px"
    ><p v-if="versionError" role="alert" class="error">
      {{ versionError }} <button @click="showVersions()">重试</button>
    </p>
    <div v-loading="versionBusy">
      <article class="version-row" v-for="v in versions" :key="v.version">
        <h3>v{{ v.version }} · {{ v.snapshot.version_label }}</h3>
        <p>{{ v.snapshot.name }} · {{ v.snapshot.kind }}</p>
        <p class="muted">
          {{ v.snapshot.endpoint || v.snapshot.adapter_name }}
        </p>
      </article>
    </div>
    <el-pagination
      v-if="versionTotal > 20"
      v-model:current-page="versionPage"
      layout="prev,pager,next"
      :total="versionTotal"
      @current-change="showVersions()"
  /></el-dialog>
</template>
