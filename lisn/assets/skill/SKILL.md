---
name: lisn
description: Read text, files, URLs or your own answers aloud to the user with lisn, a local text-to-speech reader with sentence and word highlighting. Use when the user asks to read something aloud, listen to a document, hear your answer, narrate, speak, pause/resume/stop/skip playback, change the voice or speed, or export an audiobook (mp3/m4b).
---

# lisn — read aloud

lisn is installed on this machine as the `lisn` command and (usually) as an MCP server named
`lisn`. Audio plays on the user's speakers. The user listens *and* reads along, so prefer
reading the exact text rather than a summary unless asked for a summary.

## Prefer the MCP tools when they are available

| Intent | Tool |
|---|---|
| Read text you just wrote, or any text | `read_aloud(text=...)` |
| Read a local file (pdf, docx, epub, md, txt, html) | `read_aloud(path=...)` |
| Read a web page or Google Doc | `read_aloud(url=...)` |
| Pause / resume / stop | `pause()` / `resume()` / `stop()` |
| Skip forward or back | `skip(sentences=3)` / `skip(sentences=-1)` |
| Faster / slower (0.5–3.0) | `set_speed(speed=1.3)` |
| Where are we? | `status()` |
| Save an audiobook | `export_audio(out_path="~/x.m4b", path=...)` |

"Read your last answer to me" means: call `read_aloud(text=<the full text of your previous
answer, as plain prose without markdown tables or code fences>)`. Convert bullet points to
sentences; drop code blocks or say "code block omitted".

`read_aloud` returns immediately and playback continues in the background; do not wait for
it to finish. Starting a new `read_aloud` replaces the current one. The first call after
startup can take a few seconds while the voice model loads.

## Fallback: the command line (no MCP)

Run these with the shell tool. `--no-tui` is required inside an agent (no interactive terminal).

```bash
lisn read <file-or-url> --no-tui          # reads aloud, prints progress; resumes where the user left off
lisn read --clipboard --no-tui            # whatever the user copied
printf '%s' "<text>" | lisn read - --no-tui
lisn export <file-or-url> -o out.m4b      # audiobook with chapters (.mp3 / .wav also work)
lisn voices                               # list voices (Kokoro default af_heart; Hindi: hf_alpha)
lisn config set voice am_michael speed=1.2
```

`lisn read` blocks until playback ends; run it in the background when you need to keep working.
Flags: `--voice`, `--speed`, `--engine kokoro|piper|edge`, `--from 40%`, `--chapter N`.

## Voices

Kokoro voices (default engine): `af_heart` (warm female, default), `af_bella`, `am_michael`,
`am_fenrir`, `bf_emma`, `bm_george` (British narrator), `hf_alpha` / `hm_omega` (Hindi).
Pass them as `voice=` to `read_aloud` or `--voice` on the CLI.

## Do not

- Do not paste huge documents into `read_aloud(text=...)`; pass `path=` or `url=` instead.
- Do not read secrets, tokens or passwords aloud.
- Do not claim playback finished unless `status()` says `finished`.
