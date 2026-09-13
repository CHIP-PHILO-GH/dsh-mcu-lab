# dsh-mcu-lab

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/CHIP-PHILO-GH/dsh-mcu-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/CHIP-PHILO-GH/dsh-mcu-lab/actions/workflows/ci.yml)

Wire the 8051 development loop — "compile with Keil C51 → simulate in Proteus → decide deterministically" —
into a DSH session, so the AI can compile a hex, run a circuit and hand back PASS/FAIL together with the
evidence behind that call.

---

## What this is

A DSH plugin (`lib/index.js`) plus a command-line kernel (`kernel/mcu_lab.py`). They are two layers of one thing:

- **Plugin layer**: registers 5 tools with DSH, takes the AI's arguments, spawns the kernel, and returns the
  kernel's single-line JSON to the session. It does not compile or simulate anything itself — it is a thin shell.
- **Kernel layer**: the Python script that does the actual work. Six subcommands
  (`check` / `list` / `build` / `sim` / `verify` / `run`), each printing single-line JSON.
  **It works from the command line on its own, with no plugin installed.**

The problem it solves is concrete: verifying MCU coursework used to mean a human staring at Proteus to see
whether an LED blinks, or a vision model reading a screenshot (pin numbering drifts, so the verdict wobbles).
Here the decision is made from two deterministic signals — whether compilation produced a hex, whether the
simulation process' CPU is growing, and whether any failure markers appeared.

## Repository layout

| Path | What it is |
|---|---|
| `lib/index.js` | The DSH plugin itself; registers the 5 tools |
| `kernel/mcu_lab.py` | **The command-line kernel** (Python 3, standard library only); this is what the plugin calls |
| `kernel/README.md` | The kernel's own documentation (including the original author's on-machine test records) |
| `examples/led_blink.c` | Example: LED blink on P3.7 of an AT89C51 (positive case) |
| `examples/broken.c` | Example: deliberately broken code with a missing semicolon (negative case, to show compile failures are caught) |
| `docs/PROJECT_LOG.md` | The original project's development log (decisions, pitfalls, historical test data) |
| `cordis.patch.yml` / `dsh.plugin.json` | The patch layer and plugin manifest used for loading into DSH |
| `test.mjs` | Zero-dependency tests (no Keil / Proteus / DSH required) |

The kernel is **part of this repository**, not an external dependency: `kernel/mcu_lab.py` ships with the repo,
and the plugin uses that copy by default.

## The five tools: what each one does and how to choose

| Tool | What it does | Prerequisites | When to use it |
|---|---|---|---|
| `mcu_run` | Compile → copy the hex into a working copy of the circuit → simulate → decide; returns `verdict: PASS/FAIL` plus evidence and the working directory | Keil C51 + Proteus ISIS + the three external scripts | **The default entry point**: you just want to know whether this code runs on that circuit |
| `mcu_build` | Compile a single-file C51 source into a hex with Keil C51 only; returns the hex path and the tail of the log | Keil C51 + `build51.py` | You only want to chase C51 syntax errors and do not want to touch the circuit yet (fast, and it leaves circuit files alone) |
| `mcu_sim` | Open the given circuit, simulate for a while, take a screenshot, then close it | Proteus ISIS + `proteus_ctl.py` | You only want to see the behaviour or hand a screenshot to someone; do **not** use it to decide pass/fail |
| `mcu_verify` | Deterministic verdict for the given circuit only; returns `running` plus the reasoning text | Proteus ISIS + `verify.py` | The circuit and hex are already in place and you want a re-check; or you do not want any file modified |
| `mcu_list` | List the circuit templates in the circuit index (`dsn_index.json`), at most 80 entries | Only the index file (**no** Keil / Proteus needed) | Find a usable `.DSN` first, then hand its path to the tools above |

In one sentence: **want a verdict, use `mcu_run`; only chasing compile errors, use `mcu_build`; only want a
screenshot, use `mcu_sim`; only want a re-check, use `mcu_verify`; looking for a circuit, use `mcu_list`.**

Arguments and return values (from `lib/index.js`):

| Tool | Arguments | Main returned fields |
|---|---|---|
| `mcu_run` | `source_path` (required, absolute path to the C51 source), `dsn_path` (required, absolute path to the `.DSN`), `hex_name`, `wait_seconds` (default 6) | `ok` `verdict` `stage` `hex` `evidence` `workdir` `elapsed_sec` |
| `mcu_build` | `source_path` (required) | `ok` `hex` `log_tail` |
| `mcu_sim` | `dsn_path` (required), `seconds` (default 8), `shot_path` | `ok` `shot` `workdir` |
| `mcu_verify` | `dsn_path` (required), `wait_seconds` (default 6) | `ok` `running` `evidence` `errors` `status_text` |
| `mcu_list` | none | `ok` `count` `items` |

