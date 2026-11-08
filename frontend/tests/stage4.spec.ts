import { test, expect } from "@playwright/test";

test("第四阶段：批量上传、来源分块、重复与日期检查、人工确认、问题集、缺配置与响应式", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const prefix = "http://127.0.0.1:8000/api/v1";
  const credentials = {
    username: "rag_e2e_" + Date.now().toString(36),
    password: "stage4-browser-password",
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
  await request.post(prefix + "/projects", {
    headers,
    data: { name: "RAG 浏览器验收" },
  });
  await page.goto("/login");
  await page.evaluate((t) => sessionStorage.setItem("atl_token", t), token);
  await page.goto("/knowledge");
  await page.getByRole("button", { name: "创建知识库", exact: true }).click();
  await page
    .getByRole("textbox", { name: "知识库名称", exact: true })
    .fill("浏览器知识库");
  await page.getByRole("button", { name: "保存知识库", exact: true }).click();
  await expect(
    page.getByText("浏览器知识库 · 1536 维", { exact: false }),
  ).toBeVisible();
  const text =
    "产品保修期为一年，凭购买凭证申请售后服务。有效期至 2020-01-01。";
  await page.getByLabel("批量上传文档", { exact: true }).setInputFiles([
    { name: "制度.txt", mimeType: "text/plain", buffer: Buffer.from(text) },
    { name: "副本.md", mimeType: "text/markdown", buffer: Buffer.from(text) },
  ]);
  await expect(
    page.getByText("制度.txt：解析成功，1 个分块", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "查看分块", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText(text.normalize("NFKC"));
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await page
    .getByRole("button", { name: "向量入库", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "向量入库未完成" }),
  ).toContainText("embedding_not_configured");
  await page.getByRole("tab", { name: "知识质量", exact: true }).click();
  await page.getByRole("button", { name: "开始质量检查", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "完全重复", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "有效期已过候选", exact: true }).first(),
  ).toBeVisible();
  const duplicate = page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "完全重复", exact: true }) });
  await duplicate
    .getByRole("button", { name: "来源详情", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("制度.txt");
  await expect(page.getByRole("dialog")).toContainText("副本.md");
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await duplicate
    .getByRole("button", { name: "确认问题", exact: true })
    .click();
  await expect(duplicate).toContainText("已确认");
  await page.getByRole("tab", { name: "问题集", exact: true }).click();
  await page.getByRole("button", { name: "创建问题集", exact: true }).click();
  await page
    .getByRole("textbox", { name: "问题集名称", exact: true })
    .fill("手工保修问题");
  await page
    .getByRole("textbox", { name: "问题与标准答案", exact: true })
    .fill(JSON.stringify([{ question: "保修期多久？", reference: "一年" }]));
  await page.getByRole("button", { name: "保存问题集", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "手工保修问题", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "根据文档生成问题", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "AI 生成未完成" }),
  ).toContainText("model_not_configured");
  await page.getByRole("tab", { name: "检索与评估", exact: true }).click();
  await page
    .getByRole("textbox", { name: "检索问题", exact: true })
    .fill("保修期多久？");
  await page.getByRole("button", { name: "检索片段", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "没有已索引文档" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "执行 RAGAS 评估", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "本次结果 · 失败", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("错误码：model_not_configured", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "知识质量", exact: true }).click();
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `../docs/evidence/stage4-knowledge-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
  await page.getByRole("tab", { name: "文档与分块", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "制度.txt", exact: true }) })
    .getByRole("button", { name: "删除文档", exact: true })
    .click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "制度.txt", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
