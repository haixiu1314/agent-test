import { test, expect } from "@playwright/test";

test("最终交付：报告导出、回归、时间线与关系图、安全任务、管理与三种宽度", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const prefix = "http://127.0.0.1:8000/api/v1",
    credentials = {
      username: "final_ui_" + Date.now().toString(36),
      password: "final-browser-password",
    };
  expect(
    (
      await request.post(prefix + "/auth/register", { data: credentials })
    ).status(),
  ).toBe(201);
  const token = (
    await (
      await request.post(prefix + "/auth/login", { data: credentials })
    ).json()
  ).access_token;
  const headers = { Authorization: "Bearer " + token };
  const post = async (path: string, data: any) => {
    const r = await request.post(prefix + path, { headers, data });
    expect(r.status()).toBe(201);
    return r.json();
  };
  const project = await post("/projects", { name: "最终浏览器验收" });
  const agent = await post("/agents", {
    project_id: project.id,
    name: "浏览器协议目标（非 AI）",
    kind: "python",
    adapter_name: "protocol_echo",
  });
  const suite = await post("/suites", {
    project_id: project.id,
    name: "最终浏览器套件",
  });
  const draft = {
    name: "问候验证",
    test_type: "functional",
    scenario: "最终 UI 验证",
    user_input: "你好",
    expected_behavior: "回应输入",
    expected_result: "你好",
    rules: {
      evaluators: ["rules"],
      rubric: "包含你好",
      must_include: ["你好"],
    },
  };
  await post("/cases?expected_revision=1", { ...draft, suite_id: suite.id });
  const taskIds: string[] = [];
  for (const name of ["浏览器基线", "浏览器候选"]) {
    const task = await post("/test-tasks", {
      name,
      agent_id: agent.id,
      suite_id: suite.id,
    });
    taskIds.push(task.id);
    expect(
      (
        await request.post(prefix + "/test-tasks/" + task.id + "/start", {
          headers,
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(prefix + "/test-tasks/" + task.id, { headers })
            ).json()
          ).status,
      )
      .toBe("completed");
  }
  const result = (
    await (
      await request.get(prefix + "/test-tasks/" + taskIds[0] + "/results", {
        headers,
      })
    ).json()
  ).items[0];
  await page.goto("/login");
  await page.evaluate((t) => sessionStorage.setItem("atl_token", t), token);
  await page.goto("/analysis");
  await expect(
    page.getByRole("heading", { name: "质量分析与报告" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "生成冻结报告" }).click();
  await expect(page.getByText("已观测维度加权分：")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 PDF", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({
      path: `../docs/evidence/final-analysis-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("tab", { name: "版本回归" }).click();
  async function choose(label: string, text: string) {
    const control = page.getByRole("combobox", { name: label, exact: true });
    await control.click();
    const id = await control.getAttribute("aria-controls");
    await page
      .locator('[id="' + id + '"]')
      .getByRole("option", { name: text, exact: true })
      .click();
  }
  await choose("基线任务", "浏览器基线");
  await choose("候选任务", "浏览器候选");
  await page.getByRole("button", { name: "生成回归对比" }).click();
  await expect(page.getByText(/可比 1 条/)).toBeVisible();
  await page.goto("/traces?result=" + result.id);
  await expect(page.getByText(/目标内部工具事件不可观测/)).toBeVisible();
  await page.getByRole("tab", { name: "事件关系图" }).click();
  await expect(page.locator(".vue-flow__node").first()).toBeVisible();
  await page.screenshot({
    path: "../docs/evidence/final-trace-1440.png",
    animations: "disabled",
  });
  await page.getByRole("tab", { name: "两次轨迹差异" }).click();
  await page.getByLabel("候选轨迹 ID").fill(result.id);
  await page.getByRole("button", { name: "比较事件内容" }).click();
  await expect(page.getByText(/No Data|暂无数据/)).toBeVisible();
  const securitySuite = await post("/suites", {
    project_id: project.id,
    name: "安全浏览器套件",
  });
  await post("/cases?expected_revision=1", {
    ...draft,
    suite_id: securitySuite.id,
    test_type: "security",
    tags: ["prompt_injection"],
    rules: {
      evaluators: ["security_policy", "llm_judge"],
      rubric: "遵守安全策略",
      security_policy: "不泄露测试秘密",
    },
  });
  await page.goto("/security");
  await expect(
    page.getByRole("heading", { name: "安全测试", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "执行与风险" }).click();
  await choose("安全套件", "安全浏览器套件");
  await page.getByRole("button", { name: "创建隔离安全任务" }).click();
  await page.getByRole("button", { name: "开始 / 继续" }).first().click();
  await expect(
    page.getByText("unknown", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/evidence/final-security-1440.png",
    animations: "disabled",
  });
  await page.goto("/management");
  await expect(
    page.getByRole("heading", { name: "个人中心", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "我的操作日志", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "修改密码", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("用户角色", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "../docs/evidence/final-management-1440.png",
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});
