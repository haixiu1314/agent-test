<script setup lang="ts">
import { ref, onMounted } from "vue";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  knowledgeBases = ref<any[]>([]),
  knowledgeBase = ref(""),
  models = ref<any[]>([]),
  project = ref(""),
  model = ref("__environment__"),
  input = ref(""),
  defect = ref("none"),
  history = ref<any[]>([]),
  result = ref<any>(null),
  runs = ref<any[]>([]),
  busy = ref(false),
  error = ref("");
const defects = [
  ["none", "正常模式"],
  ["wrong_tool_description", "错误工具描述"],
  ["missing_knowledge", "删除关键知识"],
  ["conflicting_knowledge", "冲突知识"],
  ["bad_prompt", "不合理提示词"],
  ["tool_timeout", "模拟工具超时"],
];
async function load() {
  knowledgeBase.value = "";
  history.value = [];
  result.value = null;
  try {
    knowledgeBases.value = (
      await api.get("/rag/knowledge-bases", {
        params: { project_id: project.value },
      })
    ).data.items;
    runs.value = (
      await api.get("/demo/runs", { params: { project_id: project.value } })
    ).data.items;
  } catch (e) {
    error.value = message(e);
  }
}
async function send() {
  busy.value = true;
  error.value = "";
  try {
    result.value = (
      await api.post("/demo/chat", {
        project_id: project.value,
        knowledge_base_id: knowledgeBase.value || null,
        model_config_id: model.value === "__environment__" ? null : model.value,
        input: input.value,
        history: history.value.slice(-30),
        defect: defect.value,
      })
    ).data;
    history.value.push(
      { role: "user", content: input.value },
      { role: "assistant", content: result.value.output },
    );
    input.value = "";
    runs.value = (
      await api.get("/demo/runs", { params: { project_id: project.value } })
    ).data.items;
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  try {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    models.value = (await api.get("/models")).data.items.filter(
      (m: any) => m.purpose === "demo",
    );
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
      <h1>企业助手演示</h1>
      <p>通过真实模型尝试制度问答、计算与多轮对话，查看实际工具事件。</p>
    </div>
  </div>
  <div class="content-grid">
    <section class="list-section">
      <h2>对话实验</h2>
      <p class="guide-note">
        天气为固定模拟数据；选择知识库后调用真实
        Milvus，未选则使用本地关键词样例。模型未配置时无法对话。
      </p>
      <form @submit.prevent="send">
        <label
          >测试项目
          <el-select v-model="project" aria-label="测试项目" @change="load"
            ><el-option
              v-for="p in projects"
              :key="p.id"
              :value="p.id"
              :label="p.name" /></el-select></label
        ><label
          >演示模型
          <el-select v-model="model" aria-label="演示模型"
            ><el-option
              value="__environment__"
              label="本地 .env 模型" /><el-option
              v-for="m in models"
              :key="m.id"
              :value="m.id"
              :label="m.name" /></el-select></label
        ><label
          >检索知识库
          <el-select
            v-model="knowledgeBase"
            aria-label="演示知识库"
            clearable
            placeholder="本地关键词样例"
          >
            <el-option
              v-for="k in knowledgeBases"
              :key="k.id"
              :value="k.id"
              :label="k.name"
            /> </el-select></label
        ><label
          >缺陷实验
          <el-select v-model="defect" aria-label="缺陷实验"
            ><el-option
              v-for="d in defects"
              :key="d[0]"
              :value="d[0]"
              :label="d[1]" /></el-select></label
        ><label for="demo-input">你的问题</label
        ><el-input
          id="demo-input"
          v-model="input"
          type="textarea"
          :rows="4"
          required
          maxlength="10000"
          placeholder="例如：年假如何申请？再计算 (125+75)/4。"
        />
        <div class="form-actions">
          <el-button
            @click="
              history = [];
              result = null;
            "
            >清空本轮对话</el-button
          ><el-button
            type="primary"
            native-type="submit"
            :loading="busy"
            :disabled="!project"
            >发送给模型</el-button
          >
        </div>
      </form>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
      <article v-for="(h, i) in history" :key="i" class="generation-record">
        <strong>{{ h.role === "user" ? "你" : "企业助手" }}</strong>
        <p class="chat-text">{{ h.content }}</p>
      </article>
    </section>
    <section class="guide">
      <h2>真实事件与运行记录</h2>
      <template v-if="result"
        ><p>以下为本次模型响应和工具执行产生的事件。</p>
        <pre class="json-view">{{
          JSON.stringify(result.events, null, 2)
        }}</pre>
      </template>
      <p v-else>模型执行后，这里显示可观测事件。不会展示虚构的模型思维链。</p>
      <article v-for="r in runs" :key="r.id" class="generation-record">
        <strong>{{ r.status }}</strong>
        <p>{{ r.request.input }}</p>
        <details v-if="r.result">
          <summary>查看已保存回答和事件</summary>
          <pre class="json-view">{{ JSON.stringify(r.result, null, 2) }}</pre>
        </details>
      </article>
    </section>
  </div>
</template>
<style scoped>
.chat-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
