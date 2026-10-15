import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

test('光猫管理页可以打开', async ({ app, browser }) => {
  await app.open('/');
  await expect(browser.locator('body')).toBeVisible();
});
