# Email — CCAR-F team invite

Send to: engineering@ + team leads
Subject line options below; the first is the one I'd send.

---

**Subject:** I passed the Claude Certified Architect exam — here's the four-week path if you want it too

**Cc:** team leads

---

Hi all,

I sat the **Claude Certified Architect – Foundations** exam (CCAR-F) and passed. It is a
genuinely good exam — scenario-based, and it tests judgment rather than recall. It does
not ask what a `PreToolUse` hook is. It asks whether you'd use a hook or a prompt when a
refund must never exceed $500, and then offers you four answers that all sound reasonable.

I want as many of us certified as possible, and I think **end of September is realistic**
if you start this week. Everything I used is written up and the code is open.

## The repo

**https://github.com/chan4lk/CCA-F-Experiments**

I built all six exam scenarios as running, tested code — 1,939 tests. The README is the
whole study path: the exam facts, the domain weights, a table mapping each exam scenario to
the code in the repo that implements it, and a week-by-week schedule. Start there.

The one file to open after the README is
`docs/backlog/2026-09-02-ccar-f-scenarios.md` — it maps individual exam objectives (1.4,
2.2, 4.3…) to the lines of code that exercise them.

Fair warning, and it's in the README too: every test passes offline against fakes, but
none of it has run against the live API — my key is rate-limited to zero. The logic is
tested; the wire calls are not.

## The exam

| | |
|---|---|
| Items | 60, multiple-choice and multiple-response |
| Structure | 4 scenarios drawn at random from a bank of 6 |
| Time | 120 minutes |
| Pass mark | 720 on a scaled 100–1,000 |
| Fee | $125 USD |
| Delivery | Proctored — online or Pearson VUE test centre |
| Valid | 12 months, free renewal if you do it on time |

**Bistec will reimburse the $125 on a pass.** Expense it with your score report.

Domain weights, because they should drive where your hours go:

- Agentic Architecture & Orchestration — **27%**
- Claude Code Configuration & Workflows — 20%
- Prompt Engineering & Structured Output — 20%
- Tool Design & MCP Integration — 18%
- Context Management & Reliability — 15%

## Two dates

- **Register by Thursday 10 September.** This is the one that matters. Pearson VUE slots
  fill up, and an unbooked exam is an exam you sit in November. Book it before you study
  anything.
- **Sit it by Wednesday 30 September.**

Booking goes through Pearson VUE: https://www.pearsonvue.com/us/en/anthropic.html

## What actually worked

The full nine-step version is in the README. The three that carried the most weight:

1. **Write the agentic loop by hand before reading anything about it.** One `while` loop
   on `stop_reason`, no framework. Once you have written it, every wrong answer on the
   exam about loop termination stops being plausible. `agent-loop.py` in the repo.
2. **Read the generated code, not just the prompt that generated it.** I had Claude
   implement all six scenarios. The learning was entirely in reading it back and asking
   *why is this a hook and not an instruction?* Generating it taught me nothing.
3. **Do the practice exams for the explanations, not the score.** Read the rationale on
   the questions you got *right* too. Several of mine were right for the wrong reason,
   and I'd never have found that out from the score.

Budget roughly 6–8 hours a week for four weeks. Less if you already work with the Agent
SDK daily.

## Leads

Could you make room for this in the next two sprints for anyone who wants to sit it? It's
about a day and a half of focused time spread over the month, and it maps directly onto
work we are already doing — the MCP tool design and hook patterns on the exam are the same
ones in our agent projects.

## If you're in

Reply here or ping me directly, and I'll keep a list so we can compare notes. Happy to run
a session on Domain 1 if there's interest — it's over a quarter of the exam and the part
where the repo helps most.

Book the slot first. Everything else follows from having a date.

Chandima
