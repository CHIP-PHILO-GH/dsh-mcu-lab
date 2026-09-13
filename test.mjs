// dsh-mcu-lab 零依赖测试。
//
// 这里只测「不需要 Keil、不需要 Proteus、不需要 DSH 在运行」的部分：
//   1. 语法：插件（node --check）与内核（Python 编译）
//   2. 内核命令行契约：单行 JSON、字段形状、缺文件时的结构化报错与退出码
//   3. 纯函数：内核 _dec() 的解码兜底
//   4. 仓库卫生与文档一致性：工具名一致、package.json 自洽、没有构建产物与本机路径
//
// 端到端（编译 → 仿真 → 判定）故意不在这里：它需要真实安装的 Keil C51 与 Proteus ISIS，
// 也不能用别的模拟器顶替——判定依据就是 Proteus 进程的 CPU 增长与窗口存活。
// 详见 README 的「测试」一节。

import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync, mkdtempSync, writeFileSync, copyFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(fileURLToPath(import.meta.url))
const KERNEL_DIR = join(ROOT, 'kernel')
const KERNEL = join(KERNEL_DIR, 'mcu_lab.py')
const TOOLS = ['mcu_run', 'mcu_build', 'mcu_sim', 'mcu_verify', 'mcu_list']
const SUBCOMMANDS = ['check', 'list', 'build', 'sim', 'verify', 'run']

let failures = 0
const check = (name, ok, extra = '') => {
  if (ok) {
    console.log(`✅ ${name}`)
    return
  }
  failures++
  console.log(`❌ ${name}${extra === '' ? '' : '  —— ' + extra}`)
}

/** 运行一个程序并收集 stdout / exit code；不抛异常。 */
function run(cmd, args, opts = {}) {
  try {
    const stdout = execFileSync(cmd, args, { encoding: 'utf8', timeout: 120_000, ...opts })
    return { code: 0, stdout: stdout ?? '', stderr: '' }
  } catch (e) {
    return {
      code: typeof e.status === 'number' ? e.status : 1,
      stdout: String(e.stdout ?? ''),
      stderr: String(e.stderr ?? ''),
    }
  }
}

/** 内核每次都只打一行 JSON，取最后一行非空行解析。 */
function lastJson(stdout) {
  const line = stdout.trim().split(/\r?\n/).map((s) => s.trim()).filter(Boolean).pop()
  if (!line) return null
  try {
    return JSON.parse(line)
  } catch {
    return null
  }
}

// ── 找 Python 3 ────────────────────────────────────────────────────────────
const PY_ENV = (process.env.DSH_MCU_LAB_PYTHON || '').trim()
function resolvePython() {
  const candidates = PY_ENV
    ? [[PY_ENV, []]]
    : process.platform === 'win32'
      ? [['python', []], ['py', ['-3']], ['python3', []]]
      : [['python3', []], ['python', []]]
  for (const [cmd, pre] of candidates) {
    if (run(cmd, [...pre, '-c', 'print(1)']).code === 0) return { cmd, pre }
  }
  return null
}
const py = resolvePython()
// 一律带 -B：不在仓库里留下 __pycache__（内核对纯函数测试是 import 进来的）
const pyRun = (args) => run(py.cmd, [...py.pre, '-B', ...args])
const kernel = (args) => pyRun([KERNEL, ...args])

const needPython = (name) => {
  if (py) return true
  check(name, false, '没找到 Python 3 解释器（可用 DSH_MCU_LAB_PYTHON 指定完整路径）')
  return false
}

console.log('— 1. 语法 —')
{
  const r = run(process.execPath, ['--check', join(ROOT, 'lib', 'index.js')])
  check('lib/index.js 语法正确', r.code === 0, r.stderr.trim().split('\n')[0] ?? '')
}
if (needPython('kernel/mcu_lab.py 语法正确')) {
  // 用 compile() 做纯语法检查：不生成 __pycache__，也不写任何文件
  const src = 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")'
  const r = pyRun(['-c', src, KERNEL])
  check('kernel/mcu_lab.py 语法正确', r.code === 0, (r.stderr || r.stdout).trim().split('\n').pop() ?? '')
}

