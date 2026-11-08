<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import { VueFlow } from "@vue-flow/core";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import { api, message } from "../api";
const route = useRoute(),
  projects = ref<any[]>([]),
  project = ref(""),
  tasks = ref<any[]>([]),
  task = ref(""),
  results = ref<any[]>([]),
  result = ref(String(route.query.result || "")),
  other = ref(""),
  current = ref<any>(null),
  comparison = ref<any>(null),
  selected = ref<any>(null),
  error = ref("");
const nodes = computed(
  () =>
    current.value?.events.map((e: any, i: number) => ({
      id: e.id,
      label: e.event_name + " · " + e.status,
      position: { x: e.parent_event_id ? 300 : 20, y: i * 90 },
      style: { borderColor: e.status === "error" ? "#b42318" : "#c6ccd7" },
    })) || [],
);
const edges = computed(
  () =>
    current.value?.events
      .filter(
        (e: any) =>
          e.parent_event_id &&
          current.value.events.some((x: any) => x.id === e.parent_event_id),
      )
      .map((e: any) => ({
        id: e.id + "-edge",
        source: e.parent_event_id,
        target: e.id,
      })) || [],
);
async function act(fn: () => Promise<void>) {
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = message(e);
  }
}
async function load() {
  current.value = (await api.get("/trace-analysis/" + result.value)).data;
  selected.value = null;
  comparison.value = null;
}
async function changeProject() {
  tasks.value = (
    await api.get("/test-tasks", {
      params: { project_id: project.value, page_size: 100 },
    })
  ).data.items;
  task.value = tasks.value[0]?.id || "";
  await changeTask();
}
async function changeTask() {
  results.value = task.value
    ? (await api.get("/traces", { params: { task_id: task.value } })).data.items
    : [];
}
async function compare() {
  comparison.value = (await api.get("/trace-analysis/" + other.value)).data;
}
const diff = computed(() => {
  if (!comparison.value || !current.value) return [];
  const signature = (e: any) =>
    JSON.stringify([e.event_type, e.event_name, e.status, e.data]);
  const left = new Set(current.value.events.map(signature)),
    right = new Set(comparison.value.events.map(signature));
  return [
    ...current.value.events
      .filter((e: any) => !right.has(signature(e)))
      .map((e: any) => ({ side: "仅基线", ...e })),
    ...comparison.value.events
      .filter((e: any) => !left.has(signature(e)))
      .map((e: any) => ({ side: "仅候选", ...e })),
  ];
});
onMounted(() =>
  act(async () => {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    project.value = projects.value[0]?.id || "";
    if (project.value) await changeProject();
    if (result.value) await load();
  }),
);
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>执行轨迹审计</h1>
      <p>展开真实采集的输入、工具、返回和异常事件，不推断模型内部思维链。</p>
    </div>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="work-controls">
    <el-select
      v-model="project"
      aria-label="轨迹项目"
      @change="act(changeProject)"
      ><el-option
        v-for="p in projects"
        :key="p.id"
        :value="p.id"
        :label="p.name" /></el-select
    ><el-select v-model="task" aria-label="轨迹任务" @change="act(changeTask)"
      ><el-option
        v-for="t in tasks"
        :key="t.id"
        :value="t.id"
        :label="t.name" /></el-select
    ><el-select v-model="result" aria-label="轨迹结果"
      ><el-option
        v-for="r in results"
        :key="r.trace_id"
        :value="r.trace_id"
        :label="r.case_name + ' / ' + r.status" /></el-select
    ><el-button @click="act(load)" :disabled="!result">加载轨迹</el-button>
  </div>
  <template v-if="current"
    ><p>
      {{
        current.events_observable
          ? "目标事件可观测"
          : "目标内部工具事件不可观测；仅展示平台实际记录"
      }}
      · {{ current.events.length }} 个事件
    </p>
    <h2>{{ current.case.name }}</h2>
    <el-tabs
      ><el-tab-pane label="事件时间线"
        ><el-table
          :data="current.events"
          @row-click="(r: any) => (selected = r)"
          ><el-table-column
            prop="timestamp"
            label="时间"
            min-width="210" /><el-table-column
            prop="event_type"
            label="事件类型"
            min-width="150" /><el-table-column
            prop="event_name"
            label="名称"
            min-width="180" /><el-table-column
            prop="status"
            label="状态"
            width="100" /><el-table-column
            prop="duration_ms"
            label="耗时 ms"
            width="120"
        /></el-table>
        <p>
          点击事件查看参数、返回与错误摘要。未提供的耗时不填造。
        </p></el-tab-pane
      ><el-tab-pane label="事件关系图"
        ><div class="trace-canvas">
          <VueFlow
            :nodes="nodes"
            :edges="edges"
            fit-view-on-init
            @node-click="
              ({ node }: any) =>
                (selected = current.events.find((e: any) => e.id === node.id))
            "
          />
        </div>
        <p>
          连线仅来自采集到的 parent_event_id；不以布局推断执行因果。
        </p></el-tab-pane
      ><el-tab-pane label="两次轨迹差异"
        ><el-input
          v-model="other"
          placeholder="候选结果 ID（可从测试结果复制）"
          aria-label="候选轨迹 ID" /><el-button
          @click="act(compare)"
          :disabled="!other"
          >比较事件内容</el-button
        >
        <p>
          按事件类型、名称、状态和内容比较；重复次数与时间顺序仍需对照时间线。
        </p>
        <el-table :data="diff"
          ><el-table-column
            prop="side"
            label="来源"
            width="120" /><el-table-column
            prop="event_type"
            label="类型" /><el-table-column
            prop="event_name"
            label="事件" /><el-table-column
            prop="status"
            label="状态" /></el-table></el-tab-pane
    ></el-tabs>
    <pre v-if="selected" class="evidence-text">{{
      JSON.stringify(selected, null, 2)
    }}</pre></template
  ><el-empty v-else description="选择已经执行的测试结果，查看真实轨迹" />
</template>
<style scoped>
.trace-canvas {
  height: 520px;
  border: 1px solid #d6dfeb;
  max-width: 100%;
}
</style>