You do not have to memorise the arguments in a session; just say what you want, for example:
> Run `examples/led_blink.c` on this circuit and tell me whether it passed.

## Prerequisites (you must supply these yourself)

Everything below is **not** in this repository and must be installed or prepared by you. Where there is no
evidence for a version requirement, the table says "unverified" instead of guessing.

| Component | Notes | Version requirement | Basis |
|---|---|---|---|
| Keil C51 toolchain | `C51.exe` / `BL51.exe` / `OH51.exe`; needed by the compile step of `mcu_build` / `mcu_run` | **Minimum / maximum version unverified.** In the original author's tested environment `C51.exe` reports file version `9.00` (description `C51/ CX51 Compiler`), read during this packaging pass | Reading the kernel code: it invokes the toolchain at a fixed path and contains no version check whatsoever |
| Proteus ISIS | `ISIS.EXE`; needed by the simulation step of `mcu_sim` / `mcu_verify` / `mcu_run` | **Minimum / maximum version unverified.** In the original author's tested environment `ISIS.EXE` reports file version `7.08 SP2 IB10468` (description `ISIS Schematic Capture`) | Same as above |
| Python 3 | Runs the kernel script; the simulation step of `mcu_sim` / `mcu_verify` / `mcu_run` also runs the interface scripts, which need third-party packages | The original author tested `3.13.15`; other versions **unverified** | `kernel/mcu_lab.py` uses only the Python standard library: `argparse` `json` `os` `shutil` `subprocess` `sys` `time` `glob` (confirmed by reading its import lines). But `kernel/iface/proteus_ctl.py` imports `win32api` / `win32con` / `win32gui` / `win32ui` / `PIL` at the top, and `verify.py` imports `win32gui`. **So "compile to hex" needs only the standard library; running a simulation / verdict additionally needs `pip install pywin32 Pillow`.** pyserial is not needed |
| External interface scripts | `build51.py` (drives Keil), `proteus_ctl.py` (starts/stops simulation, screenshots), `verify.py` (the deterministic verdict) | **Bundled with this repository**: `kernel/iface/` | The kernel calls them from that directory by default; point `DSH_MCU_LAB_IFACE` at your own directory to use your copies. The actual decision logic lives in `verify.py` |
| Circuit template index | `dsn_index.json`, the data source for `mcu_list` | Unverified (not in this repository) | The kernel's `cmd_list` reads that file directly and returns `ok:false` when it is missing |
| Operating system | The kernel uses Windows paths and invokes Windows executables | The original author tested Windows 11; **other platforms unverified** | The kernel spawns `C51.exe` / `ISIS.EXE` as child processes and has no cross-platform branch |
| Node.js | Runs the plugin and the tests | `>= 18` (`engines.node` in `package.json`) | The author's environment is Node v24.19.0 |
| DSH | The plugin host (not needed if you only use the command-line kernel) | The plugin manifest declares `>=0.0.1` | That value comes from the plugin manifest and has not been verified across versions |

Two further notes carried over from the kernel documentation (stated by the original author, not reproduced
during this packaging pass):

- The Proteus installation path **must be pure ASCII**; a path containing non-ASCII characters crashes it.
- C51 source **must be pure ASCII**; comments containing non-ASCII characters produce syntax errors such as C141.

## Installing

### Option 1: install into DSH (to get the 5 tools)

1. Put this repository into the DSH profile module directory, with a directory name matching the package name:

   ```text
   <DSH_HOME>\profiles\node_modules\dsh-mcu-lab\
   ```

   `<DSH_HOME>` defaults to `%USERPROFILE%\.dsh` (overridable with the `DSH_HOME` environment variable).

2. Append the loading line to that profile's `cordis.patch.yml` (identical to this repository's `cordis.patch.yml`):

   ```yaml
   - insert:
       - id: mcu-lab
         name: 'dsh-mcu-lab'
   ```

3. After restarting DSH (`dsh web`), the 5 tools appear in the session.

> This repository ships no installer: the copy above plus the loading line is the whole procedure.
> Where to install it, and whether to install it at all, is your call.

### Option 2: use the command-line kernel only (no DSH)

