<script setup lang="ts">
import { ref, onMounted } from "vue";
import axios from "axios";
import { message } from "../api";
const live = ref("未检测"),
  database = ref("未检测"),
  busy = ref(false);
async function check() {
  busy.value = true;
  await Promise.allSettled([
    axios
      .get("/health/live")
      .then(() => (live.value = "服务正在运行"))
      .catch((e) => (live.value = message(e))),
    axios
      .get("/health/ready")
      .then(() => (database.value = "数据库与基础迁移可读"))
      .catch((e) => (database.value = message(e))),
  ]);
  busy.value = false;
}
onMounted(check);
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>运行状态</h1>
      <p>检测后端服务和数据库基础表的实际可用性。</p>
    </div>
    <el-button @click="check" :loading="busy">重新检测</el-button>
  </div>
  <section class="status-list">
    <div>
      <h2>后端服务</h2>
      <p>{{ live }}</p>
    </div>
    <div>
      <h2>MySQL</h2>
      <p>{{ database }}</p>
    </div>
    <div>
      <h2>本地 Milvus</h2>
      <p>用于知识库索引与向量检索，可在知识库中查看文档索引状态。</p>
    </div>
    <div>
      <h2>AI 评估与批量测试</h2>
      <p>请先保存可用模型，再创建测试任务。知识库相关测试还需要已完成索引的文档。</p>
    </div>
  </section>
</template>
