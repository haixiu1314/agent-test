<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessageBox } from "element-plus";
import { api, message } from "../api";
const projects = ref<any[]>([]),
  bases = ref<any[]>([]),
  models = ref<any[]>([]),
  docs = ref<any[]>([]),
  issues = ref<any[]>([]),
  datasets = ref<any[]>([]),
  evaluations = ref<any[]>([]);
const project = ref(""),
  kb = ref(""),
  tab = ref("documents"),
  busy = ref(false),
  error = ref(""),
  notice = ref("");
const configDialog = ref(false),
  editing = ref(false),
  form = ref<any>({}),
  chunkDialog = ref(false),
  chunkDoc = ref<any>(null),
  chunks = ref<any[]>([]),
  chunkPage = ref(1),
  chunkTotal = ref(0);
const issuePage = ref(1),
  issueTotal = ref(0),
  checkId = ref(""),
  semantic = ref(false),
  ragModel = ref(""),
  issueDetail = ref<any>(null),
  uploadLog = ref<string[]>([]);
const datasetDialog = ref(false),
  datasetEditing = ref(""),
  datasetName = ref(""),
  questionJson = ref(""),
  datasetId = ref(""),
  generateCount = ref(5);
const question = ref(""),
  topK = ref(5),
  hits = ref<any[]>([]),
  mode = ref("combined"),
  evaluation = ref<any>(null);
