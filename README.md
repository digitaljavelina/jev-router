# jev-router

Route each Claude Code message to the right size of model, automatically.

You type a message. Before Claude sees it, a small fast classifier called [Jev](https://typesafe.ai) reads it and decides how much work it really is. Grunt work gets handed to a cheap model. Hard thinking stays with your strong one. You do nothing.

```
you: rename every .jpeg under Attachments to .jpg and fix the wikilinks
     [jev: bulk 0.99]  ->  handed to a Haiku sub-agent

you: my n8n workflow drops 1 in 40 webhooks and I cannot work out why
     [jev: hard 1.00]  ->  stays with your main model
```

It costs about **three cents per thousand messages** and adds about **250 milliseconds** per message. It is off by default, and if anything goes wrong it gets out of the way and your message goes through untouched.

Inspired by [Jev will 10x your Claude Code](https://youtu.be/tTnUcSj-QPA) by Jay E at RoboNuggets.

---

## Table of contents

- [What it actually does](#what-it-actually-does)
- [What it honestly saves](#what-it-honestly-saves)
- [Install](#install)
- [Using it](#using-it)
- [The presets](#the-presets)
- [What it costs](#what-it-costs)
- [The honest limits](#the-honest-limits)
- [When not to turn this on](#when-not-to-turn-this-on)
- [Privacy](#privacy)
- [How it works under the hood](#how-it-works-under-the-hood)
- [Uninstall](#uninstall)

---

## What it actually does

Claude Code cannot swap models in the middle of a message. Once you press enter, the model answering you is already locked in. No hook can change that.

What Claude Code *can* do is hand a job to a **sub-agent**, which is a separate Claude session spawned to do one task and report back, and a sub-agent can run on any model you pick. That is the lever this tool pulls.

Every message you type gets sorted into one of four buckets:

| bucket | what it means | default handling |
|---|---|---|
| `tiny` | a greeting, a quick question, a short follow-up like "make it shorter" | your main model answers it directly |
| `bulk` | lots of mechanical work, obvious steps, high volume: searching many files, renaming, extracting, reformatting | **Haiku sub-agent** |
| `standard` | ordinary coding or writing that needs real but routine judgment | **Sonnet sub-agent** |
| `hard` | architecture, tradeoffs, debugging an unknown cause, subtle correctness | your main model answers it directly |

Two of those four keep the work with your main model. That is deliberate, and it is the first thing most people get wrong about this idea.

### Why tiny work is *not* sent to a cheap model

It sounds obvious that a trivial question should go to the cheapest model available. It is wrong, and it is wrong by about a hundredfold.

A sub-agent starts from nothing. Before it reads a single word of your question it has to be handed a system prompt and the description of every tool it can use. That is thousands of tokens of setup, every time. If you ask "what's 2+2", your main model answering inline costs around five tokens. Spinning up a Haiku sub-agent to do the same job costs the whole setup first.

Delegation is only worth paying for when there is enough work on the other side to earn back the setup. That is `bulk` and `standard`. It is never `tiny`.

---

## What it honestly saves

Less than you might hope, and it is worth being straight about why.

The biggest cost in a long Claude Code session is not any single reply. It is that your main model re-reads the growing conversation on every turn. This router does not touch that. It only moves the *work* off your expensive model, not the *reading*.

So the saving comes from the middle two buckets. If most of your messages land in `bulk` and `standard`, this earns its keep. If nearly everything you send comes back `tiny` or `hard`, it will not do much for you, and you should turn it off rather than pretend.

Run it for a week, then look at `jev status`. The counts tell you the answer. This README is not going to promise you a percentage it cannot back up.

---

## Install

You need three things: Claude Code, Python 3, and a TypeSafe API key.

### Step 1: get the code

```bash
git clone https://github.com/digitaljavelina/jev-router.git
cd jev-router
```

`git clone` downloads a copy of this repository to your machine. If you do not have `git`, install it first, or download the ZIP from the green Code button on GitHub and unzip it.

### Step 2: run the installer

```bash
./install.sh
```

The installer **shows you every change before it makes any of them**, then waits for you to type `y`. Read the list. If you do not like what it says, type anything else and nothing happens.

Here is what it will do:

- Create `~/.claude/jev-router/route.py`, the classifier that runs on each message
- Create `~/.claude/jev-router/config.json`, your settings, starting switched off
- Create `~/.local/bin/jev`, the on/off/status command
- Back up your `~/.claude/settings.json`
- Add **one** hook to that settings file. Your existing hooks are left alone.

A **hook** is a script Claude Code runs automatically at a certain moment. This one runs each time you submit a message.

If the installer warns you that `~/.local/bin` is not on your `PATH`, add this line to the end of `~/.zshrc` (or `~/.bashrc` if you use bash) and open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`PATH` is the list of folders your terminal searches when you type a command. If the folder holding `jev` is not on it, typing `jev` gets you "command not found".

### Step 3: get a TypeSafe API key

Sign up at [typesafe.ai](https://typesafe.ai) and create a key. New signups come with $5 in credit, which at this router's measured usage is roughly 165,000 messages. You are unlikely to spend it.

Save the key where the router looks for it:

```bash
mkdir -p ~/.config/typesafe
echo 'YOUR_KEY_HERE' > ~/.config/typesafe/key
chmod 600 ~/.config/typesafe/key
```

`chmod 600` makes the file readable only by you. Do this. A key in a world-readable file is a key you have given away.

The router also accepts the key from a `TYPESAFE_API_KEY` environment variable if you prefer that.

### Step 4: restart Claude Code

Hooks are read when Claude Code starts. Quit it and open it again.

### Step 5: turn it on

```bash
jev on
```

That is it. Send a normal message, then run `jev status` and you should see the counter move.

---

## Using it

Everything is one command. Inside a Claude Code session you can run these without leaving the chat by putting `!` in front, which runs a shell command directly instead of sending it to the model:

```
! jev status
```

| command | what it does |
|---|---|
| `jev on` | start routing |
| `jev off` | stop routing, nothing leaves your machine |
| `jev status` | counts per bucket, what Jev has cost you, average delay |
| `jev preset <name>` | switch routing tables, see below |
| `jev test` | run ten sample messages through the real Jev and print a table |
| `jev reset` | zero the counters and cost |

`jev test` is the fastest way to see whether this is working before you trust it with real messages.

---

## The presets

A preset is a **map** telling the router where each bucket should go. Each one assumes a particular model is running your main session. Getting these out of step makes things worse, not better, so read this bit.

### `strong-base` (the default)

Your main session runs a strong model. Grunt work goes down to cheaper ones.

```
tiny      -> your main model, inline
bulk      -> Haiku sub-agent
standard  -> Sonnet sub-agent
hard      -> your main model, inline
```

Use with `/model opus`. Safest configuration. Nothing hard ever lands on a weak model, and the only thing you save is grunt work, which is the money worth saving without risk.

### `sonnet-base`

Your main session runs Sonnet. Route down to Haiku, up to Opus.

```
tiny      -> Sonnet, inline
bulk      -> Haiku sub-agent
standard  -> Sonnet, inline
hard      -> Opus sub-agent
```

Use with `/model sonnet`. Bigger saving, because your main session is cheaper on every single turn. The cost is quality: Sonnet is now the one holding your conversation and writing the briefs for sub-agents.

### `cheap-base`

Your main session runs Haiku. Everything of substance escalates upward.

```
tiny      -> Haiku, inline
bulk      -> Haiku, inline
standard  -> Sonnet sub-agent
hard      -> Opus sub-agent
```

Use with `/model haiku`. Cheapest on paper. **I do not recommend it**, and the reason is in the limits section below.

### The mismatch trap

**Changing the preset does not change your model, and changing your model does not change the preset.** You must do both, and half the change is worse than neither.

Concrete example. If you are running Opus and you switch to `sonnet-base`, the `hard` row now sends hard work to an Opus sub-agent. So Opus pays a full sub-agent startup cost to hand work to Opus, and the sub-agent knows less about your conversation than your main session does. You pay extra for a worse answer.

`jev status` prints the model each preset expects. Check it after every change.

---

## What it costs

Jev charges per input token and does not charge for output. At the time of writing that is **$0.042 per million input tokens**.

Measured on real messages, classification runs about 700 tokens each:

| messages | Jev cost |
|---|---|
| 1,000 | $0.03 |
| 10,000 | $0.30 |
| 100,000 | $3.02 |

Delay added is roughly 250 to 350 milliseconds per message. The router gives up at 1,500 milliseconds and lets your message through unrouted, so that is the worst you can ever wait. Change it with `timeout_ms` in `~/.claude/jev-router/config.json`.

The cost of Jev is not the interesting number. The interesting number is whether the routing saves you more on Claude than it spends, and only your own `jev status` counts can tell you that.

---

## The honest limits

This section exists because I ran into all of these while building it, and you would run into them too.

### Jev grades the message, not the work behind it

Jev sees the words you typed. It cannot see what those words will set in motion.

Type "yes do that" right after your model proposed a large refactor and Jev will call it `tiny` with high confidence, because as a piece of text it obviously is. Whether "that" means shortening a paragraph or building a service is invisible to it.

This fails in the safe direction. A wrong `tiny` keeps the work on your main model, which means you lose a saving rather than an answer. The dangerous direction would be hard work landing on Haiku, and in practice that has not happened, because genuinely hard messages read as hard.

### Confidence swings on identical messages

The exact same message, sent twice in one session, scored 0.94 the first time and 0.58 the second. Nothing about the words changed. What changed is the conversation context handed to Jev alongside it.

The router guards against this with `min_confidence` (0.55 by default). Below that threshold it refuses to delegate and keeps the work on your main model, because keeping it is always the safe choice. Raise the threshold if you want it more cautious.

### Delegation only pays when the answer comes back short

This is the one that cost me the most time.

A sub-agent's reply has to travel back through a narrow handoff. It works beautifully when the answer is a **receipt**: a verdict, a count, a list of files it changed, a path to something it wrote. It works badly when the answer **is** the payload.

I asked a Haiku sub-agent to build a 123-row table. It spent 55,000 tokens and 28 seconds and handed back a single line. The table never made it home. The fix was to have it write the table to a file and return the path.

So: `bulk` work whose output is large is a poor fit for this router even when Jev correctly calls it `bulk`. Jev was right about the job. The job was still wrong for delegation.

### A cheap model is cheap for a reason

On that same folder-counting job, Haiku got **122 of 123 rows right**. The one it missed:

| folder | Haiku said | truth |
|---|---|---|
| Inbox | 197 | 198 |

Off by one. For counting notes, that does not matter. For anything where the number has to be right, it does. This is the actual price of routing to a cheap model, stated plainly instead of glossed over.

### Why `cheap-base` is a trap

Putting Haiku in your main session looks like the biggest saving available, and arithmetically it is. The problem is that your main session is the **dispatcher**. It reads the routing decision, writes the brief for the sub-agent, and interprets the answer that comes back.

Escalating **down** works: a strong model writes a sharp brief for a cheap worker. Escalating **up** works badly: a cheap model writes a vague brief for a strong worker, and you get excellent work on a poorly stated question. You also lose thread quality, because the cheap model is the one remembering your conversation.

`sonnet-base` is the compromise I would actually run.

---

## When not to turn this on

- **Anything confidential.** Your message text goes to a third party. See below.
- **Short sessions.** The router pays off over volume. For a ten-message session it is noise.
- **When most of your work is hard.** If `jev status` shows everything landing in `tiny` and `hard`, the router is spending money and saving none. Turn it off.
- **When you need every answer to be exactly right.** A cheap model doing bulk work will occasionally be off by one.

---

## Privacy

**While the router is on, the text of every message you type is sent to the TypeSafe API before Claude sees it.** Not your files, not your conversation history, just your message plus up to 1,200 characters of the assistant's previous reply for context.

Turn it off for anything you would not paste into a third party service:

```bash
jev off
```

Off means off. The hook checks the switch first and exits before doing anything else.

Two more things worth knowing:

`~/.claude/jev-router/state.json` keeps the first 90 characters of your last 200 messages, so `jev status` can show you what it routed. That file is in `.gitignore` and must never be committed. Delete it any time with `jev reset`.

Background events are filtered out. Task notifications, slash command output, and shell commands run with `!` are recognised as machinery rather than you talking, and are never sent to Jev. They cost you nothing.

---

## How it works under the hood

1. You submit a message. Claude Code fires its `UserPromptSubmit` hook, which runs `route.py`.
2. `route.py` checks the on/off switch. If off, it exits immediately and silently.
3. It checks whether this is really you talking, or a background system event. System events exit here.
4. It strips Claude Code's own wrapper tags so Jev grades your words rather than markup.
5. It reads the assistant's last reply from the session transcript, for context on short follow-ups.
6. It sends one [Choice](https://docs.typesafe.ai/primitives/choice.md) question to Jev with the four buckets and a rubric for each.
7. Jev returns the winning bucket, the full probability distribution, and a confidence figure.
8. If confidence is below the threshold, the router keeps the work on your main model.
9. Otherwise it injects a short instruction into Claude's context telling it to answer inline or spawn a sub-agent on a specific model.
10. Counters and cost are written to `state.json`.

**Every failure path exits 0 and prints nothing.** No key, bad key, network down, Jev slow, malformed input, rate limited: in all of these your message goes through exactly as if the router were not installed. It is designed so that the worst case is that it does nothing.

### Configuration

`~/.claude/jev-router/config.json`:

| key | default | meaning |
|---|---|---|
| `enabled` | `false` | the on/off switch, set by `jev on` and `jev off` |
| `model` | `jev-latest` | which Jev version to call |
| `timeout_ms` | `1500` | give up after this long and let the message through |
| `min_confidence` | `0.55` | below this, never delegate |
| `max_message_chars` | `6000` | truncate long messages before sending to Jev |
| `context_chars` | `1200` | how much of the previous reply to include |
| `log_keep` | `200` | how many routing decisions to remember |
| `routes` | see presets | the bucket to model map |

You can edit `routes` by hand if none of the presets suit you. `mode` is either `inline` or `subagent`, and `model` is the sub-agent's model or `null`.

---

## Uninstall

```bash
./uninstall.sh
```

Same deal as the installer: it shows you what it will remove and waits for a `y`. It takes out the hook entry, the install directory, and the `jev` command, backs up your settings file first, and leaves your other hooks alone. It does not delete your API key.

---

## Credits

This router was inspired by [Jev will 10x your Claude Code](https://youtu.be/tTnUcSj-QPA) by Jay E at RoboNuggets. Jev was already on my radar. That video is what turned it into something I actually built.

Classification by [Jev](https://typesafe.ai), TypeSafe's System One model. Built with [Claude Code](https://claude.com/claude-code).

By [Michael Henry](https://digitaljavelina.com).

MIT licensed. See [LICENSE](LICENSE).
