import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

test('光猫登录页可以打开', async ({ app, browser }) => {
  await app.open('/admin/login.asp');
  await expect(browser).toHaveURL(/\/admin\/login\.asp(?:[?#]|$)/);
  await expect(browser.locator('body')).toBeVisible();
});
