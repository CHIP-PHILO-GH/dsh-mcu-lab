> **说明（开源发布版）**：这是命令行内核 `mcu_lab.py` 自己的说明文档，随仓库一起提供。
> 原文里的本机绝对路径已替换为占位符（`<DSH_HOME>`、`<接口脚本目录>`），指向内核自身的路径改成了
> 仓库内相对路径（`kernel/`、`examples/`），其余内容与原文档一致。文中「实测结果」是原作者本机
> 2026-09-08 的实测记录。

# dsh-mcu-lab —— 把 51 单片机开发闭环接进 DSH

## 这是什么

让 AI 在 DSH 会话里自己完成「写 C51 → Keil 编译出 hex → Proteus 跑仿真 → 判定通过/失败」。
按 2026-09-07 对 awesome-dsh-plugin 全量清单（3363 个插件）的比对，能编译 hex / 跑 Proteus /
判定结果的插件为 0，这也是本插件当初的出发点。

## 装了之后 AI 能做什么

| 工具 | 作用 |
|---|---|
| `mcu_run` | 一次调用完成：编译 + 仿真 + 判定（推荐） |
| `mcu_build` | 只编译，出 hex |
| `mcu_sim` | 打开电路跑仿真并截图 |
| `mcu_verify` | 只做确定性判定 |
| `mcu_list` | 列出电路模板（数量取决于 `dsn_index.json` 索引文件） |

用法举例（在会话里直接说）：
> 把这段 LED 闪烁的 C 代码，在 ex4 电路上跑一遍验证。

## 两个设计约束（重要）

1. **不碰你的原始电路**：每次仿真都把 .DSN 和 hex 复制到 `work\<时间戳>\` 下再跑，原始课程文件一个字节都不改。
2. **判定不靠截图猜**：不用视觉识别（视觉读引脚编号会漂移），改用 `verify.py` 的「进程 CPU 增长 + 失败标记文本 + 窗口存活」三重信号。

## 路径

| 东西 | 位置 |
|---|---|
| 内核脚本 | `kernel/mcu_lab.py`（本仓库内） |
| 示例程序 | `examples/`（本仓库内） |
| 每次仿真产物 | `kernel/work/<时间戳>/`（自动生成，已被 .gitignore 排除） |
| DSH 插件包 | `<DSH_HOME>\profiles\node_modules\dsh-mcu-lab\` |
| 底层脚本 | `kernel/iface/`（build51.py / proteus_ctl.py / verify.py，**随本仓库发布**） |

## 命令行直接用（不装插件也能用）

```bat
python kernel/mcu_lab.py check
python kernel/mcu_lab.py list
python kernel/mcu_lab.py run  <源文件.c> <电路.DSN> [--wait 6]
python kernel/mcu_lab.py build <源文件.c>
python kernel/mcu_lab.py verify <电路.DSN>
```

## 实测结果（2026-09-08，原作者本机）

| 测试 | 结果 |
|---|---|
| 环境自检 `check` | 6/6 通过 |
| 正向：LED 闪烁 → ex4 电路 | `verdict: PASS`，11 秒，证据「CPU advanced 0.172s；无失败标记」 |
| 反向 1：语法错误的 C | `ok:false, stage:build`，报出 C141 语法错误 |
| 反向 2：电路文件不存在 | `ok:false, stage:verify`，明确报错 |
| 插件自检 | 语法 OK / import OK（name=mcu-lab, apply=function）/ dump-config 已注册 |

## 前置依赖

- Keil C51（C51 / BL51 / OH51）——原作者本机装在 `D:\keil`；**安装位置随人而异**，内核里的
  `KEIL` 常量要改成你自己的路径
- Proteus ISIS——原作者本机装在 `D:\Proteus7\BIN\ISIS.EXE`；**必须英文路径**，中文路径会崩（原作者经验）
- Python 3（原作者实测 3.13.15；内核只用标准库，不需要任何第三方包）
- 接口脚本 `build51.py` / `proteus_ctl.py` / `verify.py`：随仓库发布在 `kernel/iface/`（可用 `DSH_MCU_LAB_IFACE` 指向你自己的目录）

## 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 编译报 C141 之类语法错误 | 源码里有中文注释 | C51 源码必须纯 ASCII |
| `Cannot open LISA*.SDF` | 临时目录含中文 | 已用 `D:\proteus_temp` 做进程级隔离 |
| 判定 FAIL 但截图里 LED 亮着 | 电路里 hex 文件名对不上 | 用 `--hex-name` 指定电路期望的 hex 名 |
| 工具没出现在会话里 | 插件还没生效 | 重启 `dsh web` |
