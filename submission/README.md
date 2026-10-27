# submission/ 作业提交材料

对应手册第十章要求的六项证据。**已完成 5 项**，剩 2 项在 Makers 部署后补。

| 文件 | 对应手册 | 状态 | 说明 |
|---|---|---|---|
| `01-local-running.png` | `local-running.png` 本地调试页面 | ✅ 已生成 | 本地 `local_dev.py` 起服务后的首页（空态：三个面板、四个工具灯牌、两条预设问题） |
| `02-scenario1.png` | `normal-result.png` 正常请求结果 | ✅ 已生成 | 场景一：红莲南路 + 既要倍轻松又要西厅村屋 → 推荐广安门华联购物中心 785m，附命中对照表 |
| `03-scenario2.png` | `follow-up-result.png` 连续追问结果 | ✅ 已生成 | 场景二：不要求两个品牌同时存在 → 换成更近的天虹商场(广安门店) 494m，**没有再追问位置** |
| `answers.txt` | —— | ✅ 已生成 | 两轮回答的纯文本，方便粘贴进实验报告 |
| `actions-success.png` | GitHub Actions 成功 | ✅ 已截（2026-10-27） | 推送 `95db1d2` 后 `CI · 构建校验 #1` 绿勾，运行 #57 |
| `deploy-success.png` | Makers 部署成功 | ⬜ 待截 | Makers 控制台新建部署成功后，项目概览页截一张 |
| `public-entry.txt` | 公开预览地址 | ⬜ 待填 | 部署成功拿到 `*.edgeone.cool` 地址后写一行即可 |

## 重新生成前三张

服务先起来：

```bash
cd "G:/机器学习/agent开发/travel-decision-agent"
.venv/Scripts/python.exe local_dev.py          # http://127.0.0.1:8787
```

另开一个终端：

```bash
.venv/Scripts/python.exe tests/shot.py
```

脚本用本机 Chrome（headless，不下载 Playwright 浏览器），自动点两条预设问题、等流式输出结束再截，
所以每次重跑都是最新的界面。

## 这两张截图现在是什么状态

截图里回答开头有「⚙️ 本地演示模式」和「数据来源：内置演示样例」两处标注，因为当前
`.env` 里两个 Key 都还是空的。**这是刻意的**：证明整条链路（工具调用 → 表格 → 多轮记忆）
是真的跑通了，只是数据源换成内置样例。

正式交作业前，填上 `AI_GATEWAY_API_KEY` 和 `AMAP_API_KEY`、把 `AMAP_MOCK` 改成 `0`，
再跑一次 `tests/shot.py`，回答里就不带这两处标注了。
