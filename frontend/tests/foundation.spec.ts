import { test, expect } from "@playwright/test";

test("注册登录、项目管理、Agent 连接和版本快照", async ({ page }) => {
  const suffix = Date.now().toString(36);
  await page.goto("/login");
  await page.getByRole("button", { name: "没有账号？创建账号" }).click();
  await page.getByLabel("用户名", { exact: true }).fill("e2e_" + suffix);
  await page.getByLabel("密码", { exact: true }).fill("e2e-password-123");
  await page.getByRole("button", { name: "注册账号", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("注册成功");
  await page.getByLabel("密码", { exact: true }).fill("e2e-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "测试项目", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await page.getByLabel("项目名称").fill("浏览器验收项目_" + suffix);
  await page.getByLabel("项目描述").fill("自动化验收生成，可按文档删除。");
  await page.getByRole("button", { name: "保存项目", exact: true }).click();
  await page
    .getByRole("button", { name: "浏览器验收项目_" + suffix, exact: true })
    .click();
  await page.getByRole("button", { name: "接入 Agent", exact: true }).click();
  await page.getByLabel("Agent 名称", { exact: true }).fill("协议测试 Agent");
  await page.getByLabel("接入方式", { exact: true }).click();
  await page
    .getByRole("option", { name: "受控 Python 协议验证（非 AI）" })
    .click();
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "协议测试 Agent v1" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "协议测试 Agent · 连接成功" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("版本说明", { exact: true }).fill("浏览器修改验收");
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await page.getByRole("button", { name: "版本", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "v2 · 浏览器修改验收" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "v1 · 初始配置" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close this dialog" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.locator(".el-message")).toHaveCount(0);
  await page.screenshot({
    path: "../docs/evidence/agents-desktop.png",
    fullPage: true,
  });
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({
      path: `../docs/evidence/agents-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "接入你的第一个 Agent" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "测试项目", exact: true }).click();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "还没有测试项目" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(
    page.getByRole("heading", { name: "登录工作空间" }),
  ).toBeVisible();
});

test("错误密码显示真实后端错误", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名", { exact: true }).fill("unknown_account");
  await page.getByLabel("密码", { exact: true }).fill("wrong-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("用户名或密码错误");
});
