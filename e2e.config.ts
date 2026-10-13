import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';
import { gateway } from 'ai';

// Plain HTTP is legal only for a loopback base URL. The ONT stays on
// http://192.168.1.1; scripts/ont-proxy.mjs forwards the loopback port to it.
const ontOrigin = process.env.ONT_ORIGIN ?? 'http://192.168.1.1';

export default {
  agents: {
    default: {
      model: gateway('openai/gpt-6-luna-fast'),
      system: 'You are a thorough QA agent. Verify every outcome.',
    },
  },
  targets: [{
    engine: web(),
    app: {
      url: 'http://127.0.0.1:0',
      readyUrl: 'http://127.0.0.1:{port}/admin/login.asp',
      command: {
        executable: 'node',
        args: ['scripts/ont-proxy.mjs', '--port', '{port}'],
        env: { ONT_ORIGIN: ontOrigin },
        startupTimeout: 20_000,
        log: '.e2e/logs/app.log',
      },
    },
  }],
} satisfies E2EConfig;
