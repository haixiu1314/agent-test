import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "./style.css";
import "./controls.css";
import App from "./App.vue";
import Login from "./views/Login.vue";
import Projects from "./views/Projects.vue";
import Agents from "./views/Agents.vue";
import System from "./views/System.vue";
import Cases from "./views/Cases.vue";
import Generate from "./views/Generate.vue";
import Models from "./views/Models.vue";
import Demo from "./views/Demo.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: Login },
    { path: "/", redirect: "/projects" },
    { path: "/projects", component: Projects },
    { path: "/agents", component: Agents },
    { path: "/system", component: System },
    { path: "/cases", component: Cases },
    { path: "/tasks", component: () => import("./views/Tasks.vue") },
    { path: "/knowledge", component: () => import("./views/Knowledge.vue") },
    { path: "/security", component: () => import("./views/Security.vue") },
    { path: "/traces", component: () => import("./views/Traces.vue") },
    { path: "/analysis", component: () => import("./views/Analysis.vue") },
    { path: "/management", component: () => import("./views/Management.vue") },
    { path: "/generate", component: Generate },
    { path: "/models", component: Models },
    { path: "/demo", component: Demo },
  ],
});
router.beforeEach((to) => {
  if (to.path !== "/login" && !sessionStorage.getItem("atl_token"))
    return "/login";
});
createApp(App).use(router).use(ElementPlus).mount("#app");