```bat
python kernel/mcu_lab.py check
python kernel/mcu_lab.py list
python kernel/mcu_lab.py build examples\led_blink.c
python kernel/mcu_lab.py run  examples\led_blink.c <your-circuit.DSN> --wait 6
python kernel/mcu_lab.py verify <your-circuit.DSN> --wait 6
python kernel/mcu_lab.py sim <your-circuit.DSN> --seconds 8 --shot out.png
```

Every subcommand prints its result as single-line JSON. Exit code 0 means success, 1 means it ran but failed,
and 2 means missing input (for example a source file or circuit that does not exist).

### How the kernel is bundled

- The kernel **ships with the repository** at the fixed path `kernel/mcu_lab.py`; the default the plugin calls is
  exactly this in-repo copy, derived from the plugin file's own location via `import.meta.url`
  (`<repo root>/kernel/mcu_lab.py`), so **there is no separate kernel install and no path to configure**.
- The kernel `kernel/mcu_lab.py` itself uses only the Python standard library, so `pip install` is not required for
  it (**pyserial is not needed**). The interface scripts it calls during simulation do need packages, though:
  `kernel/iface/proteus_ctl.py` needs `win32api` / `win32gui` / `win32ui` / `PIL` (pywin32 + Pillow) and
  `verify.py` uses `win32gui`. `check` / `list` / `build` alone do not need them.
- The kernel does write things: every `sim` / `verify` / `run` creates a working copy under
  `kernel/work/<timestamp>/` (copies of the `.DSN` and hex, screenshots, evidence files). That directory is
  excluded by `.gitignore`.
- The kernel's original documentation (written on the author's machine) is kept at `kernel/README.md`, and the
  development log at `docs/PROJECT_LOG.md`.

## Configuration

### Plugin side: two environment variables

| Environment variable | Purpose | Default |
|---|---|---|
| `DSH_MCU_LAB_CLI` | Path to the kernel script `mcu_lab.py` | `<repo root>/kernel/mcu_lab.py` (derived from the plugin file's location) |
| `DSH_MCU_LAB_PYTHON` | Path to the Python interpreter | `python` on Windows, `python3` elsewhere (i.e. looked up on `PATH`) |

When the kernel or the interpreter cannot be found, the tool returns an error telling you which environment
variable to set, instead of failing silently. Both variable names are the ones the original plugin used; the
spelling is unchanged.

### Kernel side: every path can be overridden by an environment variable

Neither the kernel nor the interface scripts it calls hard-code your machine's paths — override them as below;
the defaults apply when a variable is unset.

| Environment variable | Purpose | Default |
|---|---|---|
| `DSH_MCU_LAB_IFACE` | Directory of the interface scripts (`build51.py` / `proteus_ctl.py` / `verify.py`) | **Bundled**: `kernel/iface/` |
| `DSH_MCU_LAB_KEIL` | Path to `C51.exe` (only the `check` subcommand inspects it) | `D:\keil\C51\BIN\C51.exe` |
| `DSH_MCU_LAB_ISIS` | Path to `ISIS.EXE` (inspection and simulation control) | `D:\Proteus7\BIN\ISIS.EXE` |
| `DSH_MCU_LAB_DSN_INDEX` | Path to `dsn_index.json` (only `mcu_list` uses it) | **empty** — no circuit index ships with this repository |
| `DSH_MCU_LAB_KEIL_DIR` | Keil installation root (used by the interface script `build51.py`) | `D:\keil` |
| `DSH_MCU_LAB_PROTEUS_TEMP` | Temporary directory for the Proteus simulation | `D:\proteus_temp` |
| `DSH_MCU_LAB_SDCC_BIN` | SDCC toolchain directory (only when using `sdcc51.py`) | `D:\sdcc\bin` |

The three `D:\...` defaults are the original author's own Windows paths on his machine (not generic paths — they
will not match yours). Run `python kernel/mcu_lab.py check` first: it reports item by item which paths do not exist.

## Scope and limitations

An honest line between what it does and does not do:

- **The repository does not bundle the toolchain.** A fresh clone cannot run the full loop on its own:
  Keil C51 and Proteus ISIS are commercial tools you install yourself, and the template index
  (`dsn_index.json`) is not here either. The three interface scripts **do ship with the repository**
  (`kernel/iface/`). `check` lists whatever is missing.
- **The decision logic lives in the bundled `verify.py`.** `mcu_verify` / `mcu_run` decide by calling
  `kernel/iface/verify.py` and parsing the last line of JSON it prints; the criteria themselves (process CPU
  growth, failure-marker text, window liveness) live in that file. Point `DSH_MCU_LAB_IFACE` elsewhere and your
  own copy is used instead.