const prefix = () => `/rag/knowledge-bases/${kb.value}`;
const selected = () => bases.value.find((b) => b.id === kb.value);
const status: Record<string, string> = {
  parsed: "已解析",
  indexing: "入库中",
  indexed: "已入库",
  failed: "失败",
  generating: "生成中",
  draft: "待审阅",
  ready: "可评估",
  completed: "已完成",
  partial: "部分完成",
  running: "运行中",
  error: "异常",
  pending: "待确认",
  confirmed: "已确认",
  dismissed: "已排除",
};
const kinds: Record<string, string> = {
  duplicate: "完全重复",
  similar_candidate: "文本相似候选",
  conflict_candidate: "语义冲突候选",
  semantic_non_conflict: "语义检查无冲突",
  expired_candidate: "有效期已过候选",
  date_mention: "普通日期提示",
  empty: "空文本",
  too_short: "内容过短",
  too_long: "原始页过长",
  abnormal_text: "异常字符",
  format_anomaly: "格式异常",
  missing_source: "缺少来源",
  semantic_check_error: "语义检查不可用",
};
async function operate(work: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await work();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function all(path: string, params: Record<string, unknown> = {}) {
  const rows: any[] = [];
  for (let page = 1; ; page++) {
    const data = (
      await api.get(path, { params: { ...params, page, page_size: 100 } })
    ).data;
    rows.push(...data.items);
    if (
      data.total === undefined ||
      rows.length >= data.total ||
      !data.items.length
    )
      return rows;
  }
}
async function loadBases() {
  bases.value = (
    await api.get("/rag/knowledge-bases", {
      params: { project_id: project.value },
    })
  ).data.items;
  if (!bases.value.some((b) => b.id === kb.value))
    kb.value = bases.value[0]?.id || "";
  await loadKb();
}
async function loadIssues() {
  if (!kb.value) return;
  const d = (
    await api.get(prefix() + "/issues", {
      params: { page: issuePage.value, check_id: checkId.value || undefined },
    })
  ).data;
  issues.value = d.items;
  issueTotal.value = d.total;
}
async function loadDocs() {
  docs.value = (await api.get(prefix() + "/documents")).data.items;
}
async function loadDatasets() {
  datasets.value = (await api.get(prefix() + "/datasets")).data.items;
  if (!datasets.value.some((d) => d.id === datasetId.value))
    datasetId.value =
      datasets.value.find((d) => d.status === "ready")?.id || "";
}
async function loadKb() {
  docs.value = [];
  issues.value = [];
  datasets.value = [];
  evaluations.value = [];
  hits.value = [];
  evaluation.value = null;
  checkId.value = "";
  issuePage.value = 1;
  uploadLog.value = [];
  if (!kb.value) return;
  await Promise.all([
    loadDocs(),
    loadIssues(),
    loadDatasets(),
    loadEvaluations(),
  ]);
}
async function loadEvaluations() {
  evaluations.value = (await api.get(prefix() + "/evaluations")).data.items;
}
function openConfig(edit = false) {
  editing.value = edit;
  const b = selected();
  form.value =
    edit && b
      ? { name: b.name, description: b.description, ...b.config }
      : {
          name: "",
          description: "",
          dimension: 1536,
          chunk_size: 700,
          overlap: 100,
          embedding_model_id: null,
        };
  configDialog.value = true;
}
async function saveConfig() {
  await operate(async () => {
    const f = form.value;
    const body = {
      project_id: project.value,
      name: f.name,
      description: f.description,
      dimension: f.dimension,
      chunk_size: f.chunk_size,
      overlap: f.overlap,
      embedding_model_id: f.embedding_model_id || null,
    };
    const response = editing.value
      ? await api.put(prefix(), body)
      : await api.post("/rag/knowledge-bases", body);
    kb.value = response.data.id;
    configDialog.value = false;
    await loadBases();
    notice.value = "知识库配置已保存";
  });
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.value = "";
  if (files.length > 10) {
    error.value = "每批最多选择 10 个文件";
    return;
  }
  await operate(async () => {
    uploadLog.value = [];
    for (const file of files) {
      try {
        if (file.size > 500000) throw new Error("超过 500000 字节限制");
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (let i = 0; i < bytes.length; i += 16384)
          binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
        const d = (
          await api.post(prefix() + "/documents", {
            name: file.name,
            content_base64: btoa(binary),
          })
        ).data;
        uploadLog.value.push(`${file.name}：解析成功，${d.chunk_count} 个分块`);
      } catch (e) {
        uploadLog.value.push(`${file.name}：失败，${message(e)}`);
      }
    }
    await loadDocs();
  });
}
async function indexDoc(doc: any) {
  await operate(async () => {
    const d = (await api.post(prefix() + `/documents/${doc.id}/index`)).data;
    await loadDocs();
    if (d.error_code) error.value = `向量入库未完成：${d.error_code}`;
    else notice.value = "文档已写入真实向量库";
  });
}
async function removeDoc(doc: any) {
  try {
    await ElMessageBox.confirm(
      `删除“${doc.name}”及其分块、关联向量？历史评估中的来源快照会保留。`,
      "删除文档",
      { confirmButtonText: "确认删除", cancelButtonText: "返回" },
    );
    await operate(async () => {
      await api.delete(prefix() + `/documents/${doc.id}`);
      await loadDocs();
      await loadIssues();
    });
  } catch (e) {
    if (e !== "cancel" && e !== "close") error.value = message(e);
  }
}
async function removeKb() {
  try {
    await ElMessageBox.confirm(
      "删除此知识库及文档、向量、问题集和评估记录？",
      "删除知识库",
      { confirmButtonText: "确认删除", cancelButtonText: "返回" },
    );
    await operate(async () => {
      await api.delete(prefix());
      kb.value = "";
      await loadBases();
    });
  } catch (e) {
    if (e !== "cancel" && e !== "close") error.value = message(e);
  }
}
async function loadChunks() {
  const d = (
    await api.get(prefix() + `/documents/${chunkDoc.value.id}/chunks`, {
      params: { page: chunkPage.value },
    })
  ).data;
  chunks.value = d.items;
  chunkTotal.value = d.total;
}
async function showChunks(doc: any) {
  chunkDoc.value = doc;
  chunkPage.value = 1;
  await operate(async () => {
    await loadChunks();
    chunkDialog.value = true;
  });
}
async function check() {
  await operate(async () => {
    const d = (
      await api.post(prefix() + "/quality-check", {
        semantic_conflicts: semantic.value,
        model_config_id: ragModel.value || null,
      })
    ).data;
    checkId.value = d.check_id;
    issuePage.value = 1;
    await loadIssues();
    notice.value = `本次记录 ${d.issues} 条提示。语义状态：${d.semantic_status}，已检查 ${d.semantic_inspected} / ${d.semantic_candidates} 个候选。`;
    if (d.semantic_status === "failed")
      error.value =
        "语义检查未完成，查看“语义检查不可用”的详情；规则结果已保留。";
  });
}
async function confirm(issue: any, decision: string) {
  await operate(async () => {
    await api.put(`/rag/issues/${issue.id}/confirm`, null, {
      params: { decision },
    });
    await loadIssues();
    if (issueDetail.value?.id === issue.id)
      issueDetail.value = { ...issue, confirmation: decision };
  });
}
function editDataset(d?: any) {
  datasetEditing.value = d?.id || "";
  datasetName.value = d?.name || "手工问题集";
  questionJson.value = JSON.stringify(
    d?.questions || [{ question: "", reference: "", source_chunk_ids: [] }],
    null,
    2,
  );
  datasetDialog.value = true;
}
async function saveDataset() {
  await operate(async () => {
    const questions = JSON.parse(questionJson.value);
    const body = { name: datasetName.value, questions };
    const d = datasetEditing.value
      ? (await api.put(prefix() + `/datasets/${datasetEditing.value}`, body))
          .data
      : (await api.post(prefix() + "/datasets", body)).data;
    datasetId.value = d.id;
    datasetDialog.value = false;
    await loadDatasets();
    notice.value = "问题集已保存，可用于评估";
  });
}
async function generate() {
  await operate(async () => {
    const d = (
      await api.post(prefix() + "/datasets/generate", {
        count: generateCount.value,
        model_config_id: ragModel.value || null,
      })
    ).data;
    await loadDatasets();
    if (d.status === "draft") editDataset(d);
    else error.value = `AI 生成未完成：${d.error_code}，失败记录已保留`;
  });
}
async function search() {
  await operate(async () => {
    hits.value = [];
    hits.value = (
      await api.post(prefix() + "/retrieve", {
        question: question.value,
        top_k: topK.value,
      })
    ).data.hits;
    notice.value = `实际检索返回 ${hits.value.length} 个片段`;
  });
}
async function evaluate() {
  await operate(async () => {
    evaluation.value = (
      await api.post(prefix() + "/evaluate", {
        dataset_id: datasetId.value,
        mode: mode.value,
        top_k: topK.value,
        model_config_id: ragModel.value || null,
      })
    ).data;
    await loadEvaluations();
    if (evaluation.value.status !== "completed")
      error.value = `评估未全部完成：${evaluation.value.error_code || evaluation.value.status}。已取得的片段和回答保留在结果中。`;
  });
}
async function inspectEvaluation(id: string) {
  await operate(async () => {
    evaluation.value = (await api.get(`/rag/evaluations/${id}`)).data;
  });
}
onMounted(() =>
  operate(async () => {
    projects.value = await all("/projects");
    models.value = (await api.get("/models")).data.items;
    project.value = projects.value[0]?.id || "";
    if (project.value) await loadBases();
  }),
);
</script>
<template>
  <div class="knowledge-heading">
    <div>
      <h1>RAG 知识库测试</h1>
      <p class="muted">先核对知识来源，再检查检索和回答依据。</p>
    </div>
    <el-button type="primary" :disabled="!project || busy" @click="openConfig()"
      >创建知识库</el-button
    >
  </div>
  <div class="case-toolbar">
    <label
      >测试项目<el-select
        v-model="project"
        aria-label="测试项目"
        :disabled="busy"
        @change="operate(loadBases)"
        ><el-option
          v-for="p in projects"
          :key="p.id"
          :value="p.id"
          :label="p.name" /></el-select></label
    ><label
      >知识库<el-select
        v-model="kb"
        aria-label="知识库"
        :disabled="busy"
        @change="operate(loadKb)"
        ><el-option
          v-for="b in bases"
          :key="b.id"
          :value="b.id"
          :label="b.name" /></el-select></label
    ><el-button :disabled="!kb || busy" @click="openConfig(true)"
      >修改配置</el-button
    ><el-button :disabled="!kb || busy" @click="removeKb">删除知识库</el-button>
  </div>
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
  /><el-alert v-if="notice" :title="notice" type="info" :closable="false" />
  <el-empty
    v-if="!kb"
    description="创建知识库后即可上传文档；未配置模型也能解析和检查文本。"
  />
  <template v-else>
    <p class="muted">
      {{ selected()?.name }} · {{ selected()?.config.dimension }} 维 · 分块
      {{ selected()?.config.chunk_size }} / 重叠
      {{ selected()?.config.overlap }} 字符 · Embedding
      {{
        selected()?.config.embedding?.available === false
          ? "未配置"
          : selected()?.config.embedding?.model || "未配置"
      }}
    </p>
    <el-tabs
      v-model="tab"
      @tab-change="
        error = '';
        notice = '';
      "
    >
      <el-tab-pane label="文档与分块" name="documents">
        <div class="case-toolbar">
          <label class="upload-label"
            >批量上传文档<input
              aria-label="批量上传文档"
              type="file"
              multiple
              accept=".txt,.md,.pdf,.docx"
              :disabled="busy"
              @change="upload" /></label
          ><el-button :loading="busy" @click="operate(loadDocs)"
            >刷新文档</el-button
          >
        </div>
        <p class="muted">
          PDF、TXT、Markdown、DOCX；每文件最多 500000 字节，每批 10
          个。上传只解析，向量入库需真实 Embedding 和 Milvus。扫描 PDF 需先
          OCR。
        </p>
        <ul v-if="uploadLog.length">
          <li v-for="(line, i) in uploadLog" :key="i">{{ line }}</li>
        </ul>
        <div class="rag-table">
          <el-table :data="docs" empty-text="尚未上传文档"
            ><el-table-column
              prop="name"
              label="来源文档"
              min-width="210"
            /><el-table-column label="状态" width="110"
              ><template #default="{ row }">{{
                status[row.status] || row.status
              }}</template></el-table-column
            ><el-table-column
              prop="chunk_count"
              label="分块"
              width="80"
              align="right"
            /><el-table-column label="操作" min-width="240"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  :disabled="busy"
                  @click="showChunks(row)"
                  >查看分块</el-button
                ><el-button link :disabled="busy" @click="indexDoc(row)">{{
                  row.status === "indexed" ? "重建索引" : "向量入库"
                }}</el-button
                ><el-button
                  link
                  type="danger"
                  :disabled="busy"
                  @click="removeDoc(row)"
                  >删除文档</el-button
                >
                <div v-if="row.error_code" class="muted">
                  {{ row.error_code }}
                </div></template
              ></el-table-column
            ></el-table
          >
        </div>
      </el-tab-pane>
      <el-tab-pane label="知识质量" name="quality">
        <div class="case-toolbar">
          <el-checkbox v-model="semantic" :disabled="busy"
            >增加语义冲突检查</el-checkbox
          ><label
            >RAG 评估模型<el-select
              v-model="ragModel"
              clearable
              aria-label="RAG 评估模型"
              placeholder="使用本地默认配置"
              :disabled="busy"
              ><el-option
                v-for="m in models.filter((m) => m.purpose === 'rag')"
                :key="m.id"
                :label="m.name"
                :value="m.id" /></el-select></label
          ><el-button type="primary" :loading="busy" @click="check"
            >开始质量检查</el-button
          ><el-button
            :disabled="busy"
            @click="
              operate(async () => {
                checkId = '';
                issuePage = 1;
                await loadIssues();
              })
            "
            >查看全部检查记录</el-button
          >
        </div>
        <p class="muted">
          完全重复、文本相似、字符异常和明确有效期可直接检查。语义冲突需要真实
          Embedding 和模型；相似度不是冲突结论，普通日期不是过期证据。单次最多
          300 分块、20 个语义候选。
        </p>
        <p>
          问题与提示 {{ issueTotal }} 条{{
            checkId ? "（本次检查）" : "（全部历史）"
          }}
        </p>
        <div class="rag-table">
          <el-table :data="issues" empty-text="暂无提示，请先执行质量检查"
            ><el-table-column label="类型" min-width="180"
              ><template #default="{ row }">{{
                kinds[row.kind] || row.kind
              }}</template></el-table-column
            ><el-table-column label="人工处理" width="100"
              ><template #default="{ row }">{{
                status[row.confirmation]
              }}</template></el-table-column
            ><el-table-column label="原因" min-width="250"
              ><template #default="{ row }">{{
                row.detail.reason
              }}</template></el-table-column
            ><el-table-column label="操作" min-width="210"
              ><template #default="{ row }"
                ><el-button link @click="issueDetail = row">来源详情</el-button
                ><el-button
                  link
                  :disabled="busy"
                  @click="confirm(row, 'confirmed')"
                  >确认问题</el-button
                ><el-button
                  link
                  :disabled="busy"
                  @click="confirm(row, 'dismissed')"
                  >排除</el-button
                ></template
              ></el-table-column
            ></el-table
          >
        </div>
        <el-pagination
          v-if="issueTotal > 50"
          v-model:current-page="issuePage"
          :total="issueTotal"
          :page-size="50"
          layout="prev,pager,next"
          @current-change="operate(loadIssues)"
        />
      </el-tab-pane>
      <el-tab-pane label="问题集" name="datasets">
        <div class="case-toolbar">
          <el-button type="primary" :disabled="busy" @click="editDataset()"
            >创建问题集</el-button
          ><label
            >AI 生成数量<el-input-number
              v-model="generateCount"
              aria-label="AI 生成数量"
              :min="1"
              :max="20" /></label
          ><el-button :loading="busy" @click="generate"
            >根据文档生成问题</el-button
          >
        </div>
        <p class="muted">
          每组 1–20 条“问题 + 标准答案”。AI 生成使用质量页所选模型，读取前 30
          个分块；生成后须审阅保存。未配置时保留失败记录。
        </p>
        <div class="rag-table">
          <el-table :data="datasets" empty-text="还没有问题集"
            ><el-table-column
              prop="name"
              label="问题集"
              min-width="180"
            /><el-table-column label="状态 / 来源" min-width="170"
              ><template #default="{ row }"
                >{{ status[row.status] || row.status }} ·
                {{ row.source === "ai" ? "AI" : "手工" }}
                <div class="muted">{{ row.error_code || "" }}</div></template
              ></el-table-column
            ><el-table-column label="问题数" width="90" align="right"
              ><template #default="{ row }">{{
                row.questions?.length || 0
              }}</template></el-table-column
            ><el-table-column label="操作" width="150"
              ><template #default="{ row }"
                ><el-button
                  link
                  :disabled="busy || row.status === 'generating'"
                  @click="editDataset(row)"
                  >编辑 / 审阅</el-button
                ></template
              ></el-table-column
            ></el-table
          >
        </div>
      </el-tab-pane>
      <el-tab-pane label="检索与评估" name="evaluate">
        <div class="rag-controls">
          <label
            >检索问题<el-input
              v-model="question"
              aria-label="检索问题"
              placeholder="输入要从知识库查找的问题" /></label
          ><label
            >Top-K<el-input-number
              v-model="topK"
              aria-label="Top-K"
              :min="1"
              :max="10" /></label
          ><el-button
            :loading="busy"
            :disabled="!question.trim()"
            @click="search"
            >检索片段</el-button
          >
        </div>
        <article v-for="h in hits" :key="h.chunk_id" class="rag-evidence">
          <strong>{{ h.source_name }} · 第 {{ h.page_number }} 页</strong>
          <p class="muted">
            余弦相似度
            {{ Number(h.distance).toFixed(4) }}；它不等于回答质量分数。
          </p>
          <p>{{ h.content }}</p>
        </article>
        <h2 class="rag-section-title">批量 RAGAS 评估</h2>
        <div class="case-toolbar">
          <label
            >问题集<el-select
              v-model="datasetId"
              aria-label="评估问题集"
              :disabled="busy"
              ><el-option
                v-for="d in datasets.filter((d) => d.status === 'ready')"
                :key="d.id"
                :value="d.id"
                :label="d.name" /></el-select></label
          ><label
            >评估范围<el-select
              v-model="mode"
              aria-label="评估范围"
              :disabled="busy"
              ><el-option
                label="检索 + 回答（四项指标）"
                value="combined" /><el-option
                label="仅检索（准确率与召回）"
                value="retrieval" /><el-option
                label="仅回答（依据与相关性）"
                value="generation" /></el-select></label
          ><el-button
            type="primary"
            :disabled="!datasetId"
            :loading="busy"
            @click="evaluate"
            >执行 RAGAS 评估</el-button
          >
        </div>
        <p class="muted">
          使用质量页所选 RAG 模型。评估会实际调用 Embedding、Milvus
          和模型，最多运行 180 秒，超时保留已取得证据。低质量阈值为
          0.7，失败样本不计为满分。
        </p>
        <div v-if="evaluation" class="review-section">
          <h2>
            本次结果 · {{ status[evaluation.status] || evaluation.status }}
          </h2>
          <p v-if="evaluation.error_code">
            错误码：{{ evaluation.error_code }}
          </p>
          <el-empty
            v-if="!evaluation.samples?.length"
            description="尚无评估样本，请检查模型和索引配置"
          />
          <article
            v-for="(s, i) in evaluation.samples"
            :key="i"
            class="rag-evidence"
          >
            <h3>{{ Number(i) + 1 }}. {{ s.question }}</h3>
            <p>
              {{ status[s.status] || s.status
              }}{{ s.low_quality ? " · 低质量样本" : ""
              }}{{ s.error_code ? " · " + s.error_code : "" }}
            </p>
            <p>标准答案：{{ s.reference }}</p>
            <p>实际回答：{{ s.answer || "未生成（仅检索或调用未完成）" }}</p>
            <dl class="rag-metrics">
              <div v-for="(value, key) in s.metrics" :key="key">
                <dt>{{ key }}</dt>
                <dd>{{ Number(value).toFixed(4) }}</dd>
              </div>
            </dl>
            <details>
              <summary>命中来源与实际片段（{{ s.hits?.length || 0 }}）</summary>
              <pre class="json-view">{{ JSON.stringify(s.hits, null, 2) }}</pre>
            </details>
          </article>
          <details>
            <summary>本次配置快照</summary>
            <pre class="json-view">{{
              JSON.stringify(evaluation.config, null, 2)
            }}</pre>
          </details>
        </div>
        <h2 class="rag-section-title">评估历史</h2>
        <el-empty v-if="!evaluations.length" description="还没有执行记录" />
        <div v-for="r in evaluations" :key="r.id" class="rag-history">
          <span>{{ status[r.status] || r.status }} · {{ r.created_at }}</span
          ><el-button link @click="inspectEvaluation(r.id)"
            >查看评估记录</el-button
          >
        </div>
      </el-tab-pane>
    </el-tabs>
    <p class="rag-mobile-hint muted">表格可左右滑动查看操作和详细字段。</p>
  </template>
  <el-dialog
    v-model="configDialog"
    :title="editing ? '修改知识库' : '创建知识库'"
    width="680px"
    ><el-form label-position="top"
      ><el-form-item label="知识库名称"
        ><el-input
          v-model="form.name"
          aria-label="知识库名称"
          maxlength="120" /></el-form-item
      ><el-form-item label="描述"
        ><el-input
          v-model="form.description"
          aria-label="知识库描述"
          type="textarea"
          maxlength="5000" /></el-form-item
      ><el-form-item label="Embedding 模型"
        ><el-select
          v-model="form.embedding_model_id"
          aria-label="Embedding 模型"
          clearable
          placeholder="使用本地默认配置"
          ><el-option
            v-for="m in models.filter((m) => m.purpose === 'embedding')"
            :key="m.id"
            :value="m.id"
            :label="m.name" /></el-select
      ></el-form-item>
      <div class="rag-form-grid">
        <el-form-item label="向量维度"
          ><el-input-number
            v-model="form.dimension"
            aria-label="向量维度"
            :min="8"
            :max="4096" /></el-form-item
        ><el-form-item label="每块字符数"
          ><el-input-number
            v-model="form.chunk_size"
            aria-label="每块字符数"
            :min="100"
            :max="2000" /></el-form-item
        ><el-form-item label="重叠字符数"
          ><el-input-number
            v-model="form.overlap"
            aria-label="重叠字符数"
            :min="0"
            :max="500"
        /></el-form-item>
      </div>
      <p class="muted">
        维度须与模型实际输出一致。同一 Milvus
        集合使用固定维度。修改分块参数需要先删除文档；修改模型前需清除已有索引。
      </p></el-form
    ><template #footer
      ><el-button @click="configDialog = false">返回</el-button
      ><el-button
        type="primary"
        :disabled="!form.name?.trim()"
        :loading="busy"
        @click="saveConfig"
        >保存知识库</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="chunkDialog"
    :title="`${chunkDoc?.name || ''} · 文档分块`"
    width="760px"
    ><el-empty
      v-if="!chunks.length"
      description="没有可索引文本，扫描 PDF 请先 OCR" />
    <article v-for="c in chunks" :key="c.id" class="rag-evidence">
      <strong>第 {{ c.page_number }} 页 · 分块 {{ c.position + 1 }}</strong>
      <p>{{ c.content }}</p>
      <small>{{ c.id }}</small>
    </article>
    <el-pagination
      v-if="chunkTotal > 50"
      v-model:current-page="chunkPage"
      :total="chunkTotal"
      :page-size="50"
      layout="prev,pager,next"
      @current-change="operate(loadChunks)"
  /></el-dialog>
  <el-dialog
    :model-value="!!issueDetail"
    title="知识问题来源与依据"
    width="760px"
    @close="issueDetail = null"
    ><template v-if="issueDetail"
      ><h2>{{ kinds[issueDetail.kind] || issueDetail.kind }}</h2>
      <p>{{ issueDetail.detail.reason }}</p>
      <p v-if="issueDetail.detail.fact">
        冲突事实：{{ issueDetail.detail.fact }}
      </p>
      <p v-if="issueDetail.detail.recommendation">
        建议：{{ issueDetail.detail.recommendation }}
      </p>
      <article
        v-for="(s, i) in issueDetail.detail.sources"
        :key="i"
        class="rag-evidence"
      >
        <strong>{{ s.name }} · 第 {{ s.page }} 页</strong>
        <p>{{ s.content }}</p>
      </article>
      <pre class="json-view">{{
        JSON.stringify(issueDetail.detail, null, 2)
      }}</pre>
      <p>人工处理：{{ status[issueDetail.confirmation] }}</p></template
    ></el-dialog
  >
  <el-dialog
    v-model="datasetDialog"
    :title="datasetEditing ? '审阅 / 编辑问题集' : '创建问题集'"
    width="760px"
    ><label
      >问题集名称<el-input
        v-model="datasetName"
        aria-label="问题集名称" /></label
    ><label
      >问题与标准答案（JSON 数组）<el-input
        v-model="questionJson"
        aria-label="问题与标准答案"
        type="textarea"
        :rows="15"
    /></label>
    <p class="muted">
      question 为问题，reference 为标准答案；source_chunk_ids 可填写当前库分块
      ID。审阅 AI 答案是否有来源支持，再保存。
    </p>
    <template #footer
      ><el-button @click="datasetDialog = false">返回</el-button
      ><el-button type="primary" :loading="busy" @click="saveDataset"
        >保存问题集</el-button
      ></template
    ></el-dialog
  >
