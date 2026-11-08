import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { writeFile } from "node:fs/promises";

test("普通用户：真实HTTP测试、密钥显隐、保存编辑、账号隔离与三种宽度", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const calls: string[] = [];
  const provider = createServer(async (incoming, outgoing) => {
    let raw = "";
    for await (const chunk of incoming) raw += chunk;
    const data = JSON.parse(raw);
    calls.push(incoming.url || "");
    outgoing.setHeader("Content-Type", "application/json");
    if (incoming.headers.authorization !== "Bearer browser-protocol-key") {
      outgoing.writeHead(401);
      outgoing.end(
        JSON.stringify({
          error: { message: "invalid key", type: "invalid_api_key" },
        }),
      );
      return;
    }
    outgoing.end(
      JSON.stringify({
        id: "browser-protocol-only",
        object: "chat.completion",
        created: 1,
        model: data.model,
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: "OK" },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      }),
    );
  });
  await new Promise<void>((resolve) =>
    provider.listen(0, "127.0.0.1", resolve),
  );
  const providerUrl = `http://127.0.0.1:${(provider.address() as AddressInfo).port}/v1`;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const prefix = "http://127.0.0.1:8000/api/v1";
  const credentials = {
    username: "personal_ui_" + Date.now().toString(36),
    password: "personal-ui-test-password",
  };
  try {
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
    const headers = { Authorization: `Bearer ${token}` };
    expect(
      (await (await request.get(prefix + "/auth/me", { headers })).json()).role,
    ).toBe("tester");
    await page.addInitScript(
      (value) => sessionStorage.setItem("atl_token", value),
      token,
    );
    await page.goto("/models");
    await page.getByLabel("配置名称", { exact: true }).fill("我的协议模型");
    await page.getByLabel("模型接口 URL", { exact: true }).fill(providerUrl);
    await page.getByLabel("模型名称", { exact: true }).fill("protocol-only");
    const key = page.getByLabel("API 密钥", { exact: true });
    await key.fill("wrong-protocol-key");
    await expect(key).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "显示密钥", exact: true }).click();
    await expect(key).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "隐藏密钥", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "测试", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "测试未通过" }),
    ).toContainText("密钥无效");
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeDisabled();
    await key.fill("browser-protocol-key");
    await page.getByRole("button", { name: "测试", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "测试通过" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeEnabled();
    await page.getByLabel("模型名称", { exact: true }).fill("protocol-edited");
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "测试", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "保存配置", exact: true }).click();
    await expect(page.locator(".model-row")).toContainText("我的协议模型");
    await expect(key).toHaveValue("");
    await page.reload();
    await page
      .locator(".model-row")
      .getByRole("button", { name: "编辑", exact: true })
      .click();
    await expect(key).toHaveValue("");
    await expect(key).toHaveAttribute("placeholder", /留空/);
    await page
      .getByLabel("配置名称", { exact: true })
      .fill("我的协议模型已编辑");
    await page.getByRole("button", { name: "测试", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "保存配置", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "保存配置", exact: true }).click();
    await expect(page.locator(".model-row")).toContainText(
      "我的协议模型已编辑",
    );
    const listing = await request.get(prefix + "/models", { headers });
    const listingText = await listing.text();
    expect(listingText).not.toContain("browser-protocol-key");
    const saved = JSON.parse(listingText).items[0];
    const other = {
      username: credentials.username + "_b",
      password: credentials.password,
    };
    expect(
      (await request.post(prefix + "/auth/register", { data: other })).status(),
    ).toBe(201);
    const otherToken = (
      await (await request.post(prefix + "/auth/login", { data: other })).json()
    ).access_token;
    const otherHeaders = { Authorization: `Bearer ${otherToken}` };
    expect(
      (
        await (
          await request.get(prefix + "/models", { headers: otherHeaders })
        ).json()
      ).items,
    ).toEqual([]);
    expect(
      (
        await request.put(prefix + "/models/" + saved.id, {
          headers: otherHeaders,
          data: {
            ...saved,
            api_key: null,
            id: undefined,
            has_api_key: undefined,
          },
        })
      ).status(),
    ).toBe(404);
    expect(
      calls.filter((path) => path === "/v1/chat/completions").length,
    ).toBeGreaterThanOrEqual(4);
    await expect(page.locator(".el-message")).toHaveCount(0);
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `../docs/evidence/personal-models-${width}.png`,
        fullPage: true,
      });
    }
    const snapshot = await page.evaluate(() => {
      const clone = document.documentElement.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("script").forEach((script) => script.remove());
      return "<!doctype html>" + clone.outerHTML;
    });
    await writeFile(
      "../.local/personal-models-rendered.html",
      snapshot,
      "utf8",
    );
    expect(errors).toEqual([]);
  } finally {
    await new Promise<void>((resolve, reject) =>
      provider.close((error) => (error ? reject(error) : resolve())),
    );
  }
});