- **`mcu_sim` / `mcu_verify` copy only the `.DSN`, not the hex** (visible in the kernel's `cmd_sim` /
  `cmd_verify`: they call `_stage_dsn` without a hex path). Whether such a circuit still runs from the working
  copy, when the hex it references lives elsewhere, is **unverified**; for end-to-end verification use
  `mcu_run`, which copies the hex too.
- **Your original circuits are never modified**: every run works on a copy under `kernel/work/<timestamp>/`,
  and the original `.DSN` is not written to (a design constraint that can be checked in the code path).
- **`mcu_list` output follows the index file** and returns at most 80 entries (the kernel does `items[:80]`).
  The "79 templates" figure in the original documentation is the size of the author's own index, not a
  capability of this plugin.
- **The verdict is "the simulation is really running", not "the circuit works as intended".** Whether the LED
  blinks at the rate you wanted is something the verdict does not know; it reports that the program started and
  no failure markers appeared.
- **There is no end-to-end CI**: see the next section. Any claim that "CI verified the compile/simulation" is
  false for this repository.

## Testing

### What runs: zero-dependency tests

```bash
node test.mjs      # same as npm test
```

Requires **Node ≥ 18 + Python 3**; it does **not** require Keil, Proteus, or a running DSH. It covers four areas:

1. **Syntax**: `node --check lib/index.js`, and compiling `kernel/mcu_lab.py`.
2. **Kernel command-line contract** (the part that does not need Keil/Proteus): `check` / `list` print a single
   line of JSON with the right field shapes; `build` / `run` / `sim` / `verify` return a **structured error with
   exit code 2** when the source or circuit does not exist, instead of throwing a traceback.
3. **Pure functions**: the kernel's `_dec()` decoding fallback (UTF-8 → GBK → replacement characters), plus
   string pass-through.
4. **Repository hygiene and doc consistency**: the tool names registered by `lib/index.js` match both READMEs;
   `package.json`'s name/version/`files` line up; the repository contains no Keil/Proteus build artifacts and no
   machine-local traces such as an absolute path inside a Windows user profile.

### What cannot run: why there is no end-to-end CI

The thing really worth verifying is the "compile → simulate → decide" chain, and that needs **Keil C51** and
**Proteus ISIS** installed on the machine:

- Both are commercial software. GitHub Actions runners do not have them, and no portable substitute produces
  the same evidence — the verdict rests on Proteus' process CPU growth and window liveness, and switching to a
  different simulator would change the criteria;
- The interface scripts the chain passes through (`build51.py` / `proteus_ctl.py` / `verify.py`) do ship here,
  in `kernel/iface/`, but they only drive Keil and Proteus — they cannot replace them.

Therefore `.github/workflows/ci.yml` runs **only the zero-dependency tests 1–4 above**, and does not pretend,
in any byte, to have run a compile or a simulation.

### How to verify the end-to-end path yourself

Install Keil C51 and Proteus ISIS on your machine, point the kernel's path environment variables per the
"Configuration" section at your installation (or edit the defaults), then:

```bat
python kernel/mcu_lab.py check
:: expect 6/6 true; anything missing is listed as false

python kernel/mcu_lab.py run examples\led_blink.c <your-circuit.DSN> --wait 6
:: expect the last JSON line to have ok=true and verdict=PASS, with CPU growth and "no failure markers" in evidence

python kernel/mcu_lab.py run examples\broken.c <the-same-circuit.DSN> --wait 6
:: the negative case: expect ok=false and stage=build, with a syntax error such as C141 in log_tail
```

### The original author's on-machine test record (2026-09-08)

The data below comes from the original project log (`docs/PROJECT_LOG.md`) and is a historical record produced
**on a machine with Keil C51 and Proteus 7.8 installed** — **not** produced by this packaging pass:

| Test | Result |
|---|---|
| `mcu_lab.py check` | 6/6 passed |
| Positive: `led_blink.c` → ex4 circuit | `verdict: PASS`, 11.0 seconds, evidence `process CPU advanced 0.172s; ISIS window alive; no failure markers` |
| Negative 1: `broken.c` (syntax error) | `ok:false, stage:build`, log contains `ERROR C141` |
| Negative 2: circuit file does not exist | `ok:false, stage:verify`, explicit error |
| `mcu_lab.py list` | returned 79 templates |

The commands actually run during this packaging pass, and their results, are recorded in the delivery notes
(conclusion: all zero-dependency tests passed; the end-to-end path was not re-run).

## License

[MIT](LICENSE) © 2026 CHIP-PHILO-GH

Keil and Proteus are commercial products of their respective companies; this repository neither contains nor
redistributes them.
