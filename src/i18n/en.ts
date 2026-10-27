const en = {
  // Header
  "app.title": "Travel Decision Assistant",
  "app.subtitle": "Tell me where you are and what brands you need — I'll find the nearest mall",

  // Runtime mode badge (only served by the local dev runtime via /status)
  "status.demo": "Demo mode · no model",
  "status.mock": "Sample data",
  "status.demoMock": "Demo mode · sample data",
  "status.hint": "No model key configured: replies come from local rules, and map data is the built-in sample set (AMAP_MOCK=1) rather than live Amap results",

  // Empty state
  "empty.title": "Travel Decision Assistant",
  "empty.hint": "I can find malls near you, check whether they carry the brands you want, and rank them by distance. Tell me your location and the brands to get started.",
  "empty.features": "Amap Maps · Brand Check · Distance Ranking · Follow-ups",

  // Chat input
  "chat.placeholder": "Where are you, and what are you looking for...  ⏎ Send · Shift+⏎ Newline",
  "chat.hint": "Powered by OpenAI Agents SDK + Amap Maps + EdgeOne Makers",

  // Preset questions
  "preset.1": "I'm near Honglian South Road metro station. Recommend a mall that has both Breo and Xitingcunwu.",
  "preset.2": "If both brands aren't required, is there anything closer?",

  // Tool indicators
  "tool.location": "Geocode",
  "tool.malls": "Find malls",
  "tool.brand": "Check brand",
  "tool.distance": "Distance",
  "tool.walk": "Walking route",

  // Status & errors
  "status.error": "Request failed. Please check if the backend service is running.",
  "status.stopped": "⏹ *Generation stopped*",
  "status.backendError": "Backend abort request failed. The server may still be running.",

  // Debug panel
  "debug.title": "Trace",
  "debug.events": "events",
  "debug.clear": "Clear",
  "debug.empty": "Waiting for SSE events...",
  "debug.emptyHint": "After sending a message, all raw backend data will be displayed here.",

  // Conversation sidebar
  "sidebar.label": "Conversation list",
  "sidebar.title": "Chats",
  "sidebar.newChat": "New chat",
  "sidebar.loading": "Loading conversations...",
  "sidebar.loadMore": "Load more",
  "sidebar.loadingMore": "Loading...",
  "sidebar.emptyTitle": "No conversations yet",
  "sidebar.emptyHint": "Click \"New chat\" to start your first conversation.",
  "sidebar.delete": "Delete conversation",
  "sidebar.deleteConfirm": "Permanently delete this conversation? This cannot be undone.",

  // Aria labels (button hover/screen-reader)
  "aria.send": "Send",
  "aria.clearHistory": "Clear history",
  "aria.stopGeneration": "Stop generation",

  // Language toggle
  "lang.switch": "中文",

  // ─── Floating bottom-right action badges ─────────────────────────────
  "floatingLink.deploy": "Deploy",
  "floatingLink.github": "GitHub",
} as const;

export default en;
