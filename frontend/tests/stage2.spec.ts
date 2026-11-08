import { test, expect } from "@playwright/test";

test("第二阶段：用例增删改、导入、快照、未配置模型与响应式页面", async ({
  page,
  request,
}) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (e) => browserErrors.push(e.message));
  const suffix = Date.now().toString(36),
    username = "case_e2e_" + suffix,
    password = "stage2-e2e-password";
  await request.post("http://127.0.0.1:8000/api/v1/auth/register", {
    data: { username, password },
  });
  const authResponse = await request.post(
    "http://127.0.0.1:8000/api/v1/auth/login",
    { data: { username, password } },
  );
  const token = (await authResponse.json()).access_token;
  const headers = { Authorization: "Bearer " + token };
  await request.post("http://127.0.0.1:8000/api/v1/projects", {
    headers,
    data: { name: "用例浏览器验收_" + suffix },
  });
  await page.goto("/login");
  await page.evaluate((t) => sessionStorage.setItem("atl_token", t), token);
  await page.goto("/cases");
  await page.getByRole("button", { name: "创建套件", exact: true }).click();
  await page.locator(".el-message-box input").fill("浏览器测试套件");
  await page.getByRole("button", { name: "OK", exact: true }).click();
  await page.getByRole("button", { name: "新增用例", exact: true }).click();
  await page.getByLabel("用例名称", { exact: true }).fill("浏览器问候用例");
  await page.getByLabel("测试场景", { exact: true }).fill("新用户问候");
  await page
    .getByLabel("用户输入（边界测试可留空）", { exact: true })
    .fill("你好");
  await page.getByLabel("预期行为", { exact: true }).fill("礼貌回应");
  await page.getByLabel("预期结果", { exact: true }).fill("包含问候");
  await page.getByRole("button", { name: "保存用例", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "浏览器问候用例", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("用例名称", { exact: true }).fill("修改后的问候用例");
  await page.getByRole("button", { name: "保存用例", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "修改后的问候用例", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "版本记录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "版本 3 · 1 条用例", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await page.getByRole("button", { name: "导入 / 导出", exact: true }).click();
  await page.getByLabel("文件内容", { exact: true }).fill("[{}]");
  await page.getByRole("button", { name: "校验并导入", exact: true }).click();
  await expect(page.locator(".el-message--error")).toContainText("导入失败");
  const draft = {
    name: "导入的问候用例",
    test_type: "functional",
    scenario: "文件导入",
    user_input: "你好",
    expected_behavior: "回应问候",
    expected_result: "礼貌回复",
    rules: { evaluators: ["rules"], rubric: "按问候判断" },
  };
  await page.getByLabel("选择 JSON / CSV 文件").setInputFiles({
    name: "cases.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify([draft])),
  });
  await page.getByRole("button", { name: "校验并导入", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "导入的问候用例", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "导入 / 导出", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前套件", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("test-cases.json");
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await expect(page.locator(".el-message")).toHaveCount(0);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({
      path: `../docs/evidence/stage2-cases-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("link", { name: "AI 生成用例", exact: true }).click();
  await expect(page.getByText("请先在“模型配置”添加并测试你的模型，再返回选择生成模型。")).toBeVisible();
  await page
    .getByText("待测 Agent 的提示词、工具与接口", { exact: true })
    .click();
  await page
    .getByLabel("从 TXT / Markdown 文件读取提示词")
    .setInputFiles({
      name: "prompt.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("你是企业知识助手。"),
    });
  await expect(
    page.getByLabel("系统提示词（作为待测数据）", { exact: true }),
  ).toHaveValue("你是企业知识助手。");
  await page
    .getByLabel("业务需求", { exact: true })
    .fill("验证普通问候场景，保持礼貌。");
  await page
    .getByRole("button", { name: "调用模型生成草稿", exact: true })
    .click();
  await expect(page.locator(".inline-error[role=alert]")).toContainText(
    "model_not_configured",
  );
  await page.screenshot({
    path: "../docs/evidence/stage2-generation-1440.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "模型配置", exact: true }).click();
  await expect(page.getByLabel("模型接口 URL", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加模型", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "企业助手演示", exact: true }).click();
  await page.getByLabel("你的问题", { exact: true }).fill("年假如何申请？");
  await page.getByRole("button", { name: "发送给模型", exact: true }).click();
  await expect(page.locator(".inline-error[role=alert]")).toContainText(
    "模型尚未配置",
  );
  await page.screenshot({
    path: "../docs/evidence/stage2-demo-1440.png",
    fullPage: true,
  });
  for (const path of ["generate", "models", "demo"]) {
    for (const width of [768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/" + path);
      await expect(page.locator("h1")).toBeVisible();
      await page.screenshot({
        path: `../docs/evidence/stage2-${path}-${width}.png`,
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/cases");
  await page.getByRole("button", { name: "删除", exact: true }).first().click();
  await page.getByRole("button", { name: "OK", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "修改后的问候用例", exact: true }),
  ).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});
