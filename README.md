# dsh-mcu-lab

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/CHIP-PHILO-GH/dsh-mcu-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/CHIP-PHILO-GH/dsh-mcu-lab/actions/workflows/ci.yml)

只想要“照着做一遍”的封装版本（含安装、配置与排错表），见同名技能包 dsh-mcu-lab；本仓库是代码本体。

把「Keil C51 编译 → Proteus 仿真 → 确定性判定」这条 51 单片机开发链路接进 DSH 会话，
让 AI 在对话里直接编译 hex、跑电路、拿到 PASS/FAIL 与判定依据。

---

## 这是什么

一个 DSH 插件（`lib/index.js`）+ 一个命令行内核（`kernel/mcu_lab.py`），两者是同一件事的两层：

- **插件层**：向 DSH 注册 5 个工具，接收 AI 的调用参数，spawn 内核、把内核输出的单行 JSON 交回会话。
  它自己不编译、不仿真，只是一层薄壳。
- **内核层**：真正干活的 Python 脚本。6 个子命令（`check` / `list` / `build` / `sim` / `verify` / `run`），
  每个都输出单行 JSON，**不装插件也能直接在命令行用**。

它解决的问题很具体：单片机的作业验证过去只能靠人盯着 Proteus 看 LED 亮不亮、或者靠视觉模型读截图
（引脚编号会漂移，判定不稳定）。这里改成两层确定性判据——编译是否产出 hex、仿真进程的 CPU 是否在增长、
有没有失败标记文本。

## 仓库结构

| 路径 | 是什么 |
|---|---|
| `lib/index.js` | DSH 插件本体，注册 5 个工具 |
| `kernel/mcu_lab.py` | **命令行内核**（Python 3，纯标准库），插件调用的就是它 |
| `kernel/README.md` | 内核自己的说明文档（含原作者本机的实测记录） |
| `examples/led_blink.c` | 示例：AT89C51 上 P3.7 的 LED 闪烁（正向用例） |
| `examples/broken.c` | 示例：故意漏分号的坏代码（反向用例，用来验证编译失败能被抓到） |
| `docs/PROJECT_LOG.md` | 原项目的开发日志（决策、踩坑、历史实测数据） |
| `cordis.patch.yml` / `dsh.plugin.json` | DSH 装载用的补丁层与插件清单 |
| `test.mjs` | 零依赖测试（不需要 Keil / Proteus / DSH） |

内核是**本仓库的一部分**，不是外挂依赖：`kernel/mcu_lab.py` 随仓库一起发布，插件默认就用它。

## 五个工具：各干什么、怎么选

| 工具 | 干什么 | 前提 | 什么时候用 |
|---|---|---|---|
| `mcu_run` | 编译 → 把 hex 复制进电路工作副本 → 仿真 → 判定，返回 `verdict: PASS/FAIL` + 证据 + 工作目录 | Keil C51 + Proteus ISIS + 外部三脚本 | **默认入口**：只想知道「这段代码在这个电路上跑不跑得起来」 |
| `mcu_build` | 只用 Keil C51 把单文件 C51 源码编译成 hex，返回 hex 路径与日志尾部 | Keil C51 + `build51.py` | 只想排 C51 语法错误，还不想动电路（快，且不碰电路文件） |
| `mcu_sim` | 打开指定电路跑一段时间并截图，然后关闭 | Proteus ISIS + `proteus_ctl.py` | 只想看现象、要一张截图给人看；**不要**用它做判定 |
| `mcu_verify` | 只对指定电路做确定性判定，返回 `running` 与判定依据文本 | Proteus ISIS + `verify.py` | 电路和 hex 都已就位、只想复判一次；或不想让任何文件被改动 |

选法一句话：**要结论就 `mcu_run`；只排编译错误用 `mcu_build`；只要截图用 `mcu_sim`；只要复判用 `mcu_verify`；先找电路用 `mcu_list`。**

参数与返回值（来自 `lib/index.js`）：

| 工具 | 参数 | 主要返回字段 |
|---|---|---|
| `mcu_run` | `source_path`（必填，C51 源文件绝对路径）、`dsn_path`（必填，`.DSN` 绝对路径）、`hex_name`、`wait_seconds`（默认 6） | `ok` `verdict` `stage` `hex` `evidence` `workdir` `elapsed_sec` |
| `mcu_build` | `source_path`（必填） | `ok` `hex` `log_tail` |
| `mcu_sim` | `dsn_path`（必填）、`seconds`（默认 8）、`shot_path` | `ok` `shot` `workdir` |
| `mcu_verify` | `dsn_path`（必填）、`wait_seconds`（默认 6） | `ok` `running` `evidence` `errors` `status_text` |
| `mcu_list` | 无 | `ok` `count` `items` |

