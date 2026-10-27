const zh = {
  // Header
  "app.title": "出行决策助手",
  "app.subtitle": "告诉我你在哪、想逛什么品牌，我帮你挑最近的商场",

  // 顶部模式角标（仅本地 local_dev.py 会返回 /status）
  "status.demo": "演示模式 · 无模型",
  "status.mock": "样例数据",
  "status.demoMock": "演示模式 · 样例数据",
  "status.hint": "当前没有模型 Key，回答由本地规则生成；地图数据来自内置样例（AMAP_MOCK=1），不是高德实时结果",

  // Empty state
  "empty.title": "出行决策助手",
  "empty.hint": "我可以帮你查询附近的商场，核对里面有没有你想要的品牌门店，再按距离给出推荐。试试告诉我你的位置和想找的品牌。",
  "empty.features": "高德地图 · 品牌核对 · 距离比较 · 多轮追问",

  // Chat input
  "chat.placeholder": "说说你在哪、想找什么…  ⏎ 发送 · Shift+⏎ 换行",
  "chat.hint": "由 OpenAI Agents SDK + 高德地图 + EdgeOne Makers 驱动",

  // Preset questions
  "preset.1": "我在红莲南路地铁站附近，想找一个既有倍轻松又有西厅村屋的商场，帮我推荐。",
  "preset.2": "如果不要求两个品牌同时存在，还有没有距离更近的选择？",

  // Tool indicators
  "tool.location": "地点解析",
  "tool.malls": "商场检索",
  "tool.brand": "品牌核对",
  "tool.distance": "距离测量",
  "tool.walk": "步行规划",

  // Status & errors
  "status.error": "⚠️ 请求失败，请检查后端服务是否启动。",
  "status.stopped": "⏹ *已停止生成*",
  "status.backendError": "⚠️ 后端中断请求失败，服务端可能仍在运行。",

  // Debug panel
  "debug.title": "传输流",
  "debug.events": "事件",
  "debug.clear": "清除",
  "debug.empty": "等待 SSE 事件...",
  "debug.emptyHint": "发送消息后，所有原始后端数据将在此处显示。",

  // Conversation sidebar
  "sidebar.label": "会话列表",
  "sidebar.title": "会话",
  "sidebar.newChat": "新建聊天",
  "sidebar.loading": "正在加载会话...",
  "sidebar.loadMore": "加载更多",
  "sidebar.loadingMore": "加载中...",
  "sidebar.emptyTitle": "暂无会话",
  "sidebar.emptyHint": "点击「新建聊天」开始第一段对话。",
  "sidebar.delete": "删除会话",
  "sidebar.deleteConfirm": "确定要永久删除这个会话吗？此操作不可恢复。",

  // Aria labels (button hover/screen-reader)
  "aria.send": "发送",
  "aria.clearHistory": "清除历史",
  "aria.stopGeneration": "停止生成",

  // Language toggle
  "lang.switch": "English",

  // ─── Floating bottom-right action badges ─────────────────────────────
  "floatingLink.deploy": "一键部署",
  "floatingLink.github": "GitHub",
} as const;

export default zh;
