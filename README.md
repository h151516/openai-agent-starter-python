# 出行决策 Agent（Travel Decision Agent）

基于 [TencentEdgeOne/openai-agent-starter-python](https://github.com/TencentEdgeOne/openai-agent-starter-python) 改造的课程项目：
告诉 Agent 你在哪、想逛哪些品牌，它去查附近的商场、逐个核对品牌门店、比较距离，然后给出可解释的推荐。

**框架：** OpenAI Agents SDK（Python） · **地图：** 高德地图 Web 服务 · **平台：** 腾讯云 EdgeOne Makers

## 能力边界

| 能做什么 | 怎么做 |
|---|---|
| 解析用户位置 | `resolve_location` → 高德地理编码，拿到经纬度和城市 |
| 找附近商场 | `search_nearby_malls` → 周边检索 POI 分类 060100（购物中心） |
| 核对品牌是否在商场 | `search_brand_in_mall` → 以商场坐标为中心做品牌 POI 周边检索 |
| 比较远近 / 估算通勤 | `measure_distance` → 高德路网驾车距离 |

典型问法：

```text
我在红莲南路地铁站附近，想找一个既有倍轻松又有西厅村屋的商场，帮我推荐。
```

预期行为：先解析位置 → 搜周边商场 → 对每个商场分别查「倍轻松」和「西厅村屋」→ 只有两个品牌都命中的商场才算满足 → 按距离排序给推荐。
第二轮追问「如果不要求两个品牌同时存在，还有没有更近的」，应复用第一轮的位置条件重新比较，而不是重新问地址。

## 四个工具的设计取舍

- **品牌核对为什么用周边检索**：高德没有「某商场内品牌清单」这种接口，只能以商场坐标为圆心、在 500 米内搜该品牌，用命中门店到圆心的距离近似判断。这个近似有误差，所以工具返回里带了 `note` 和 `limitation` 字段，提示模型不要说成「100% 确认在店内」。
- **距离为什么两种**：`search_nearby_malls` 的 `distance_m` 是直线距离（排序用，快）；`measure_distance` 是路网驾车距离（回答「多久到」用）。两者不要混着说。
- **错误不吞**：任何工具失败都返回 `{"error": ..., "hint": ...}`，让模型向用户说明是 Key 的问题还是搜索范围的问题，而不是编一个结果。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `AI_GATEWAY_API_KEY` | 是 | 模型网关 Key。部署到 Makers 时由平台自动注入；本地运行必须手填 |
| `AI_GATEWAY_BASE_URL` | 是 | `https://ai-gateway.edgeone.link/v1` |
| `AI_GATEWAY_MODEL` | 否 | 默认 `@makers/deepseek-v4-flash`，换模型只改这里，不用改代码 |
| `AMAP_API_KEY` | 是 | 高德 **Web 服务** 类型的 Key（不是 Web 端 JS Key） |

## 本地开发

前置：Node.js ≥ 18、Python ≥ 3.10、EdgeOne CLI（`npm i -g edgeone`）。

```bash
npm install
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env                            # 填入真实 Key
edgeone makers dev
```

本地访问 `http://localhost:8080`，链路追踪面板在 `http://localhost:8080/agent-metrics`。

Windows 注意：`package.json` 里 `dev:agents` 脚本用的是 `PATH=$PWD/.venv/bin:$PATH`（Unix 写法），Windows 请直接用 `edgeone makers dev`，并确保 `.venv/Scripts` 在 PATH 里。

## 项目结构

```text
travel-decision-agent/
├── agents/
│   ├── chat/index.py          # POST /chat —— SSE 流式对话入口，Agent 与提示词在这里
│   ├── chat/stop.py           # POST /chat/stop —— 中断当前 run
│   ├── _logger.py             # 日志
│   └── _tools.py              # 四个高德地图工具（本项目的核心改动）
├── cloud-functions/           # 无状态接口：history / conversations / clear / delete
├── src/                       # React + Vite 前端（聊天界面、工具灯牌、调试面板）
├── api-schema.json            # 工具接口声明（高德 endpoint、参数、返回字段）
├── edgeone.json               # 平台部署配置，framework=openai-agents-sdk，不要覆盖
├── requirements.txt
└── package.json
```

## 部署

1. GitHub 上 Fork 上游模板，仓库名 `travel-decision-agent`；
2. Makers 控制台授权 GitHub，绑定这个 Fork 建项目；
3. 仓库 Settings → Secrets and variables → Actions 加 `EDGEONE_API_TOKEN`；
4. Push 触发自动部署，或在 Makers「部署管理 → 新建部署」手动触发；
5. 用临时预览地址验证对话。

完整步骤见同目录上一级的 `操作手册.md`。

## 参考

- [EdgeOne Makers Agents 文档](https://cloud.tencent.com/document/product/1552/132759)
- [高德 Web 服务 API](https://lbs.amap.com/api/webservice/summary)
- [OpenAI Agents SDK (Python)](https://openai.github.io/openai-agents-python/)

## License

MIT.