console.log('\n— 2. 内核命令行契约（不需要 Keil / Proteus）—')
if (needPython('check 输出单行 JSON 且 6 个检查项齐全')) {
  const r = kernel(['check'])
  const j = lastJson(r.stdout)
  const keys = j && j.checks ? Object.keys(j.checks).sort() : []
  const expected = ['build51.py', 'dsn_index.json', 'keil_c51', 'pillow', 'proteus_ctl.py', 'proteus_isis', 'python3', 'pywin32', 'sdcc', 'verify.py']
  check('check 输出单行 JSON 且能力检查项齐全',
    !!j && typeof j.ok === 'boolean' && JSON.stringify(keys) === JSON.stringify(expected),
    `exit=${r.code} 输出=${r.stdout.trim().slice(0, 160)}`)
  check('check 的退出码与 ok 一致（0 或 1）',
    r.code === (j && j.ok ? 0 : 1), `exit=${r.code} ok=${j && j.ok}`)
}
if (needPython('list 输出 JSON，字段随索引文件走')) {
  const r = kernel(['list'])
  const j = lastJson(r.stdout)
  const shaped = !!j && typeof j.ok === 'boolean' &&
    (j.ok ? typeof j.count === 'number' && Array.isArray(j.items) && j.items.length <= 80 : typeof j.error === 'string')
  check('list 输出 JSON，字段随索引文件走', shaped, `exit=${r.code} 输出=${r.stdout.trim().slice(0, 160)}`)
}
{
  const cases = [
    ['build', ['build', join(ROOT, 'no-such-file.c')], 2, null],
    ['run', ['run', join(ROOT, 'no-such-file.c'), join(ROOT, 'no-such.DSN')], 2, 'build'],
    ['sim', ['sim', join(ROOT, 'no-such.DSN')], 2, 'sim'],
    ['verify', ['verify', join(ROOT, 'no-such.DSN')], 2, 'verify'],
  ]
  for (const [label, args, wantCode, wantStage] of cases) {
    if (!needPython(`${label}：输入不存在时给结构化报错，退出码 ${wantCode}`)) continue
    const r = kernel(args)
    const j = lastJson(r.stdout)
    const ok = r.code === wantCode && !!j && j.ok === false &&
      typeof j.error === 'string' && j.error.length > 0 &&
      (wantStage === null || j.stage === wantStage) && !/\bTraceback\b/.test(r.stderr)
    check(`${label}：输入不存在时给结构化报错，退出码 ${wantCode}`, ok,
      `exit=${r.code} 输出=${r.stdout.trim().slice(0, 200)}`)
  }
  if (needPython('缺子命令时按用法错误退出（argparse 退出码 2）')) {
    const r = kernel([])
    check('缺子命令时按用法错误退出（argparse 退出码 2）', r.code === 2 && /usage/i.test(r.stderr),
      `exit=${r.code} stderr=${r.stderr.trim().slice(0, 120)}`)
  }
}

