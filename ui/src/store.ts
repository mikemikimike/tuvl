import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { ConfigKind } from './types'

// Auto-expire the persisted dev key after this many ms of inactivity.
// 15 minutes matches typical short-lived dev sessions and limits exposure
// if a developer walks away from an unlocked workstation.
const IDLE_EXPIRY_MS = 15 * 60 * 1000

interface UIState {
  // Dev session key entered on the login screen
  devKey: string | null
  setDevKey: (key: string | null) => void

  // Wall-clock timestamp of the most recent authenticated activity.  Used by
  // the rehydration hook below to drop a stale key on page reload.
  lastSeen: number | null
  touch: () => void

  // Currently selected item in any sidebar
  selected: { kind: ConfigKind; name: string } | null
  setSelected: (kind: ConfigKind, name: string) => void
  clearSelected: () => void

  // Sidebar open/closed
  sidebarOpen: boolean
  toggleSidebar: () => void

  // Validation panel
  validationOpen: boolean
  toggleValidation: () => void

  // Theme
  theme: 'dark' | 'light'
  toggleTheme: () => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      devKey: null,
      setDevKey: (key) =>
        set({ devKey: key, lastSeen: key ? Date.now() : null }),

      lastSeen: null,
      touch: () => set((s) => (s.devKey ? { lastSeen: Date.now() } : s)),

      selected: null,
      setSelected: (kind, name) => set({ selected: { kind, name } }),
      clearSelected: () => set({ selected: null }),

      // the icon rail by default: pages (the workflow canvas above all) get the width
      sidebarOpen: false,
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

      validationOpen: false,
      toggleValidation: () => set((s) => ({ validationOpen: !s.validationOpen })),

      theme: 'dark' as const,
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
    }),
    {
      name: 'tuvl-ui',
      // sessionStorage clears when the tab closes, so the dev key never
      // outlives the browser session.  Theme is also session-scoped; that's
      // an acceptable trade for the security gain.
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        devKey: state.devKey,
        lastSeen: state.lastSeen,
        theme: state.theme,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state || !state.devKey) return
        if (state.lastSeen && Date.now() - state.lastSeen > IDLE_EXPIRY_MS) {
          // Drop the stored key; the user will be returned to the login page.
          state.devKey = null
          state.lastSeen = null
        }
      },
    },
  ),
)

// Idle-expiry watchdog — runs once at module load.  Checks the timestamp
// every minute and clears the dev key after IDLE_EXPIRY_MS without any
// ``touch()`` call.  Activity hooks should call ``touch()`` on user input.
if (typeof window !== 'undefined') {
  setInterval(() => {
    const s = useUIStore.getState()
    if (s.devKey && s.lastSeen && Date.now() - s.lastSeen > IDLE_EXPIRY_MS) {
      s.setDevKey(null)
    }
  }, 60_000)
  const touch = () => useUIStore.getState().touch()
  window.addEventListener('mousemove', touch, { passive: true })
  window.addEventListener('keydown', touch, { passive: true })
}