在会话里不必背参数，直接说就行，例如：
> 把 `examples/led_blink.c` 在这个电路上跑一遍，告诉我过没过。

## 前置条件

下面这些需要你自己装好或准备好（标「随仓库提供」的除外）。版本要求一栏凡没有代码依据的，一律写「未验证」。

| 组件 | 说明 | 版本要求 | 依据 |
|---|---|---|---|
| Keil C51 工具链 | `C51.exe` / `BL51.exe` / `OH51.exe`；`mcu_build` / `mcu_run` 的编译环节要用 | **最低 / 最高版本未验证**。原作者实测环境里 `C51.exe` 的文件版本是 `9.00`（文件描述 `C51/ CX51 Compiler`），本次整理读文件版本得到 | 读内核代码：它按固定路径调用工具链，代码里没有任何版本检查 |
| Proteus ISIS | `ISIS.EXE`；`mcu_sim` / `mcu_verify` / `mcu_run` 的仿真环节要用 | **最低 / 最高版本未验证**。原作者实测环境里 `ISIS.EXE` 的文件版本是 `7.08 SP2 IB10468`（文件描述 `ISIS Schematic Capture`） | 同上 |
| Python 3 | 跑内核脚本；`mcu_sim` / `mcu_verify` / `mcu_run` 的仿真环节还会用到接口脚本，它们需要第三方包 | 原作者实测 `3.13.15`，其他版本**未验证** | 内核 `kernel/mcu_lab.py` 只用 Python 标准库：`argparse` `json` `os` `shutil` `subprocess` `sys` `time` `glob`（读过它的 import 行确认）；但 `kernel/iface/proteus_ctl.py` 顶部 `import win32api / win32con / win32gui / win32ui / PIL`，`verify.py` 也 `import win32gui`。**所以「编译出 hex」只需要标准库，跑仿真/判定还需要 `pip install pywin32 Pillow`。** 不需要 pyserial |
| 外部接口脚本 | `build51.py`（调 Keil）、`proteus_ctl.py`（开/关仿真、截图）、`verify.py`（确定性判定） | **随仓库提供**：`kernel/iface/` | 内核默认从这里调用；可用 `DSH_MCU_LAB_IFACE` 指向你自己的目录。真正的判定逻辑写在 `verify.py` 里 |
| 电路模板索引 | `dsn_index.json`，`mcu_list` 的数据源 | 自备（不在本仓库内，**可选**） | 内核 `cmd_list` 读该文件；缺失时 `mcu_list` 返回 `ok:false` 并提示设 `DSH_MCU_LAB_DSN_INDEX`，**不影响 mcu_build / mcu_sim / mcu_verify / mcu_run** |
| 操作系统 | 内核里是 Windows 路径与 Windows 可执行文件的调用方式 | 原作者实测 Windows 11；**其他平台未验证** | 内核把 `C51.exe` / `ISIS.EXE` 当子进程调，没有跨平台分支 |
| Node.js | 跑插件与测试 | `>= 18`（`package.json` 的 `engines.node`） | 作者环境 Node v24.19.0 |
| DSH | 插件宿主（只用命令行内核时不需要） | `dsh.plugin.json` 里声明 `>=0.0.1` | 该值来自插件清单，未经跨版本验证 |

另外：插件侧（`lib/index.js`）运行时依赖 DSH 宿主提供的 `@deepseek-ai/dsh-tools`，已在 `package.json` 里以
`peerDependencies` 声明，**不把它复制进自身依赖树**——所以脱离 DSH 单独 `import` 这个插件会解析失败，
这是设计边界，不是缺文件；只想用命令行内核（`kernel/`）的人完全不需要它。

另外两条来自内核文档的经验（原作者陈述，本次整理未复现）：

- Proteus 的安装路径**必须纯英文**，中文路径会崩。
- C51 源码**必须纯 ASCII**，带中文注释会报 C141 之类的语法错误。

## 安装

### 方式一：装进 DSH（拿到 5 个工具）

1. 把本仓库放到 DSH 的 profile 模块目录下，目录名与包名一致：

   ```text
   <DSH_HOME>\profiles\node_modules\dsh-mcu-lab\
   ```

   其中 `<DSH_HOME>` 默认是 `%USERPROFILE%\.dsh`（可用环境变量 `DSH_HOME` 覆盖）。

