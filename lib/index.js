/**
 * dsh-mcu-lab —— 把 51 单片机开发闭环接进 DSH
 *
 * 注册 5 个工具，底层调用仓库内的命令行内核 kernel/mcu_lab.py：
 *   mcu_run     编译 + Proteus 仿真 + 确定性判定（推荐入口）
 *   mcu_build   Keil C51 或 SDCC 编译出 hex
 *   mcu_sim     打开电路跑仿真并截图
 *   mcu_verify  只做确定性判定（不改文件）
 *   mcu_list    列出电路模板索引里的模板
 *
 * 设计约束：
 *  - 每次仿真都在独立工作目录做副本，绝不修改用户的原始 .DSN
 *  - 判定不依赖截图识别，用 verify.py 的进程 CPU 增长 + 失败标记文本
 *  - 所有工具返回结构化 JSON，路径为绝对路径
 *
 * 前置条件（缺任何一样，对应工具会返回 ok:false 并说明原因）：
 *  - 编译优先使用 Keil C51，缺失时可回退到免费 SDCC；仿真要本机装好 Proteus ISIS
 *  - 内核还会调用 `kernel/iface/` 下的 build51.py / proteus_ctl.py / verify.py（随本仓库发布）
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'mcu-lab'
export const inject = ['tools']

// 本插件是薄壳，真正的活由命令行内核 kernel/mcu_lab.py 干。两个路径都可用环境变量覆盖，
// 默认值按本文件位置推算，不写死任何本机绝对路径：
//   DSH_MCU_LAB_CLI     内核脚本路径，默认 <本仓库根>/kernel/mcu_lab.py
//   DSH_MCU_LAB_PYTHON  Python 解释器，默认按 PATH 查找（Windows 找 python，其他平台找 python3）
const HERE = dirname(fileURLToPath(import.meta.url))   // <本仓库根>/lib
const REPO_ROOT = resolve(HERE, '..')
const DEFAULT_CLI = join(REPO_ROOT, 'kernel', 'mcu_lab.py')

function envValue(name) {
  const v = process.env[name]
  return v && v.trim() ? v.trim() : null
}

const CLI = envValue('DSH_MCU_LAB_CLI') || DEFAULT_CLI
const PY = envValue('DSH_MCU_LAB_PYTHON') || (process.platform === 'win32' ? 'python' : 'python3')
const TIMEOUT_MS = 300000

function runCli(args, signal) {
  return new Promise((resolve, reject) => {
    if (!existsSync(CLI)) {
      reject(new Error(
        '找不到内核脚本 mcu_lab.py：' + CLI + '\n' +
        '它应当是本仓库里的 kernel/mcu_lab.py；若你把内核放在别处，' +
        '请用环境变量 DSH_MCU_LAB_CLI 指定它的完整路径。'
      ))
      return
    }
    const child = spawn(PY, [CLI, ...args], { windowsHide: true })
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      try { child.kill() } catch { /* ignore */ }
      reject(new Error('mcu-lab 超时（' + TIMEOUT_MS + 'ms）: ' + args.join(' ')))
    }, TIMEOUT_MS)
    const onAbort = () => { try { child.kill() } catch { /* ignore */ } }
    if (signal) signal.addEventListener('abort', onAbort, { once: true })
    child.stdout.on('data', (d) => { stdout += d.toString('utf8') })
    child.stderr.on('data', (d) => { stderr += d.toString('utf8') })
    child.on('error', (e) => {
      clearTimeout(timer)
      if (e && e.code === 'ENOENT') {
        reject(new Error(
          '找不到 Python 解释器：' + PY + '\n' +
          '内核需要 Python 3；请确认 python 在 PATH 上，' +
          '或用环境变量 DSH_MCU_LAB_PYTHON 指定解释器的完整路径。'
        ))
        return
      }
      reject(e)
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (signal) signal.removeEventListener('abort', onAbort)
      const line = stdout.trim().split(/\r?\n/).filter(Boolean).pop()
      let parsed = null
      if (line) {
        try { parsed = JSON.parse(line) } catch { parsed = null }
      }
      if (!parsed) {
        reject(new Error('mcu-lab 未返回 JSON（exit=' + code + '）：' + (stderr || stdout).slice(-500)))
        return
      }
      parsed._exit_code = code
      resolve(parsed)
    })
  })
}

function textRender(fn) {
  return (_args, value) => [{ type: 'text', text: fn(value) }]
}

