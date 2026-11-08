import { test, expect } from "@playwright/test";

test("第三阶段：创建、执行、结果依据、失败重跑、取消与三种宽度", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const prefix = "http://127.0.0.1:8000/api/v1",
    suffix = Date.now().toString(36);
  const credentials = {
    username: "task_e2e_" + suffix,
    password: "stage3-browser-password",
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
  const project = await (
    await request.post(prefix + "/projects", {
      headers,
      data: { name: "执行浏览器验收_" + suffix },
    })
  ).json();
  await request.post(prefix + "/agents", {
    headers,
    data: {
      project_id: project.id,
      name: "协议流程目标（非 AI）",
      kind: "python",
      adapter_name: "protocol_echo",
    },
  });
  const suite = await (
    await request.post(prefix + "/suites", {
      headers,
      data: { project_id: project.id, name: "浏览器执行套件" },
    })
  ).json();
  for (let i = 0; i < 2; i++) {
    expect(
      (
        await request.post(prefix + "/cases?expected_revision=" + (i + 1), {
          headers,
          data: {
            suite_id: suite.id,
            name: i ? "失败用例" : "通过用例",
            test_type: "functional",
            scenario: "任务浏览器验证",
            user_input: "你好",
            expected_behavior: "回应",
            expected_result: "你好",
            rules: {
              evaluators: ["rules"],
              rubric: "按包含词判断",
              must_include: [i ? "不会出现的内容" : "你好"],
            },
          },
        })
      ).status(),
    ).toBe(201);
  }
  await page.goto("/login");
  await page.evaluate((t) => sessionStorage.setItem("atl_token", t), token);
  await page.goto("/tasks");
  await page.getByRole("button", { name: "创建任务", exact: true }).click();
  await page
    .getByRole("textbox", { name: "任务名称", exact: true })
    .fill("浏览器批量执行");
  await page.getByRole("button", { name: "保存任务", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "浏览器批量执行", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "开始", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "浏览器批量执行 · 已完成", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "任务结果" })).toContainText(
    "通过 1 · 失败 1",
  );
  await page
    .getByRole("button", { name: "结果详情", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "评估依据", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".el-dialog").filter({ hasText: "用例执行结果" }),
  ).toContainText("规则检查");
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await page.getByRole("button", { name: "重跑未通过", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "浏览器批量执行 · 重跑 · 待执行",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "任务结果" })).toContainText(
    "已结束 0 / 1",
  );
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "浏览器批量执行 · 重跑 · 已取消",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".el-message")).toHaveCount(0);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("heading", { name: "测试执行", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `../docs/evidence/stage3-tasks-${width}.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});
