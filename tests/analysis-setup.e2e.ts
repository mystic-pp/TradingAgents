import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

test('用中文配置 NVDA 分析', { timeout: 180_000 }, async ({ app, screen }) => {
  await app.open('/');

  const terminal = screen.getByRole('region', 'TradingAgents 终端');
  const input = screen.getByRole('textbox', '终端输入');

  await expect(screen.getByRole('heading', 'TradingAgents 分析终端')).toBeVisible();
  await expect(terminal).toContainText('Welcome to TradingAgents', { timeout: 30_000 });
  await expect(terminal).toContainText('[SPY]:');

  await input.pressSequentially('NVDA');
  await input.press('Enter');

  await expect(terminal).toContainText('[SPY]: NVDA');
  await expect(terminal).toContainText(/\[\d{4}-\d{2}-\d{2}\]:/);
  await input.press('Enter');

  await expect(terminal).toContainText('English (default)');
  await input.press('ArrowDown');
  await input.press('Enter');

  await expect(terminal).toContainText('Chinese (中文)');
  await expect(terminal).toContainText('Market Analyst');
  await input.press('Space');
  await input.press('Enter');

  await expect(terminal).toContainText('Selected analysts: market');
  await expect(terminal).toContainText('Shallow - Quick research');
  await input.press('Enter');

  await expect(terminal).toContainText('Step 6: LLM Provider');
  await expect(terminal).toContainText('Select your LLM Provider');
});
