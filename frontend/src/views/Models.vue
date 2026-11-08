<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api, message } from "../api";
interface ModelForm {
  name: string;
  purpose: string;
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
}
interface SavedModel extends Omit<ModelForm, "api_key"> {
  id: string;
  has_api_key: boolean;
}
interface TestResult {
  success: boolean;
  code: string;
  message: string;
  latency_ms?: number;
}
const defaults = (): ModelForm => ({
  name: "",
  purpose: "generation",
  provider: "openai-compatible",
  base_url: "",
  model: "",
  api_key: "",
});
const purposes: Record<string, string> = {
  generation: "测试用例生成",
  demo: "企业助手演示",
  judge: "质量评估",
  security: "安全用例生成",
  rag: "知识库评估",
  embedding: "文本向量化",
};
const items = ref<SavedModel[]>([]),
  form = ref<ModelForm>(defaults());
const id = ref(""),
  hasSavedKey = ref(false),
  showKey = ref(false),
  ready = ref(false),
  loading = ref(true),
  error = ref("");
const saving = ref(false),
  testing = ref(false),
  result = ref<TestResult | null>(null),
  testedSnapshot = ref("");
const editor = ref<HTMLElement | null>(null);
function payload() {
  return {
    ...form.value,
    name: form.value.name.trim(),
    base_url: form.value.base_url.trim(),
    model: form.value.model.trim(),
    api_key: form.value.api_key || null,
  };
}
const snapshot = computed(() =>
  JSON.stringify({ ...payload(), saved_model_id: id.value || null }),
);
const currentResult = computed(() =>
  testedSnapshot.value === snapshot.value ? result.value : null,
);
const canSave = computed(
  () => !!currentResult.value?.success && !testing.value && !saving.value,
);
async function load() {
  error.value = "";
  loading.value = true;
  try {
    const data = (await api.get("/models")).data;
    items.value = data.items;
    ready.value = data.environment_ready;
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}
function open(model?: SavedModel, scroll = true) {
  id.value = model?.id || "";
  hasSavedKey.value = model?.has_api_key || false;
  form.value = model
    ? {
        name: model.name,
        purpose: model.purpose,
        provider: model.provider,
        base_url: model.base_url,
        model: model.model,

        api_key: "",
      }
    : defaults();
  showKey.value = false;
  testedSnapshot.value = "";
  result.value = null;
  if (scroll)
    editor.value?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function validate() {
  if (
    ![form.value.name, form.value.base_url, form.value.model].every((value) =>
      value.trim(),
    )
  ) {
    ElMessage.warning("请填写配置名称、接口地址和模型名称");
    return false;
  }
  if (!form.value.api_key && !hasSavedKey.value) {
    ElMessage.warning("请填写 API 密钥");
    return false;
  }
  return true;
}
async function testConnection() {
  if (!validate() || testing.value || saving.value) return;
  testing.value = true;
  result.value = null;
  const requestedSnapshot = snapshot.value;
  try {
    const response = await api.post("/models/test", {
      ...payload(),
      saved_model_id: id.value || null,
    });
    if (snapshot.value === requestedSnapshot) {
      result.value = response.data;
      testedSnapshot.value = requestedSnapshot;
    }
  } catch (e) {
    if (snapshot.value === requestedSnapshot) {
      result.value = {
        success: false,
        code: "request_failed",
        message: message(e),
      };
      testedSnapshot.value = requestedSnapshot;
    }
  } finally {
    testing.value = false;
  }
}
async function save() {
  if (!canSave.value) return;
  saving.value = true;
  try {
    const response = id.value
      ? await api.put(`/models/${id.value}`, payload())
      : await api.post("/models", payload());
    open(response.data, false);
    await load();
    ElMessage.success("模型配置已加密保存");
  } catch (e) {
    ElMessage.error(message(e));
  } finally {
    saving.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>模型配置</h1>
      <p>配置你自己的模型，测试后保存。其他用户无法查看或使用你的配置。</p>
    </div>
    <el-button :disabled="testing || saving" @click="open()"
      >添加模型</el-button
    >
  </div>
  <section
    ref="editor"
    class="model-editor"
    aria-labelledby="model-editor-title"
  >
    <h2 id="model-editor-title">{{ id ? "编辑模型" : "添加模型" }}</h2>
    <form @submit.prevent="save" class="model-form">
      <div class="model-form-grid">
        <div class="model-field">
          <label for="model-name">配置名称</label
          ><el-input
            id="model-name"
            v-model="form.name"
            placeholder="例如：我的评估模型"
            :disabled="testing || saving"
            maxlength="120"
            required
          />
        </div>
        <div class="model-field">
          <label for="model-purpose">用途</label
          ><el-select
            id="model-purpose"
            v-model="form.purpose"
            aria-label="模型用途"
            :disabled="testing || saving"
            ><el-option
              v-for="(label, value) in purposes"
              :key="value"
              :value="value"
              :label="label"
          /></el-select>
        </div>
        <div class="model-field model-field-wide">
          <label for="model-url">模型接口 URL</label
          ><el-input
            id="model-url"
            v-model="form.base_url"
            placeholder="https://服务商地址/v1"
            :disabled="testing || saving"
            maxlength="1000"
            required
          />
          <p class="model-help">
            填写 OpenAI 兼容接口的基础地址，通常以 /v1 结尾，无需添加
            /chat/completions。
          </p>
        </div>
        <div class="model-field model-field-wide">
          <label for="model-id">模型名称</label
          ><el-input
            id="model-id"
            v-model="form.model"
            placeholder="填写服务商提供的准确模型名称"
            :disabled="testing || saving"
            maxlength="120"
            required
          />
        </div>
        <div class="model-field model-field-wide">
          <label for="model-key">API 密钥</label>
          <el-input
            id="model-key"
            v-model="form.api_key"
            :type="showKey ? 'text' : 'password'"
            autocomplete="new-password"
            :disabled="testing || saving"
            :placeholder="
              hasSavedKey
                ? '已保存密钥；留空继续使用原密钥'
                : '填写服务商提供的 API 密钥'
            "
            maxlength="8192"
          >
            <template #suffix
              ><button
                class="model-key-toggle"
                type="button"
                :aria-label="showKey ? '隐藏密钥' : '显示密钥'"
                :aria-pressed="showKey"
                @click="showKey = !showKey"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.7"
                  aria-hidden="true"
                >
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                  <circle cx="12" cy="12" r="3" />
                  <path v-if="showKey" d="m3 3 18 18" />
                </svg></button
            ></template>
          </el-input>
          <p class="model-help">
            默认隐藏，点击眼睛查看本次输入。保存时加密存储，已保存的密钥不会回显。
          </p>
        </div>
      </div>
      <div class="model-test-block">
        <p class="model-help">
          系统使用低消耗请求验证连接，单次测试最长约 22 秒。
        </p>
        <div class="form-actions">
          <el-button
            :loading="testing"
            :disabled="saving"
            @click="testConnection"
            >测试</el-button
          ><el-button
            type="primary"
            native-type="submit"
            :disabled="!canSave"
            :loading="saving"
            >保存配置</el-button
          ><el-button v-if="id" :disabled="testing || saving" @click="open()"
            >取消编辑</el-button
          >
        </div>
        <p v-if="testing" role="status">正在请求模型，请稍候…</p>
        <p
          v-else-if="currentResult"
          role="status"
          :class="currentResult.success ? 'model-test-success' : 'inline-error'"
        >
          {{ currentResult.success ? "测试通过" : "测试未通过" }}：{{
            currentResult.message
          }}<span v-if="currentResult.latency_ms !== undefined"
            >（{{ currentResult.latency_ms }} ms）</span
          >
        </p>
        <p v-else class="model-help">
          先测试，通过后即可保存；修改配置后需要重新测试。
        </p>
      </div>
    </form>
  </section>
  <section class="list-section" aria-labelledby="saved-models-title">
    <h2 id="saved-models-title">我的模型配置</h2>
    <p v-if="loading" role="status">正在读取配置…</p>
    <div v-else-if="error">
      <p class="inline-error">{{ error }}</p>
      <el-button @click="load">重新加载</el-button>
    </div>
    <p v-else-if="!items.length" class="empty">
      还没有保存模型。在上方填写并测试你的第一个模型。
    </p>
    <article
      v-for="model in items"
      :key="model.id"
      class="project-row model-row"
    >
      <div>
        <h3>{{ model.name }}</h3>
        <p>
          {{ model.model }} · {{ purposes[model.purpose] }} ·
          {{ model.has_api_key ? "密钥已加密保存" : "缺少密钥" }}
        </p>
        <small>{{ model.base_url }}</small>
      </div>
      <el-button :disabled="testing || saving" @click="open(model)"
        >编辑</el-button
      >
    </article>
    <p class="model-help">
      服务器默认模型：{{
        ready
          ? "已配置；仍以实际调用结果为准"
          : "未配置；你可以使用自己的模型配置"
      }}。
    </p>
  </section>
</template>
<style scoped>
.model-editor {
  max-width: 960px;
  padding: 24px 0;
  border-bottom: 1px solid #e5e7eb;
  scroll-margin-top: 24px;
}
.model-form {
  margin-top: 20px;
}
.model-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px 24px;
}
.model-field {
  min-width: 0;
}
.model-field label {
  display: block;
  margin-bottom: 8px;
}
.model-field-wide {
  grid-column: 1 / -1;
}
.model-help {
  color: var(--muted, #52627a);
  font-size: 13px;
  line-height: 1.6;
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.model-key-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 0;
  padding: 6px;
  color: inherit;
  cursor: pointer;
}
.model-key-toggle:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 1px;
}
.model-test-block {
  margin-top: 24px;
}
.model-test-success {
  color: #17643f;
}
.model-row > div {
  min-width: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 640px) {
  .model-form-grid {
    grid-template-columns: 1fr;
  }
  .model-key-toggle {
    min-width: 44px;
    min-height: 36px;
  }
  .form-actions {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
