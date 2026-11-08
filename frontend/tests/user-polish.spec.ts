import { test, expect } from '@playwright/test';

test('个人中心、长日志侧栏、滑动导航及全部模块表单布局', async ({ page, request }) => {
  test.setTimeout(180000);
  const prefix = 'http://127.0.0.1:8000/api/v1';
  const account = { username: 'workspace_' + Date.now().toString(36), password: 'workspace-test-password' };
  expect((await request.post(prefix + '/auth/register', { data: account })).status()).toBe(201);
  const token = (await (await request.post(prefix + '/auth/login', { data: account })).json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (await request.post(prefix + '/projects', { headers, data: { name: '布局检查项目' } })).json();
  for (let index = 0; index < 55; index++) {
    expect((await request.put(prefix + '/projects/' + project.id, { headers, data: { name: '布局检查项目', description: `操作记录${index}` } })).status()).toBe(200);
  }
  await page.goto('/login');
  await expect(page.locator('body')).not.toContainText('第一阶段');
  await page.addInitScript(value => sessionStorage.setItem('atl_token', value), token);
  await page.goto('/management');
  await expect(page.getByRole('heading', { name: '个人中心', exact: true })).toBeVisible();
  await expect(page.locator('.personal-log-table .el-table__body-wrapper')).toBeVisible();
  await expect(page.getByText('用户角色', { exact: true })).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('管理员');
  const before = await page.locator('.nav-bottom').boundingBox();
  await page.mouse.wheel(0, 2000);
  const after = await page.locator('.nav-bottom').boundingBox();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(2);
  expect(after!.y + after!.height).toBeLessThanOrEqual(902);
  await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible();
  const indicator = page.locator('.nav-indicator');
  const oldTransform = await indicator.evaluate(el => getComputedStyle(el).transform);
  const securityLink = page.getByRole('navigation').getByRole('link', { name: '安全测试', exact: true });
  await securityLink.click();
  await securityLink.hover();
  expect(await securityLink.evaluate(el => getComputedStyle(el).textDecorationLine)).toBe('none');
  await expect.poll(() => indicator.evaluate(el => getComputedStyle(el).transform)).not.toBe(oldTransform);
  const transition = await indicator.evaluate(el => getComputedStyle(el).transitionProperty);
  expect(transition).toContain('transform');
  for (const route of ['/security', '/generate']) {
    await page.goto(route);
    const boxes = page.locator('.el-checkbox-group .el-checkbox');
    await expect(boxes.first()).toBeVisible();
    await expect.poll(async () => { const a = await page.locator("nav a.router-link-active").boundingBox(); const b = await indicator.boundingBox(); return Math.abs(a!.y - b!.y) + Math.abs(a!.height - b!.height); }).toBeLessThan(2);
    const first = await boxes.nth(0).boundingBox(), second = await boxes.nth(1).boundingBox();
    expect(Math.abs(first!.y - second!.y)).toBeLessThan(2);
    await page.screenshot({ path: `../docs/evidence/user-polish-${route.slice(1)}-1440.png`, fullPage: true });
  }
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ['/projects', '/agents', '/cases', '/tasks', '/knowledge', '/security', '/traces', '/analysis', '/management', '/generate', '/models', '/demo', '/system']) {
      await page.goto(route);
      await expect(page.locator('h1')).toBeVisible();
      await expect(page.locator('body')).not.toContainText('管理员');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (route === '/models') {
        await expect(page.getByText('高级参数', { exact: true })).toHaveCount(0);
        await expect(page.getByRole('spinbutton')).toHaveCount(0);
        await expect(page.getByRole('button', { name: '测试', exact: true })).toBeVisible();
      }
      if (route === '/management') await page.screenshot({ path: `../docs/evidence/user-polish-personal-${width}.png`, fullPage: true });
    }
    if (width < 1100) {
      await page.getByRole('button', { name: '菜单', exact: true }).click();
      await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible();
      await expect(page.getByRole('navigation')).toBeVisible();
      const footer = await page.locator('.nav-bottom').boundingBox();
      expect(footer!.y + footer!.height).toBeLessThanOrEqual(902);
      await page.getByRole('button', { name: '关闭菜单', exact: true }).click();
    }
  }
});
