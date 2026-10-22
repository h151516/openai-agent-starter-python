# 出行决策 Agent（中文说明）

> 完整说明见 [README.md](./README.md)。这里只放最常用的信息。

## 这是什么

把 EdgeOne Makers 的 OpenAI Agents Starter（Python）改造成一个**出行决策 Agent**：
用户报位置 + 想逛的品牌，Agent 用高德地图查附近商场、逐个核对品牌门店、比较距离，再给出推荐。

## 和原模板的差别

| 原模板 | 现在 |
|---|---|
| `get_weather` 天气查询（假数据） | `resolve_location` 高德地理编码 |
| `get_clothing_advice` 穿衣建议（规则判断） | `search_nearby_malls` 周边商场检索 |
| `translate_text` 翻译（假数据） | `search_brand_in_mall` 品牌门店核对 |
| `text_statistics` 文本统计 | `measure_distance` 路网距离测量 |

前端、SSE 流式、会话记忆、部署配置全部沿用，只替换了业务层。

## 跑起来

```bash
npm install
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env          # 填 AI_GATEWAY_* 和 AMAP_API_KEY
edgeone makers dev
```

访问 `http://localhost:8080`。

没装 EdgeOne CLI、或暂时没有 Key，用本地运行时：

```bash
npm run build                            # 出 dist/（不跑则自动回退 local_preview.html）
.venv/Scripts/python.exe local_dev.py     # http://127.0.0.1:8787
```

## 离线演示模式（不需要高德 Key）

`.env` 里加一行 `AMAP_MOCK=1`，四个工具改读 `agents/_fixtures.py` 的内置样例数据，
不联网、不消耗配额。样例取景地是「北京西城区红莲南路地铁站」，正好覆盖手册的两个场景：

| 场景 | 结论 |
|---|---|
| 既要倍轻松又要西厅村屋 | 广安门华联购物中心（约 785m，唯一同时命中） |
| 只要求一个品牌、要比近 | 天虹商场(广安门店)（约 494m） |

带这个标记的结果会附 `source: "mock"`，模型会在回答里注明「演示数据」。**上线前必须关掉。**

两个自检脚本都不需要 Key：

```bash
.venv/Scripts/python.exe tests/offline_check.py    # 工具层 24 项
.venv/Scripts/python.exe tests/mock_flow.py        # 业务层 14 项，打印命中矩阵
.venv/Scripts/python.exe tests/local_demo_check.py # 演示链路 12 项，两轮对话
```

## 必填的两个 Key

- `AI_GATEWAY_API_KEY`：Makers 控制台 → 模型与密钥
- `AMAP_API_KEY`：高德开放平台 → 应用管理 → 添加 Key，**服务平台选「Web服务」**

`AI_GATEWAY_MODEL` 不填默认 `@makers/deepseek-v4-flash`，想换模型只改这个变量，不用动代码。

## 典型对话

```text
我在红莲南路地铁站附近，想找一个既有倍轻松又有西厅村屋的商场，帮我推荐。
```

```text
如果不要求两个品牌同时存在，还有没有距离更近的选择？
```

第二句应该复用第一轮的位置，不再追问地址 —— 这是会话记忆在起作用。

## License

MIT.