</template>
<style scoped>
.knowledge-heading {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
}
.rag-table {
  overflow-x: auto;
  margin-top: 16px;
}
.rag-evidence {
  padding: 18px 0;
  border-bottom: 1px solid #e5e8ec;
  overflow-wrap: anywhere;
}
.rag-controls {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 16px;
  margin: 20px 0;
}
.rag-controls label:first-child {
  flex: 1;
  min-width: 200px;
}
.rag-controls label {
  margin: 0;
}
.rag-section-title {
  margin-top: 28px;
}
.rag-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
}
.rag-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}
.rag-metrics dt {
  color: #5b667b;
  font-size: 12px;
}
.rag-metrics dd {
  margin: 0;
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}
.rag-history {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  padding: 10px 0;
  border-bottom: 1px solid #e5e8ec;
}
.upload-label {
  min-width: 0 !important;
}
.upload-label input {
  display: block;
  max-width: 100%;
  margin-top: 6px;
}
.el-select {
  width: 100%;
}
.rag-mobile-hint {
  display: none;
}
@media (max-width: 640px) {
  .knowledge-heading {
    flex-wrap: wrap;
  }
  .rag-form-grid {
    grid-template-columns: 1fr;
  }
  .rag-mobile-hint {
    display: block;
  }
  .rag-controls {
    align-items: stretch;
  }
  .rag-controls label:first-child {
    flex-basis: 100%;
  }
}
</style>
