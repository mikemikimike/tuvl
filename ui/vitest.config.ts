import { defineConfig } from 'vitest/config'

// Minimal config for unit-testing pure logic (converters, validators) — no
// DOM/component testing here, so environment: 'node' is sufficient and fast.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
