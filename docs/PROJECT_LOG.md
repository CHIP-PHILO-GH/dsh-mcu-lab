> **开源发布版说明**：为清除本机痕迹，本文件中的本机绝对路径与可识别到个人的描述已做替换
> （`<DSH_HOME>` = DSH 配置目录、`<原内核目录>` = 本仓库的 `kernel/` 与 `examples/`、
> `<接口脚本目录>` = 内核调用的外部脚本目录、`<调研数据目录>` = 生态调研数据所在目录），
> 其余内容与结构保持原样。

# dsh-mcu-lab 项目日志（PROJECT_LOG）

## 背景与目标

发起者是一名在读本科生（微电子 / 电子工程方向），在 2026-09-08 晚问「就今晚能做什么有价值的东西」。经生态实测（awesome-dsh-plugin 全量 3363 插件，2026-09-07 数据）发现：**单片机/嵌入式品类几乎空白**（proteus 命中 0、51/arduino/esp32/stm32 命中 0、keil 命中 1 且只是技能包不执行工具），而生视频、生图、UI、记忆、编排等品类已拥挤或头部锁死。

同时，手上已经有跑通的底层脚本（`build51.py` / `proteus_ctl.py` / `verify.py`），以及 79 个课程电路模板索引。**缺的只是最后一层：把它们接进 DSH，让 AI 在会话里闭环。**

## 最终方案与理由

三层结构：

1. **CLI 内核** `<原内核目录>\mcu_lab.py` —— 纯标准库，5 个子命令（check/list/build/sim/verify/run），每个都输出单行 JSON。理由：不装插件也能用，且便于被任何 agent 调用。
2. **DSH 插件包** `<DSH_HOME>\profiles\node_modules\dsh-mcu-lab\` —— `inject = ['tools']`，用 `defineTool` 注册 5 个工具，execute 里 spawn 调 CLI。理由：照抄 mineru 插件验证过的注册模式，风险最低。
3. **profile 注册** `<DSH_HOME>\profiles\web\cordis.patch.yml` 末尾追加 insert 行。理由：与 butler / rawchat / vision 等插件同一套机制。

关键决策：
- **不修改原始电路**：每次仿真把 .DSN + hex 复制到 `work\<时间戳>\` 再跑（红线 3：原住民文件保护）。
- **判定走确定性通道**：不用截图 + 视觉模型猜（历史教训：视觉读引脚编号会漂移），用 verify.py 的 CPU 增长 + 失败标记文本。
- **插件与 CLI 解耦**：插件只是薄壳，逻辑全在 CLI，方便以后命令行直用或换宿主。

## 关键路径与产物

- CLI：`<原内核目录>\mcu_lab.py`（8KB）
- 示例：`<原内核目录>\examples\led_blink.c`、`broken.c`
- 插件：`<DSH_HOME>\profiles\node_modules\dsh-mcu-lab\{package.json, dsh.plugin.json, cordis.patch.yml, lib\index.js}`
- 注册：`<DSH_HOME>\profiles\web\cordis.patch.yml`（末尾 dsh-mcu-lab 段）
- 说明：`<原内核目录>\README.md`
- 生态调研原始数据：`<调研数据目录>\plugins.json` + `DSH生态与提案调研-20260908.md`

## 踩坑

1. **chatlog 的明文库在 `work_dir\db_storage\` 子目录下**，不是直接放在 work_dir 根——按根目录找会得到"0 条"的假结果。（同批做的微信同步工具踩到）
2. **同一个人消息分散在 message_0.db 与 message_1.db 两个库**，若用同一个游标键，两个库会互相覆盖游标，导致每次同步都把老消息重发。修法：游标键改为 `库名::会话`。
3. **PowerShell 里 `cd /d` 不是合法语法**（那是 cmd 的），要用 `Set-Location`，否则后续 `cmd /c run.bat` 找不到文件。
4. 静态插件必须 `export const inject = ['tools']`，否则服务未就绪时注册会失败。

## 验证结果（2026-09-08 实测）

| 项目 | 结果 |
|---|---|
| `mcu_lab.py check` | 6/6 通过 |
| 正向端到端（led_blink.c → ex4.DSN） | `verdict: PASS`，elapsed 11.0s，evidence=`process CPU advanced 0.172s; ISIS window alive; no failure markers` |
| 反向 1（broken.c 语法错误） | `ok:false, stage:build`，日志含 `ERROR C141` |
| 反向 2（DSN 不存在） | `ok:false, stage:verify`，明确报错 |
| `mcu_lab.py list` | 返回 79 个电路模板 |
| 插件 `node --check` | 通过 |
| 插件 import 冒烟 | `name=mcu-lab, apply=function, inject=["tools"]` |
| `dsh --profile web --dump-config` | 含 `- id: dsh-mcu-lab / name: 'dsh-mcu-lab'`，无 error |

## 用法

会话里直接说「把这段代码在 ex4 电路上跑一遍验证」，或命令行：
`python kernel/mcu_lab.py run <源.c> <电路.DSN>`

## 待用户做

**重启 `dsh web`**（AI 不自行重启），重启后 5 个工具才会出现在会话里。

## 后续可扩展

- 加 `mcu_uart`（串口仿真 + 收发校验）、`mcu_scope`（逻辑分析仪数据抓取）
- 把常见实验做成模板库（LED/数码管/按键/蜂鸣器/串口），一句话生成工程
- 若要发布到插件市场：需补 LICENSE、英文 README、把硬编码路径改成配置项