const JSON_OUT = (props) => ({
  schema: { type: 'object', additionalProperties: true, properties: props },
  render: textRender((v) => JSON.stringify(v, null, 1)),
})

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'mcu_run',
    description:
      '51 单片机端到端闭环：把一段 C51 源码用 Keil 或 SDCC 编译成 hex，复制到指定 Proteus 电路的工作副本里跑仿真，' +
      '再用确定性方法判定仿真是否真的在运行。不修改任何原始电路文件。' +
      '返回 verdict=PASS/FAIL 以及 hex 路径、仿真证据、工作目录。',
    parameters: {
      source_path: { type: 'string', required: true, description: 'C51 源文件绝对路径（必须纯 ASCII，不能有中文注释）' },
      dsn_path: { type: 'string', required: true, description: 'Proteus 电路文件（.DSN）绝对路径' },
      hex_name: { type: 'string', description: '电路期望的 hex 文件名，默认与 DSN 同名加 .hex' },
      wait_seconds: { type: 'number', description: '仿真运行观察时长（秒），默认 6' },
    },
    output: JSON_OUT({
      ok: { type: 'boolean', required: true },
      verdict: { type: 'string' },
      stage: { type: 'string' },
      hex: { type: 'string' },
      evidence: { type: 'string' },
      workdir: { type: 'string' },
      elapsed_sec: { type: 'number' },
    }),
    execute: async (args, exec) => {
      exec.signal.throwIfAborted()
      const a = ['run', args.source_path, args.dsn_path]
      if (args.hex_name) a.push('--hex-name', args.hex_name)
      if (args.wait_seconds) a.push('--wait', String(args.wait_seconds))
      return await runCli(a, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'mcu_build',
    description: '用 Keil C51 或免费 SDCC 把单文件 8051 源码编译成 hex（自动优先 Keil），返回 hex 绝对路径与编译日志尾部。',
    parameters: {
      source_path: { type: 'string', required: true, description: 'C51 源文件绝对路径（纯 ASCII）' },
    },
    output: JSON_OUT({
      ok: { type: 'boolean', required: true },
      hex: { type: 'string' },
      log_tail: { type: 'string' },
    }),
    execute: async (args, exec) => {
      exec.signal.throwIfAborted()
      return await runCli(['build', args.source_path], exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'mcu_sim',
    description: '启动 Proteus ISIS 打开指定电路并运行仿真，截图后自动关闭。只用于看现象，判定请用 mcu_verify 或 mcu_run。',
    parameters: {
      dsn_path: { type: 'string', required: true, description: 'Proteus 电路文件（.DSN）绝对路径' },
      seconds: { type: 'number', description: '运行秒数，默认 8' },
      shot_path: { type: 'string', description: '截图输出路径，默认落在工作目录' },
    },
    output: JSON_OUT({
      ok: { type: 'boolean', required: true },
      shot: { type: 'string' },
      workdir: { type: 'string' },
    }),
    execute: async (args, exec) => {
      exec.signal.throwIfAborted()
      const a = ['sim', args.dsn_path]
      if (args.seconds) a.push('--seconds', String(args.seconds))
      if (args.shot_path) a.push('--shot', args.shot_path)
      return await runCli(a, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'mcu_verify',
    description: '对指定 Proteus 电路做确定性仿真判定（不靠截图猜）：返回 running 布尔值与判定依据文本。',
    parameters: {
      dsn_path: { type: 'string', required: true, description: 'Proteus 电路文件（.DSN）绝对路径' },
      wait_seconds: { type: 'number', description: '观察时长（秒），默认 6' },
    },
    output: JSON_OUT({
      ok: { type: 'boolean', required: true },
      running: { type: 'boolean' },
      evidence: { type: 'string' },
      errors: { type: 'array' },
      status_text: { type: 'string' },
    }),
    execute: async (args, exec) => {
      exec.signal.throwIfAborted()
      const a = ['verify', args.dsn_path]
      if (args.wait_seconds) a.push('--wait', String(args.wait_seconds))
      return await runCli(a, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'mcu_list',
    description: '列出内核配置的电路模板索引（dsn_index.json）里的 Proteus 电路模板，最多返回 80 条。模板数量取决于索引文件，换一台机器会不同。',
    parameters: {},
    output: JSON_OUT({
      ok: { type: 'boolean', required: true },
      count: { type: 'integer' },
      items: { type: 'array' },
    }),
    execute: async (_args, exec) => {
      exec.signal.throwIfAborted()
      return await runCli(['list'], exec.signal)
    },
  }))

  ctx.logger?.info?.('dsh-mcu-lab: 5 tools registered (mcu_run/mcu_build/mcu_sim/mcu_verify/mcu_list)')
}