console.log('\n— 3. 免费 SDCC 编译与离线判定通路 —')
if (needPython('SDCC/离线通路')) {
  const tmp = mkdtempSync(join(tmpdir(), 'dsh-mcu-lab-offline-'))
  try {
    const src = join(tmp, 'led_blink.c')
    copyFileSync(join(ROOT, 'examples', 'led_blink.c'), src)
    const build = kernel(['build', src, '--compiler', 'sdcc'])
    const bj = lastJson(build.stdout)
    check('SDCC 可将自带示例编译为 hex/ihx', build.code === 0 && bj?.ok === true && bj.compiler === 'sdcc' && typeof bj.hex === 'string', `exit=${build.code} 输出=${build.stdout.trim().slice(-240)}`)
    const broken = join(tmp, 'broken.c')
    copyFileSync(join(ROOT, 'examples', 'broken.c'), broken)
    writeFileSync(join(tmp, 'broken.hex'), ':00000001FF\n', 'utf8')
    const badBuild = kernel(['build', broken, '--compiler', 'sdcc'])
    const badJ = lastJson(badBuild.stdout)
    check('SDCC 编译失败不误用上次残留 hex', badBuild.code !== 0 && badJ?.ok === false && badJ.hex === null, `exit=${badBuild.code} 输出=${badBuild.stdout.trim().slice(-240)}`)
    const runDsn = join(tmp, 'run.dsn')
    writeFileSync(runDsn, '', 'utf8')
    const endToEnd = kernel(['run', src, runDsn, '--compiler', 'sdcc', '--backend', 'offline'])
    const runJ = lastJson(endToEnd.stdout)
    check('mcu_lab run 真实串起 SDCC 编译与离线判定', endToEnd.code === 0 && runJ?.ok === true && runJ.compiler === 'sdcc' && runJ.verdict === 'PASS', `exit=${endToEnd.code} 输出=${endToEnd.stdout.trim().slice(-260)}`)
    const badRun = kernel(['run', broken, runDsn, '--compiler', 'sdcc', '--backend', 'offline'])
    const badRunJ = lastJson(badRun.stdout)
    check('mcu_lab run 编译失败停在 build 阶段', badRun.code !== 0 && badRunJ?.stage === 'build', `exit=${badRun.code} 输出=${badRun.stdout.trim().slice(-220)}`)
    for (const [name, marker, wantCode, wantRunning] of [['pass.dsn', '', 0, true], ['sim-fail.dsn', 'OFFLINE_SIM_FAIL', 1, false], ['verdict-fail.dsn', 'OFFLINE_VERDICT_FAIL', 1, false]]) {
      const dsn = join(tmp, name)
      writeFileSync(dsn, marker, 'utf8')
      const r = kernel(['verify', dsn, '--backend', 'offline'])
      const j = lastJson(r.stdout)
      check(`离线后端 ${name} 真实走 verify.py`, r.code === wantCode && j?.running === wantRunning && /offline backend/.test(j?.evidence ?? ''), `exit=${r.code} 输出=${r.stdout.trim().slice(-200)}`)
    }
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
}

console.log('\n— 4. 纯函数 _dec() —')
if (needPython('_dec() 的 UTF-8 / GBK / 坏字节兜底都成立')) {
  const script = [
    'import sys, json',
    'sys.path.insert(0, sys.argv[1])',
    'import mcu_lab',
    's = "\\u4e2d\\u6587"',
    'print(json.dumps({',
    '    "gbk": mcu_lab._dec(s.encode("gbk")),',
    '    "utf8": mcu_lab._dec(s.encode("utf-8")),',
    '    "passthrough": mcu_lab._dec(s),',
    '    "bad_bytes_is_str": isinstance(mcu_lab._dec(b"\\xff\\xfe\\xff"), str),',
    '}))',
  ].join('\n')
  const r = pyRun(['-c', script, KERNEL_DIR])
  const j = lastJson(r.stdout)
  const cjk = '\u4e2d\u6587'
  check('_dec() 的 UTF-8 / GBK / 坏字节兜底都成立',
    r.code === 0 && !!j && j.gbk === cjk && j.utf8 === cjk && j.passthrough === cjk && j.bad_bytes_is_str === true,
    `exit=${r.code} 输出=${r.stdout.trim().slice(0, 160)}`)
}

console.log('\n— 5. 仓库卫生与文档一致性 —')
{
  const plugin = readFileSync(join(ROOT, 'lib', 'index.js'), 'utf8')
  const readmeZh = readFileSync(join(ROOT, 'README.md'), 'utf8')
  const readmeEn = readFileSync(join(ROOT, 'README.en.md'), 'utf8')
  const manifest = JSON.parse(readFileSync(join(ROOT, 'dsh.plugin.json'), 'utf8'))
  const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  const changelog = readFileSync(join(ROOT, 'CHANGELOG.md'), 'utf8')
  const kernelSrc = readFileSync(KERNEL, 'utf8')

  const registered = [...plugin.matchAll(/name: '(mcu_[a-z_]+)'/g)].map((m) => m[1]).sort()
  check('插件注册的工具正好是这 5 个', JSON.stringify(registered) === JSON.stringify([...TOOLS].sort()),
    `实际 ${registered.join(',')}`)
  check('插件清单 dsh.plugin.json 的 tools 与实现一致',
    JSON.stringify([...manifest.contributes.tools].sort()) === JSON.stringify([...TOOLS].sort()),
    `实际 ${(manifest.contributes.tools || []).join(',')}`)
  for (const tool of TOOLS) {
    check(`README.md 写了 ${tool}`, readmeZh.includes(tool))
    check(`README.en.md 写了 ${tool}`, readmeEn.includes(tool))
  }
  for (const sub of SUBCOMMANDS) {
    check(`内核里有 ${sub} 子命令，且两个 README 都提到`, kernelSrc.includes(`"${sub}"`) && readmeZh.includes(sub) && readmeEn.includes(sub))
  }

  check('package.json：包名是 dsh-mcu-lab 且没有 private 字段',
    pkg.name === 'dsh-mcu-lab' && !('private' in pkg) && pkg.version === '0.1.0' && pkg.license === 'MIT',
    `name=${pkg.name} private=${'private' in pkg} version=${pkg.version}`)
  check('package.json：repository / engines / files 齐备',
    typeof pkg.repository?.url === 'string' && pkg.repository.url.includes('dsh-mcu-lab') &&
    typeof pkg.engines?.node === 'string' && Array.isArray(pkg.files) && pkg.files.includes('kernel'))
  check('CHANGELOG 记着当前版本 0.1.0', changelog.includes('[0.1.0]'))

  // 插件里不许再出现写死的盘符绝对路径（这正是本仓库修掉的本机痕迹之一）
  check('lib/index.js 不含写死的盘符绝对路径', !/[A-Za-z]:[\\/]/.test(plugin))

  // 遍历仓库：不许有构建产物 / 二进制 / 超大文件
  const bannedExt = new Set(['.hex', '.lst', '.m51', '.obj', '.dsn', '.dbk', '.workspace', '.uvproj', '.uvopt',
    '.exe', '.dll', '.bin', '.png', '.jpg', '.jpeg', '.gif', '.zip', '.7z', '.pdf', '.so', '.dylib', '.pyc'])
  const textExt = new Set(['.md', '.js', '.mjs', '.json', '.yml', '.yaml', '.c', '.h', '.py', '.txt', ''])
  const skipDir = new Set(['node_modules', '.git', 'work'])
  // 本机痕迹的针：拆开拼，避免测试文件自己命中自己
  const machineRoot = ['D:', '\\', 'dsh-workspace'].join('')
  const needles = [
    ['C:', '\\', 'Users', '\\'].join(''),
    machineRoot,
    String.fromCharCode(0x5317, 0x54f2),
  ]
  // kernel/mcu_lab.py 顶部的 IFACE / KEIL / ISIS / DSN_INDEX 是「作者本机的路径默认值」，
  // 使用者必须自己改（见 README 的「配置」）。这是有意保留的，但**只允许出现在这一个文件里**：
  // 一旦它出现在别处（文档、测试、插件代码），这里就会报错。
  const knownLocalPathFile = 'kernel/mcu_lab.py'
  let knownLocalPathHits = 0
  const offenders = []
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (!skipDir.has(entry.name)) walk(join(dir, entry.name))
        continue
      }
      const full = join(dir, entry.name)
      const rel = relative(ROOT, full).split('\\').join('/')
      const size = statSync(full).size
      const ext = extname(entry.name).toLowerCase()
      if (bannedExt.has(ext)) offenders.push(`构建产物/二进制: ${rel}`)
      if (size > 300 * 1024) offenders.push(`超过 300KB: ${rel}`)
      if (!textExt.has(ext)) continue
      let text
      try {
        text = readFileSync(full, 'utf8')
      } catch {
        continue
      }
      for (const needle of needles) {
        if (!text.includes(needle)) continue
        if (needle === machineRoot && rel === knownLocalPathFile) {
          knownLocalPathHits++
          continue
        }
        offenders.push(`本机痕迹 ${JSON.stringify(needle)}: ${rel}`)
      }
    }
  }
  walk(ROOT)
  check('仓库里没有构建产物 / 二进制 / 超大文件，也没有本机路径', offenders.length === 0, offenders.join(' | '))
  console.log(`ℹ️  ${knownLocalPathFile} 内保留 ${knownLocalPathHits} 处作者本机路径常量（IFACE / KEIL / ISIS / DSN_INDEX），使用前须自行修改`)
}

console.log(failures === 0 ? `\n全部通过（${new Date().toISOString()}）` : `\n${failures} 项失败`)
process.exitCode = failures === 0 ? 0 : 1
