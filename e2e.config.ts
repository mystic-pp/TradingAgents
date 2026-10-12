import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';
import { gateway } from 'ai';

const root = fileURLToPath(new URL('.', import.meta.url));

export default {
  workers: 1,
  timeout: 180_000,
  assertionTimeout: 20_000,
  agents: {
    default: {
      // 示例测试和配置向导测试不调用模型。确定供应商后再换成对应的 provider。
      model: gateway('openai/gpt-6-luna-fast'),
      system: '你是严谨的测试代理。每一步都要对照屏幕上的文字确认结果。',
      context:
        '页面标题是「TradingAgents 分析终端」。主区域是命令行画面，底部「终端输入」接收按键。向导顺序是股票代码、分析日期、输出语言、分析师、研究深度、模型供应商和模型。输出语言里的中文选项显示为 Chinese (中文)。回车确认当前项，空格勾选分析师。',
    },
  },
  targets: [
    {
      engine: web({ viewport: { width: 1280, height: 900 } }),
      app: {
        url: 'http://127.0.0.1:0',
        readyUrl: 'http://127.0.0.1:{port}/health',
        command: {
          executable: 'python3',
          args: [path.join(root, 'scripts/e2e_cli_server.py'), '--port', '{port}'],
          cwd: root,
          env: {
            LANG: 'C.UTF-8',
            LC_ALL: 'C.UTF-8',
            PYTHONUNBUFFERED: '1',
          },
          startupTimeout: 60_000,
          log: '.e2e/logs/app.log',
        },
      },
    },
  ],
} satisfies E2EConfig;