2. 在该 profile 的 `cordis.patch.yml` 末尾加上装载行（本仓库的 `cordis.patch.yml` 内容一致）：

   ```yaml
   - insert:
       - id: mcu-lab
         name: 'dsh-mcu-lab'
   ```

3. 重启 DSH（`dsh web`）后，5 个工具才会出现在会话里。

> 本仓库不含安装脚本：上面的复制与装载行就是全部步骤，装在哪、装不装由你决定。

### 方式二：只用命令行内核（不装 DSH）

```bat
python kernel/mcu_lab.py check
python kernel/mcu_lab.py list
python kernel/mcu_lab.py build examples\led_blink.c
python kernel/mcu_lab.py run  examples\led_blink.c <你的电路.DSN> --wait 6
python kernel/mcu_lab.py verify <你的电路.DSN> --wait 6
python kernel/mcu_lab.py sim <你的电路.DSN> --seconds 8 --shot out.png
```

每个子命令都把结果打成单行 JSON，退出码 0 表示成功、1 表示跑完但失败、2 表示入参缺失
（例如源文件或电路不存在）。

### 内核归集说明

- 内核**随仓库发布**，位置固定在 `kernel/mcu_lab.py`；插件默认调用的就是仓库内这一份，
  用 `import.meta.url` 从插件文件位置推算出 `<仓库根>/kernel/mcu_lab.py`，
  **不需要另外安装内核、也不需要配置路径**。
- 内核 `kernel/mcu_lab.py` 本身只用 Python 标准库，不用 `pip install` 任何东西（**不需要 pyserial**）；
  但仿真环节要调用的 `kernel/iface/proteus_ctl.py` 需要 `win32api` / `win32gui` / `win32ui` / `PIL`（pywin32 + Pillow），
  `verify.py` 用到 `win32gui`。只跑 `check` / `list` / `build` 不需要这两个包。
- 内核自己会写东西：每次 `sim` / `verify` / `run` 都在 `kernel/work/<时间戳>/` 下建工作副本
  （`.DSN` 与 hex 的副本、截图、证据文件）。这个目录已被 `.gitignore` 排除。
- 内核文档的原文件（作者本机的说明）收在 `kernel/README.md`，开发日志收在 `docs/PROJECT_LOG.md`。

## 配置

### 插件侧：两个环境变量

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `DSH_MCU_LAB_CLI` | 内核脚本 `mcu_lab.py` 的路径 | `<仓库根>/kernel/mcu_lab.py`（按插件文件位置推算） |
| `DSH_MCU_LAB_PYTHON` | Python 解释器的路径 | Windows 用 `python`，其他平台用 `python3`（即按 PATH 查找） |

找不到内核或找不到解释器时，工具会返回一条说明「该设哪个环境变量」的错误，而不是空手失败。

### 内核侧：路径全部可用环境变量覆盖

内核以及它调用的接口脚本，路径都不写死在代码里，按下表覆盖；**不设就用默认值**。

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `DSH_MCU_LAB_IFACE` | 接口脚本目录（`build51.py` / `proteus_ctl.py` / `verify.py`） | **仓库自带**：`kernel/iface/` |
| `DSH_MCU_LAB_KEIL` | `C51.exe` 的路径（`check` 体检用） | `<KEIL_DIR>\C51\BIN\C51.exe` |
| `DSH_MCU_LAB_ISIS` | `ISIS.EXE` 的路径（体检与仿真控制用） | `<PROTEUS_DIR>\BIN\ISIS.EXE` |
| `DSH_MCU_LAB_DSN_INDEX` | `dsn_index.json` 的路径（只有 `mcu_list` 用） | **空**——本仓库不附带电路索引 |
| `DSH_MCU_LAB_KEIL_DIR` | Keil 安装根目录（接口脚本 `build51.py` 用） | `<KEIL_DIR>` |
| `DSH_MCU_LAB_PROTEUS_TEMP` | Proteus 仿真临时目录 | `<PROTEUS_TEMP>` |
| `DSH_MCU_LAB_SDCC_BIN` | SDCC 工具链目录（只在用 `sdcc51.py` 时） | `<SDCC_BIN>` |

`<KEIL_DIR>`、`<PROTEUS_DIR>`、`<SDCC_BIN>` 是这三款软件的**常见默认安装位置**，不是作者的个人信息；
装在别处就设上面对应的变量。先跑一次体检：

