<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from "vue";
import * as echarts from "echarts";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  project = ref(""),
  tasks = ref<any[]>([]),
  task = ref(""),
  baseline = ref(""),
  candidate = ref(""),
  summary = ref<any>(null),
  reports = ref<any[]>([]),
  report = ref<any>(null),
  regression = ref<any>(null),
  history = ref<any[]>([]),
  error = ref(""),
  busy = ref(false),
  chartEl = ref<HTMLElement | null>(null),
  weights = ref(
    '{"functional":25,"behavior":20,"rag":20,"security":20,"stability":15}',
  );
let chart: echarts.ECharts | undefined;
let observer: ResizeObserver | undefined;
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
  const [s, t, r, g] = await Promise.all([
    api.get("/dashboard", { params: { project_id: project.value } }),
    api.get("/test-tasks", {
      params: { project_id: project.value, page_size: 100 },
    }),
    api.get("/reports", { params: { project_id: project.value } }),
    api.get("/regressions", { params: { project_id: project.value } }),
  ]);
  summary.value = s.data;
  tasks.value = t.data.items;
  task.value = tasks.value[0]?.id || "";
  reports.value = r.data.items;
  history.value = g.data.items;
  report.value = null;
  regression.value = null;
  await nextTick();
  draw();
}
function draw() {
  if (!chartEl.value || !summary.value) return;
  chart ||= echarts.init(chartEl.value);
  const counts = summary.value.counts;
  chart.setOption({
    color: ["#294b9b"],
    tooltip: { trigger: "axis" },
    grid: { left: 50, right: 30, top: 20, bottom: 45 },
    xAxis: {
      type: "category",
      data: [
        "passed",
        "failed",
        "error",
        "inconclusive",
        "cancelled",
        "pending",
        "running",
      ],
    },
    yAxis: { type: "value", minInterval: 1 },
    series: [
      {
        type: "bar",
        data: [
          "passed",
          "failed",
          "error",
          "inconclusive",
          "cancelled",
          "pending",
          "running",
        ].map((k) => ({
          value: counts[k] || 0,
          itemStyle: {
            color: ["failed", "error"].includes(k) ? "#b42318" : "#294b9b",
          },
        })),
        barMaxWidth: 42,
      },
    ],
  });
}
async function create() {
  await act(async () => {
    report.value = (
      await api.post("/reports", {
        task_id: task.value,
        weights: JSON.parse(weights.value),
      })
    ).data;
    reports.value = (
      await api.get("/reports", { params: { project_id: project.value } })
    ).data.items;
  });
}
async function download(format: string) {
  await act(async () => {
    const response = await api.get(
      "/reports/" + report.value.id + (format === "png" ? "/chart" : "/export"),
      {
        params: { format },
        responseType: "blob",
      },
    );
    const url = URL.createObjectURL(response.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "AgentTestLab-" + report.value.id + "." + format;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}
async function compare() {
  await act(async () => {
    regression.value = (
      await api.post("/regressions", {
        baseline_id: baseline.value,
        candidate_id: candidate.value,
      })
    ).data;
    history.value = (
      await api.get("/regressions", { params: { project_id: project.value } })
    ).data.items;
  });
}
onMounted(() =>
  act(async () => {
    projects.value = (
      await api.get("/projects", { params: { page_size: 100 } })
    ).data.items;
    project.value = projects.value[0]?.id || "";
    weights.value = JSON.stringify(
      (await api.get("/report-options")).data.weights,
    );
    await load();
    observer = new ResizeObserver(() => chart?.resize());
    if (chartEl.value) observer.observe(chartEl.value);
  }),
);
onUnmounted(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>质量分析与报告</h1>
      <p>基于实际测试结果计算；缺失维度保持未知，严重安全风险独立提示。</p>
    </div>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="work-controls">
    <el-select v-model="project" aria-label="分析项目" @change="act(load)"
      ><el-option
        v-for="p in projects"
        :key="p.id"
        :label="p.name"
        :value="p.id" /></el-select
    ><el-button @click="act(load)">刷新统计</el-button>
  </div>
  <template v-if="summary"
    ><div class="analysis-stats">
      <div>
        测试任务<strong>{{ summary.task_count }}</strong>
      </div>
      <div>
        结果总数<strong>{{ summary.result_count }}</strong>
      </div>
      <div>
        通过率<strong>{{
          summary.pass_rate === null
            ? "—"
            : (summary.pass_rate * 100).toFixed(1) + "%"
        }}</strong>
      </div>
      <div>
        平均响应<strong>{{
          summary.average_ms === null
            ? "—"
            : summary.average_ms.toFixed(1) + " ms"
        }}</strong>
      </div>
    </div></template
  >
  <div
    ref="chartEl"
    class="quality-chart"
    role="img"
    aria-label="真实测试结果状态分布"
  />
  <el-tabs
    ><el-tab-pane label="评分与报告"
      ><div class="work-controls">
        <el-select v-model="task" aria-label="报告任务"
          ><el-option
            v-for="t in tasks"
            :key="t.id"
            :value="t.id"
            :label="t.name + ' / ' + t.status" /></el-select
        ><el-button
          type="primary"
          @click="create"
          :loading="busy"
          :disabled="!task"
          >生成冻结报告</el-button
        >
      </div>
      <label
        >评分权重 JSON（五维度）<el-input
          v-model="weights"
          type="textarea"
          :rows="2"
          aria-label="评分权重" /></label
      ><el-table :data="reports"
        ><el-table-column
          prop="name"
          label="历史报告"
          min-width="220"
        /><el-table-column
          prop="created_at"
          label="生成时间"
          min-width="180"
        /><el-table-column label="操作" width="120"
          ><template #default="s"
            ><el-button
              link
              @click="
                act(async () => {
                  report = (await api.get('/reports/' + s.row.id)).data;
                })
              "
              >查看报告</el-button
            ></template
          ></el-table-column
        ></el-table
      ><template v-if="report"
        ><h2>{{ report.name }}</h2>
        <el-alert
          v-if="report.summary.risk_warning"
          type="error"
          title="存在高危或严重安全违规，综合分数不能抵消风险"
          :closable="false"
        />
        <p>
          已观测维度加权分：<strong>{{ report.summary.score ?? "—" }}</strong> /
          100；缺失：{{
            report.summary.missing_dimensions.join("、") || "无"
          }}。分数不是完整安全认证。
        </p>
        <p>{{ report.summary.score_rule }}</p>
        <el-table
          :data="
            Object.entries(report.summary.dimensions).map(
              ([dimension, score]) => ({
                dimension,
                score,
                weight: report.summary.effective_weights[dimension],
              }),
            )
          "
          ><el-table-column prop="dimension" label="维度" /><el-table-column
            label="分数"
            ><template #default="s">{{
              s.row.score ?? "—"
            }}</template></el-table-column
          ><el-table-column label="有效权重"
            ><template #default="s">{{
              s.row.weight === undefined
                ? "未计入"
                : (s.row.weight * 100).toFixed(2) + "%"
            }}</template></el-table-column
          ></el-table
        >
        <div class="work-controls">
          <el-button
            v-for="f in ['html', 'pdf', 'json', 'csv', 'png']"
            :key="f"
            @click="download(f)"
            >导出 {{ f.toUpperCase() }}</el-button
          >
        </div>
        <h3>性能、风险与行为覆盖</h3>
        <pre class="evidence-text">{{
          JSON.stringify(
            {
              performance: report.summary.performance,
              coverage: report.summary.coverage,
              defects: report.summary.defects,
              findings: report.summary.findings,
            },
            null,
            2,
          )
        }}</pre>
        <el-table :data="report.results"
          ><el-table-column
            prop="name"
            label="用例"
            min-width="180"
          /><el-table-column prop="status" label="判定" /><el-table-column
            label="实际回答"
            min-width="260"
            ><template #default="s">{{
              s.row.output ?? "未取得回答"
            }}</template></el-table-column
          ><el-table-column label="证据" width="100"
            ><template #default="s"
              ><RouterLink :to="'/traces?result=' + s.row.id"
                >轨迹</RouterLink
              ></template
            ></el-table-column
          ></el-table
        ></template
      ></el-tab-pane
    >
    <el-tab-pane label="版本回归"
      ><p>
        选择同一
        Agent、同一套件的两个已结束任务。修改过的用例单列；仅同源且内容相同的用例参与新增失败/修复统计。
      </p>
      <div class="work-controls">
        <el-select v-model="baseline" aria-label="基线任务"
          ><el-option
            v-for="t in tasks"
            :key="t.id"
            :label="t.name"
            :value="t.id" /></el-select
        ><el-select v-model="candidate" aria-label="候选任务"
          ><el-option
            v-for="t in tasks"
            :key="t.id"
            :label="t.name"
            :value="t.id" /></el-select
        ><el-button
          @click="compare"
          :disabled="!baseline || !candidate"
          :loading="busy"
          >生成回归对比</el-button
        >
      </div>
      <el-table :data="history"
        ><el-table-column
          prop="baseline_id"
          label="基线"
          min-width="240"
        /><el-table-column
          prop="candidate_id"
          label="候选"
          min-width="240"
        /><el-table-column label="历史" width="110"
          ><template #default="s"
            ><el-button
              link
              @click="
                act(async () => {
                  regression = (await api.get('/regressions/' + s.row.id)).data;
                })
              "
              >查看对比</el-button
            ></template
          ></el-table-column
        ></el-table
      ><template v-if="regression"
        ><p>
          可比 {{ regression.comparable_count }} 条；新增失败
          {{ regression.new_failures.length }} 条；修复
          {{ regression.fixed_cases.length }} 条。
        </p>
        <p>{{ regression.note }}</p>
        <el-table :data="regression.pairs"
          ><el-table-column
            prop="name"
            label="同源用例"
            min-width="180"
          /><el-table-column prop="transition" label="变化" /><el-table-column
            prop="baseline_status"
            label="基线"
          /><el-table-column
            prop="candidate_status"
            label="候选"
          /><el-table-column
            prop="latency_delta_ms"
            label="耗时变化 ms"
            min-width="150"
          /><el-table-column label="轨迹" width="110"
            ><template #default="s"
              ><RouterLink :to="'/traces?result=' + s.row.candidate_result_id"
                >候选轨迹</RouterLink
              ></template
            ></el-table-column
          ></el-table
        >
        <pre class="evidence-text">{{
          JSON.stringify(regression, null, 2)
        }}</pre>
      </template></el-tab-pane
    ></el-tabs
  >
</template>
<style scoped>
.quality-chart {
  height: 260px;
  width: 100%;
}
.analysis-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  margin: 24px 0;
}
.analysis-stats strong {
  display: block;
  font-size: 28px;
  font-weight: 600;
}
@media (max-width: 650px) {
  .analysis-stats {
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }
}
</style>
