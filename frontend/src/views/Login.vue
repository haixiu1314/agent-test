<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { api, message } from "../api";
const registering = ref(false),
  username = ref(""),
  password = ref(""),
  busy = ref(false),
  error = ref(""),
  notice = ref(""),
  router = useRouter();
async function submit() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const payload = { username: username.value, password: password.value };
    if (registering.value) {
      await api.post("/auth/register", payload);
      registering.value = false;
      notice.value = "注册成功，请使用刚才的账号登录";
      password.value = "";
    } else {
      const result = await api.post("/auth/login", payload);
      sessionStorage.setItem("atl_token", result.data.access_token);
      await router.push("/projects");
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="login-page">
    <div class="login-intro">
      <div class="brand">AgentTestLab</div>
      <h1>智能体测试空间</h1>
      <p>从真实接入开始，让每次测试都有据可查。</p>
      <ul>
        <li>管理测试项目与业务场景</li>
        <li>配置 HTTP 与受控 Python Agent</li>
        <li>保存配置版本，验证连接状态</li>
      </ul>
    </div>
    <section class="login-form">
      <h2>{{ registering ? "创建测试账号" : "登录工作空间" }}</h2>
      <p class="muted">
        {{
          registering
            ? "注册后即可创建自己的测试项目。"
            : "使用你的账号继续管理测试项目。"
        }}
      </p>
      <form @submit.prevent="submit">
        <label for="username">用户名</label
        ><el-input
          id="username"
          v-model="username"
          autocomplete="username"
          maxlength="50"
          required
        />
        <p class="field-hint">3–50 位英文字母、数字、下划线或短横线</p>
        <label for="password">密码</label
        ><el-input
          id="password"
          v-model="password"
          type="password"
          show-password
          :autocomplete="registering ? 'new-password' : 'current-password'"
          minlength="10"
          maxlength="128"
          required
        />
        <p class="field-hint">10–128 个字符</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="notice" class="success" role="status">{{ notice }}</p>
        <el-button type="primary" native-type="submit" :loading="busy">{{
          registering ? "注册账号" : "登录"
        }}</el-button
        ><button
          type="button"
          class="text-button"
          @click="
            registering = !registering;
            error = '';
            notice = '';
          "
        >
          {{ registering ? "已有账号，返回登录" : "没有账号？创建账号" }}
        </button>
      </form>
    </section>
  </div>
</template>
