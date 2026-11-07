# local-llm

An [Agent Skill](https://agentskills.io) for running local LLMs and wiring them
into agent harnesses. It targets llama.cpp on a consumer GPU (12 GB class), and
covers the part most guides skip: the **harness**.

The same weights can score 62% in one harness and 33% in another, and context
management alone nearly doubles solved tasks in a small window. The skill
encodes what that means in practice.

## Contents

```
skills/local-llm/
├── SKILL.md                     workflow, hard rules, symptom table
├── references/
│   ├── server.md                llama-server for agents: flags, MoE offload, prompt cache, MTP, router
│   ├── models.md                model and quant choice by VRAM/RAM, with evidence
│   ├── harnesses.md             harness evidence, ranking, context rules, Claude Code setup
│   ├── harness-configs.md       Pi, Qwen Code, mini-swe-agent, OpenCode configs for a small window
│   └── troubleshooting.md       symptom → cause → fix
└── scripts/
    └── llm_probe.py             endpoint probe: health, context, tool call, prefix cache, tok/s, /v1/messages
layer-template/                  starting point for your personal layer (~/.local-llm)
tests/                           mock llama-server + probe tests
```

## Install

Claude Code, by symlink (keeps it updatable with `git pull`):

```bash
git clone <this repo> ~/Software/local-llm
ln -s ~/Software/local-llm/skills/local-llm ~/.claude/skills/local-llm
```

Other agents: `npx skills add <owner>/local-llm`.

## Local layer

The skill stays general. Your own setup goes in a layer folder that the skill
reads before answering: `~/.local-llm/` (or `$LOCAL_LLM_HOME`, or
`.local-llm/` in a project). Start from `layer-template/`:

```bash
cp -r layer-template ~/.local-llm
mv ~/.local-llm/machines/HOSTNAME.md ~/.local-llm/machines/$(hostname -s).md
```

| File | Holds |
|---|---|
| `profile.md` | goals and preferences, on every machine |
| `machines/<hostname>.md` | hardware, paths, build, quirks, models, measurements |
| `notes.md` | notes attached to a section of the skill (`## <file>#<heading slug>`) |

The agent writes machine facts and measurements there, never into the skill.

## Probe a server

```bash
python3 -I skills/local-llm/scripts/llm_probe.py --url http://127.0.0.1:9931
```

It needs the standard library only. It exits with 1 if any check fails.
Run `tests/test_probe.sh` to test the probe itself against a mock server.

## Scope and freshness

Facts are dated November 2026 and were checked against llama.cpp build b12189.
llama.cpp changes defaults often, so the skill tells the agent to verify flags
against `llama-server --help` on the installed build. Model recommendations
age within months.

## License

MIT