```bash
python kernel/mcu_lab.py check
```

它会逐项报告每个前置条件是否就位。**`dsn_index.json` 是可选件**：它只服务 `mcu_list`，
索引的是各人自备的电路文件，因此缺失**不会**让体检失败，只会单独列在 `optional` 字段里。

### 没有 Keil 也能编译：SDCC 路线

仓库自带的 `kernel/iface/sdcc51.py` 用 **SDCC**（免费开源编译器）替代 Keil：

```bash
python kernel/iface/sdcc51.py your.c        # .c -> .hex（Intel HEX，Proteus 可直接加载）
```

需要可从 PATH 调用的 SDCC（或设 `DSH_MCU_LAB_SDCC_BIN` 指向安装目录；本机实测为 SDCC 4.6.0）。
**仿真与判定仍需 Proteus，但"编译出 hex"这一段不再依赖付费的 Keil。**

⚠️ **这条路线只对「标准 C + SDCC 认可的扩展」成立，Keil 专有关键字要自己改**：
`sdcc-inc/reg52.h` 这个 shim 只负责把 `#include <reg52.h>` 转发到 SDCC 的 `8052.h`，
仓库自带的 `examples/led_blink.c` 已用 `#if defined(__SDCC)` 兼容 SDCC 的 `__sbit` 扩展。
`sdcc51.py` 会优先使用 PATH 中的 `sdcc`，也可用 `DSH_MCU_LAB_SDCC_BIN` 指定目录。
`mcu_build` / `mcu_run` 的 `--compiler auto` 会优先 Keil，Keil 不可用时自动回退 SDCC。

```bat
python kernel/iface/sdcc51.py examples\led_blink.c
:: 预期：SDCC 结果: errors=0 ... hex=...\led_blink.hex
```

其他 Keil 专有语法（例如 `interrupt`、`_at_`）仍需按 SDCC 语法改写；未逐项验证。

## 没有 Keil/Proteus 时的能力边界

```bat
python kernel/mcu_lab.py check
```

该命令会分别报告 `keil_c51`、`proteus_isis`、`sdcc`、脚本文件和 `capabilities`。
缺失工具不会抛栈，而会给出安装/配置指引；`ok:false` 只表示完整能力矩阵未齐，不会掩盖可用的 SDCC 编译或离线判定能力。
商业软件缺失时，`keil_build` 或 `proteus_sim` 会是 `false`，对应结果标为未验证。

## 离线验证

没有 Proteus 时可以用注入的离线后端验证真实 `mcu_lab.py -> verify.py` 判定链路：

```bat
python kernel/mcu_lab.py verify path\pass.dsn --backend offline
python kernel/mcu_lab.py verify path\sim-fail.dsn --backend offline
python kernel/mcu_lab.py verify path\verdict-fail.dsn --backend offline
```

`pass.dsn` 内容为空即返回 `running:true`；包含 `OFFLINE_SIM_FAIL` 返回仿真失败；包含 `OFFLINE_VERDICT_FAIL` 返回判定不通过。
这是假桩，不代表真实 Proteus 行为，但三种结果都经过正式 `verify` 子命令和 JSON/退出码处理。
## 能力边界

如实划清能做到与做不到的：

- **仓库不自带工具链**。clone 下来不能独立跑通端到端：Keil C51 与 Proteus ISIS 都是要自己装的商业软件；
  模板索引（`dsn_index.json`）也不在这里。三个接口脚本**已经随仓库提供**（`kernel/iface/`），缺什么，`check` 会列出来。
- **判定逻辑在随仓库发布的 `verify.py` 里**。`mcu_verify` / `mcu_run` 的判定是调用 `kernel/iface/verify.py`
  并解析它输出的最后一行 JSON 得到的；判据本身（进程 CPU 增长、失败标记文本、窗口存活）写在那个文件里。
  `DSH_MCU_LAB_IFACE` 指向别处时，用的就是你自己的那份。
- **`mcu_sim` / `mcu_verify` 只复制 `.DSN`，不复制 hex**（读内核 `cmd_sim` / `cmd_verify` 可见，
  它们调用 `_stage_dsn` 时没传 hex 路径）。因此电路引用的 hex 若不在工作副本目录里，
  这两个工具是否还能跑起来**未验证**；要端到端验证请用 `mcu_run`（它会把 hex 一并复制）。
