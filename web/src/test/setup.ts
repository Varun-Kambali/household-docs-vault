// Run before every test file (vite.config.ts).
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest has no global afterEach unless asked, so Testing Library cannot clean up by itself.
afterEach(() => {
  cleanup()
})

// React's act() warns unless the test says it is running in a test environment.
declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
