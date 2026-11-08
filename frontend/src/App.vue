<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "./api";
const route = useRoute(),
  router = useRouter(),
  menu = ref(false),
  username = ref("");
const navigation = ref<HTMLElement | null>(null);
const indicator = ref({
  transform: "translateY(0px)",
  height: "0px",
  opacity: 0,
});
let observer: ResizeObserver | undefined;
function moveIndicator() {
  const active = navigation.value?.querySelector<HTMLElement>(
    "a.router-link-active",
  );
  if (active)
    indicator.value = {
      transform: `translateY(${active.offsetTop}px)`,
      height: `${active.offsetHeight}px`,
      opacity: 1,
    };
}
watch(
  () => [route.path, menu.value],
  async () => {
    await nextTick();
    moveIndicator();
  },
  { flush: "post" },
);
onMounted(() => {
  observer = new ResizeObserver(moveIndicator);
  if (navigation.value) observer.observe(navigation.value);
  moveIndicator();
});
watch(navigation, (element) => {
  observer?.disconnect();
  if (element) observer?.observe(element);
  nextTick(moveIndicator);
});
onBeforeUnmount(() => observer?.disconnect());
watch(
  () => route.path,
  async (path) => {
    menu.value = false;
    if (path !== "/login") {
      try {
        username.value = (await api.get("/auth/me")).data.username;
      } catch {
        username.value = "";
      }
    }
  },
  { immediate: true },
);
function logout() {
  sessionStorage.removeItem("atl_token");
  router.push("/login");
}
</script>
<template>
  <RouterView v-if="route.path === '/login'" />
  <div v-else class="shell">
    <aside :class="{ open: menu }">
      <div class="brand">
        <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
          <path
            d="M8 4v9L3 25q-1 3 3 3h20q4 0 3-3l-5-12V4M6 4h20M8 20h16M11 24h10"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linejoin="round"
          /></svg
        ><strong>AgentTestLab</strong>
      </div>
      <p class="workspace">智能体质量测试与安全审计</p>
      <nav ref="navigation" class="side-navigation" aria-label="主导航">
        <span
          class="nav-indicator"
          :style="indicator"
          aria-hidden="true"
        ></span>
        <RouterLink to="/projects">测试项目</RouterLink
        ><RouterLink to="/agents">Agent 接入</RouterLink
        ><RouterLink to="/cases">测试用例</RouterLink
        ><RouterLink to="/tasks">测试执行</RouterLink
        ><RouterLink to="/knowledge">RAG 知识库</RouterLink
        ><RouterLink to="/security">安全测试</RouterLink
        ><RouterLink to="/traces">轨迹审计</RouterLink
        ><RouterLink to="/analysis">质量分析与报告</RouterLink
        ><RouterLink to="/management">个人中心</RouterLink
        ><RouterLink to="/generate">AI 生成用例</RouterLink
        ><RouterLink to="/models">模型配置</RouterLink
        ><RouterLink to="/demo">企业助手演示</RouterLink
        ><RouterLink to="/system">运行状态</RouterLink>
      </nav>
      <div class="nav-bottom">
        <span>{{ username }}</span
        ><button @click="logout">退出登录</button>
      </div>
    </aside>
    <div class="main-wrap">
      <header class="topbar">
        <button class="menu-toggle" @click="menu = !menu" :aria-expanded="menu">
          {{ menu ? "关闭菜单" : "菜单" }}</button
        ><span>我的测试空间</span
        ><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noopener"
          >API 文档 ↗</a
        >
      </header>
      <main><RouterView /></main>
    </div>
  </div>
</template>
