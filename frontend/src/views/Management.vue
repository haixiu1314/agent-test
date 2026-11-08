<script setup lang="ts">
import { ref, onMounted } from "vue";
import { api, message } from "../api";
const me = ref<{ username: string } | null>(null),
  logs = ref<any[]>([]);
const error = ref(""),
  notice = ref(""),
  oldPassword = ref(""),
  newPassword = ref("");
const logPage = ref(1),
  logTotal = ref(0),
  busy = ref(false),
  changing = ref(false);
const actionNames: Record<string, string> = {
  "auth.login": "登录",
  "auth.register": "注册",
  "auth.password": "修改密码",
  "model.create": "添加模型",
  "model.update": "修改模型",
  "model.test.available": "模型测试通过",
  "model.test.authentication_failed": "模型认证失败",
  "agent.connection.ok": "Agent 连接成功",
  "project.create": "创建项目",
  "project.update": "修改项目",
};
async function readLogs() {
  const data = (
    await api.get("/operation-logs", { params: { page: logPage.value } })
  ).data;
  logs.value = data.items;
  logTotal.value = data.total;
}
async function load() {
  busy.value = true;
  error.value = "";
  try {
    me.value = (await api.get("/auth/me")).data;
    await readLogs();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function changePage() {
  error.value = "";
  try {
    await readLogs();
  } catch (e) {
    error.value = message(e);
  }
}
async function changePassword() {
  changing.value = true;
  error.value = "";
  notice.value = "";
  try {
    await api.put("/auth/password", {
      password: oldPassword.value,
      new_password: newPassword.value,
    });
    oldPassword.value = "";
    newPassword.value = "";
    notice.value = "密码已更新，下次登录请使用新密码。";
    await readLogs();
  } catch (e) {
    error.value = message(e);
  } finally {
    changing.value = false;
  }
}
function formatTime(value: string) {
  return new Date(value.endsWith("Z") ? value : value + "Z").toLocaleString(
    "zh-CN",
    { hour12: false },
  );
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>个人中心</h1>
      <p>管理账号安全，查看自己的操作记录。</p>
    </div>
    <el-button :loading="busy" @click="load">刷新</el-button>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-alert v-if="notice" :title="notice" type="success" :closable="false" />
  <section class="account-section" aria-labelledby="account-security">
    <h2 id="account-security">账号安全</h2>
    <p>当前账号：{{ me?.username || "正在读取…" }}</p>
    <form class="password-form" @submit.prevent="changePassword">
      <label for="profile-current"
        >当前密码<el-input
          id="profile-current"
          v-model="oldPassword"
          type="password"
          show-password
          autocomplete="current-password"
          required
      /></label>
      <label for="profile-new"
        >新密码<el-input
          id="profile-new"
          v-model="newPassword"
          type="password"
          show-password
          autocomplete="new-password"
          minlength="10"
          maxlength="128"
          placeholder="10–128 个字符"
          required
      /></label>
      <el-button type="primary" native-type="submit" :loading="changing"
        >修改密码</el-button
      >
    </form>
    <p class="muted">
      请使用独立的密码。修改密码后，其他已登录会话可能在一段时间内继续有效。
    </p>
  </section>
  <section class="account-section" aria-labelledby="personal-log-title">
    <h2 id="personal-log-title">我的操作日志</h2>
    <p class="muted">共 {{ logTotal }} 条，仅显示当前账号的操作。</p>
    <el-table
      :data="logs"
      :max-height="480"
      class="personal-log-table"
      empty-text="暂无操作记录"
    >
      <el-table-column prop="created_at" label="时间" min-width="185"
        ><template #default="scope">{{
          formatTime(scope.row.created_at)
        }}</template></el-table-column
      >
      <el-table-column prop="action" label="操作" min-width="170"
        ><template #default="scope">{{
          actionNames[scope.row.action] || scope.row.action
        }}</template></el-table-column
      >
      <el-table-column
        prop="resource_id"
        label="关联记录"
        min-width="210"
        show-overflow-tooltip
      />
      <el-table-column
        prop="request_id"
        label="请求编号"
        min-width="210"
        show-overflow-tooltip
      />
    </el-table>
    <el-pagination
      v-model:current-page="logPage"
      :page-size="50"
      :total="logTotal"
      layout="prev,pager,next"
      @current-change="changePage"
    />
  </section>
</template>
<style scoped>
.account-section {
  margin-top: 28px;
  min-width: 0;
}
.password-form {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 16px;
  margin: 16px 0;
}
.password-form label {
  margin: 0;
  width: 260px;
  max-width: 100%;
}
.password-form .el-input {
  margin-top: 8px;
}
.personal-log-table {
  margin-top: 16px;
  max-width: 100%;
}
@media (max-width: 640px) {
  .password-form label {
    width: 100%;
  }
}
</style>
