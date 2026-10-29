# submission/ 作业提交材料

对应手册第十章要求的六项证据。**6/6 全部完成**（2026-10-29 线上部署验收通过）。

## 材料清单

| 文件 | 对应手册 | 状态 | 说明 |
|---|---|---|---|
| `01-local-running.png` | `local-running.png` 本地调试页面 | ✅ | 本地 `local_dev.py` 起服务后的首页（空态：三个面板、五个工具灯牌、两条预设问题） |
| `02-scenario1.png` | `normal-result.png` 正常请求结果 | ✅ | 场景一：红莲南路 + 既要倍轻松又要西町村屋 → 推荐龙湖北京丽泽天街，附品牌命中对照表 + 步行方案（真实高德数据） |
| `03-scenario2.png` | `follow-up-result.png` 连续追问结果 | ✅ | 场景二：不要求两个品牌同时存在 → **没有再追问位置**，复用上一轮位置重新比较 |
| `actions-success.png` | GitHub Actions 成功 | ✅ | 推送 `95db1d2` 后 `CI · 构建校验` 绿勾（运行 #57） |
| `deploy-success.png` | Makers 部署成功 | ✅ | 2026-10-29 16:16 EdgeOne Makers 部署成功，状态「成功」，耗时 67s，生产环境，五步流水线全绿，提交 `10cf691` |
| `public-entry.txt` | 公开预览地址 | ✅ | 预览域名 + 令牌地址 + 部署信息，见该文件 |
| `answers.txt` | —— | ✅ | 两轮回答纯文本，方便粘贴进实验报告 |

## 线上验收记录（2026-10-29 16:18）

部署地址：`https://openai-agent-starter-python-dpih81wwif72.edgeone.cool`

| 检查项 | 结果 |
|---|---|
| 首页 | HTTP 200，标题「出行决策助手 \| 附近商场品牌核验」（自定义前端已上线上） |
| 模型链路 | SSE 流式正常，身份提示词生效（自述「出行决策助手」） |
| 场景一 | 12 次工具调用（定位 → 商场检索 → 品牌核对 ×10），推荐龙湖北京丽泽天街，倍轻松 3F-14 + 西町村屋约 46m，附步行 1.9km/25min |
| 场景二 | 同会话追问，**未重新询问位置**，复用上下文重新核对并给出结论 |
| 演示标注 | 回答中无「演示数据 / 本地演示模式」字样 → `AMAP_MOCK` 未泄漏到线上 |
| 环境变量 | 仅 `AMAP_API_KEY`，模型 Key 由平台自动注入 |

## 重新生成前三张（本地）

服务先起来：

```bash
cd "G:/机器学习/agent开发/travel-decision-agent"
.venv/Scripts/python.exe local_dev.py          # http://127.0.0.1:8787
```

另开一个终端：

```bash
.venv/Scripts/python.exe tests/shot.py
```

脚本用本机 Chrome（headless，不下载 Playwright 浏览器），自动点两条预设问题、等流式输出结束再截。

## 线上接口自测（免浏览器）

```bash
# 1) 令牌换 cookie（302 即成功，会 Set-Cookie）
curl -c cj.txt "https://<域名>?eo_token=<token>&eo_time=<time>"
# 2) 对话必须带 makers-conversation-id（6-36 字符）
curl -N -X POST "https://<域名>/chat" -b cj.txt \
  -H "Content-Type: application/json" \
  -H "makers-conversation-id: test-001" \
  --data-binary @body.json      # {"message":"..."}，文件须 UTF-8
```