- **不改你的原始电路**：每次都在 `kernel/work/<时间戳>/` 做副本，原始 `.DSN` 不被写入
  （这是设计约束，代码路径可核）。
- **`mcu_list` 的输出随索引文件变化**，最多 80 条（内核里是 `items[:80]`）。
  原文档里「79 个模板」是原作者本机那份索引的数量，不是本插件的固有能力。
- **判定视角是「仿真是否真在跑」**，不是「电路功能是否正确」。LED 是否按你期望的节奏闪，
  判定器不知道；它告的是「程序跑起来了、没有失败标记」。
- **没有 CI 端到端**：见下一节。任何「CI 已验证编译/仿真」的说法在本仓库都不成立。

## 测试

### 能跑的：零依赖测试

```bash
node test.mjs      # 等价于 npm test
```

需要 **Node ≥ 18 + Python 3**；**不需要** Keil、Proteus，也不需要 DSH 在运行。覆盖四类：

1. **语法**：`node --check lib/index.js`、Python 编译 `kernel/mcu_lab.py`。
2. **内核命令行契约**（不依赖 Keil/Proteus 的部分）：`check` / `list` 输出单行 JSON 且字段形状正确；
   `build` / `run` / `sim` / `verify` 在源文件或电路不存在时返回**结构化报错与退出码 2**，而不是抛栈。
3. **纯函数**：内核的 `_dec()` 解码兜底（UTF-8 → GBK → 替换字符），以及字符串直通。
4. **SDCC 与离线后端**：临时目录编译自带示例，并通过 `verify.py --backend offline` 覆盖通过、仿真失败、判定失败。
5. **仓库卫生与文档一致性**：`lib/index.js` 注册的工具名与两个 README 里写的一致；
   `package.json` 的包名/版本/`files` 对得上；仓库里没有 Keil/Proteus 构建产物，
   也没有 Windows 用户目录下的绝对路径这类本机痕迹。

### 不能跑的：为什么没有端到端 CI

真正要验证的是「编译 → 仿真 → 判定」这条链路，它必须在本机装好 **Keil C51** 与 **Proteus ISIS**：

- 两者都是商业软件，GitHub Actions 的 runner 上没有，也没有免安装的等效替代品能产生同样的证据——
  判定的依据是 Proteus 进程的 CPU 增长与窗口存活，换个模拟器就换了判据；
- 链路中间的三个接口脚本随仓库发布在 `kernel/iface/`；`dsn_index.json` 需自备（可选）。

所以 `.github/workflows/ci.yml` **只跑上面第 1–4 类零依赖测试**，一个字节都不假装跑过编译或仿真。

### 你自己怎么自验端到端

在本机装好 Keil C51 与 Proteus ISIS，按「配置」一节用环境变量（或直接改内核里那几个默认值）把路径指到你的安装位置，然后：

```bat
python kernel/mcu_lab.py check
:: 期望 6/6 全 true；缺哪一项会列出哪一项是 false

python kernel/mcu_lab.py run examples\led_blink.c <你的电路.DSN> --wait 6
:: 期望最后一行 JSON 里 ok=true、verdict=PASS，evidence 里能看到 CPU 增长与"无失败标记"

python kernel/mcu_lab.py run examples\broken.c <同一个电路.DSN> --wait 6
:: 反向用例：期望 ok=false、stage=build，log_tail 里出现 C141 之类的语法错误
```

### 原作者本机的实测记录（2026-09-08）

以下数据来自原项目日志（`docs/PROJECT_LOG.md`），是**在装有 Keil C51 与 Proteus 7.8 的机器上**
跑出来的历史记录，**不是本次开源整理跑的**：

| 测试 | 结果 |
|---|---|
| `mcu_lab.py check` | 6/6 通过 |
| 正向：`led_blink.c` → ex4 电路 | `verdict: PASS`，11.0 秒，证据 `process CPU advanced 0.172s; ISIS window alive; no failure markers` |
| 反向 1：`broken.c`（语法错） | `ok:false, stage:build`，日志含 `ERROR C141` |
| 反向 2：电路文件不存在 | `ok:false, stage:verify`，明确报错 |
| `mcu_lab.py list` | 返回 79 个模板 |

本次整理实际跑过的命令与结果，记录在交付说明里（结论：零依赖测试全部通过；端到端未复跑）。

## 许可

[MIT](LICENSE) © 2026 CHIP-PHILO-GH

Keil、Proteus 是各自公司的商业软件，本仓库不包含、也不分发它们。


