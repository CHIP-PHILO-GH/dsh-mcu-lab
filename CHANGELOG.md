# 更新日志

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-09-12

首个公开版本，整理自作者本机自用的插件 `@local/dsh-mcu-lab`。

### 修复（2026-09-13 发布前整理）

- `package.json` 增加 `peerDependencies`：`@deepseek-ai/dsh-tools`。插件侧运行时依赖 DSH 宿主提供，
  原先一条依赖都没声明，陌生人克隆后直接导入会报「找不到包」。本包不把宿主运行时复制进自身依赖树，
  README「前置条件」已同步说明这是设计边界。
- `test.mjs` 的临时目录改用系统临时目录：原先建在仓库的上一级目录里，测试被打断就会在克隆目录旁边
  留下 `dsh-mcu-lab-offline-*` 残留。

### 新增

- 5 个 DSH 工具：`mcu_run`（编译 + 仿真 + 判定，推荐入口）、`mcu_build`、`mcu_sim`、`mcu_verify`、`mcu_list`。
- 命令行内核随仓库发布：`kernel/mcu_lab.py`（Python 3，纯标准库），6 个子命令
  `check` / `list` / `build` / `sim` / `verify` / `run`，每个都输出单行 JSON。不装插件也能直接用。
- 示例程序：`examples/led_blink.c`（正向）、`examples/broken.c`（反向，验证编译失败能被抓到）。
- 文档：`README.md`、`README.en.md`（全文英文对照）、`kernel/README.md`（内核自己的说明）、
  `docs/PROJECT_LOG.md`（原项目开发日志）。
- 测试 `test.mjs`：零依赖，覆盖语法、内核命令行契约、纯函数解码、仓库卫生与文档一致性。
  不需要 Keil / Proteus / DSH。
- GitHub Actions CI（`.github/workflows/ci.yml`）：只跑上面这些零依赖测试。

### 接口脚本随仓库发布（本次整理新增）

- `kernel/iface/` 收纳内核**必需**的三个脚本：`build51.py`（Keil 编译封装）、
  `proteus_ctl.py`（Proteus 仿真控制）、`verify.py`（确定性判定）；另含
  `sdcc51.py`（SDCC 免费编译器路线）与 `sdcc-inc/reg52.h`。
  没有前三个，内核的 `build` / `sim` / `verify` / `run` 都跑不起来，因此必须随仓库发布。
- 这些脚本头部的课程语境说明已去掉；其安装路径改为可用环境变量覆盖
  （`DSH_MCU_LAB_KEIL_DIR` / `DSH_MCU_LAB_ISIS` / `DSH_MCU_LAB_PROTEUS_TEMP` / `DSH_MCU_LAB_SDCC_BIN`），
  默认值取三款软件的常见安装位置，不再写死在某台机器上。
- 内核的 `IFACE` / `KEIL` / `ISIS` / `DSN_INDEX` 同样改为环境变量覆盖
  （`DSH_MCU_LAB_IFACE` / `DSH_MCU_LAB_KEIL` / `DSH_MCU_LAB_ISIS` / `DSH_MCU_LAB_DSN_INDEX`）。
- `check` 把 `dsn_index.json` 归为**可选件**：它只服务 `mcu_list`，索引的是各人自备的电路，
  缺失不再让体检失败，改为在 `optional` 字段单独列出；`list` 在未配置索引时给出指明环境变量的报错。

### 变更（相对作者本机自用版本）

- `package.json`：包名从 `@local/dsh-mcu-lab` 改为 `dsh-mcu-lab`，去掉 `"private": true`，
  补 `description` / `keywords` / `repository` / `engines`（`node >= 18`、`dsh >= 0.0.1`）/
  `files` / `scripts`。依赖声明未改动（原本就没有依赖字段）。
- `lib/index.js`：删掉写死的 Python 解释器路径与内核路径，改为「环境变量优先 + 用
  `import.meta.url` 推算仓库内相对路径」，默认指向 `kernel/mcu_lab.py`；
  找不到内核或解释器时给出「该设哪个环境变量」的报错。环境变量名沿用
  `DSH_MCU_LAB_PYTHON` / `DSH_MCU_LAB_CLI`。
- `cordis.patch.yml` 与 `dsh.plugin.json`：随包名改名，装载行的 `name` 与包名一致。
- 工具描述里「本机课程资料 / 79 个模板」等本机专属说法改为「随索引文件变化」。
- 文档里的本机绝对路径与可识别到个人的描述替换为占位符（`<DSH_HOME>` 等）。

### 已知边界

- 端到端（编译 → 仿真 → 判定）必须自备 Keil C51 与 Proteus ISIS（接口脚本已随仓库发布在 `kernel/iface/`）
  （`build51.py` / `proteus_ctl.py` / `verify.py`），因此**没有端到端 CI**，理由写在 README 的「测试」一节。
- `kernel/mcu_lab.py` 顶部的 `IFACE` / `KEIL` / `ISIS` / `DSN_INDEX` 四个路径常量仍是作者本机的默认值，
  **未做配置化**，使用前必须自己改（见 README 的「配置」）。
- `mcu_sim` / `mcu_verify` 只复制 `.DSN`、不复制 hex；这种情形下能否跑起来未验证。
