"""Command line interface: `lisn read|sample|voices|config|history|bookmarks|cache`."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from lisn import __version__
from lisn.config import HIGHLIGHT_MODES, Config, load_config, save_config, set_value
from lisn.errors import LisnError
from lisn.model import Document
from lisn.tts.base import MAX_SPEED, MIN_SPEED, TTSEngine
from lisn.tts.registry import ENGINE_NAMES

app = typer.Typer(
    name="lisn",
    help="Read documents aloud, word for word, with the current sentence and word highlighted.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Show or change saved defaults (voice, speed, engine, ...).")
app.add_typer(config_app, name="config")
console = Console()
err_console = Console(stderr=True)

_PERCENT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%?\s*$")


def main() -> None:
    try:
        app()
    except LisnError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise SystemExit(1) from exc


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show the version and exit.")] = False,
) -> None:
    if version:
        console.print(f"lisn {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def read(
    source: Annotated[str, typer.Argument(help="File path, URL, Google Doc URL, or '-' for stdin.")] = "",
    clipboard: Annotated[bool, typer.Option("--clipboard", help="Read the clipboard contents.")] = False,
    engine: Annotated[str | None, typer.Option(help=f"TTS engine: {', '.join(ENGINE_NAMES)}.")] = None,
    voice: Annotated[str | None, typer.Option(help="Voice id (see `lisn voices`).")] = None,
    speed: Annotated[float | None, typer.Option(min=MIN_SPEED, max=MAX_SPEED, help="Speech rate.")] = None,
    from_: Annotated[str | None, typer.Option("--from", help="Start at a percentage, e.g. 40%.")] = None,
    chapter: Annotated[int | None, typer.Option(help="Start at chapter N (1-based).")] = None,
    highlight: Annotated[str | None, typer.Option(help="word or sentence.")] = None,
    no_resume: Annotated[
        bool, typer.Option("--no-resume", help="Start from the top, ignoring the saved position.")
    ] = False,
    no_tui: Annotated[bool, typer.Option("--no-tui", help="Headless playback in the terminal.")] = False,
    no_audio: Annotated[bool, typer.Option("--no-audio", help="Simulate playback without a sound device.")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Do not read or write the audio cache.")] = False,
    read_code: Annotated[bool, typer.Option("--read-code", help="Read code blocks instead of skipping them.")] = False,
) -> None:
    """Open a document and start reading it aloud (resumes where you left off)."""
    from lisn.extract import extract, extract_clipboard
    from lisn.player.state import StateStore, document_key

    if highlight is not None and highlight not in HIGHLIGHT_MODES:
        raise typer.BadParameter(f"--highlight must be one of {HIGHLIGHT_MODES}")
    config = load_config().with_overrides(
        engine=engine, voice=voice, speed=speed, highlight=highlight, read_code=read_code or None
    )
    tts_engine = _warm_engine(config)  # load the model while we extract the document
    if clipboard:
        extracted = extract_clipboard(config.read_code)
    elif source:
        extracted = extract(source, config.read_code)
    else:
        raise typer.BadParameter("Give a source, '-' for stdin, or --clipboard.")
    document = _build(extracted)
    store = StateStore()
    key = document_key(document)
    start_index = _start_index(document, from_, chapter)
    if start_index is None:
        start_index = 0 if no_resume else store.resume_index(key, document)
        if start_index:
            err_console.print(
                f"[dim]Resuming at sentence {start_index + 1} of {len(document)} (use --no-resume to restart).[/dim]"
            )
    runner = _play_headless if no_tui else _play_tui
    runner(document, config, start_index, engine=tts_engine, store=store, key=key, no_audio=no_audio, no_cache=no_cache)


@app.command()
def sample(
    text: Annotated[str, typer.Argument(help="Text to speak.")] = "Hello! This is lisn, reading to you.",
    voice: Annotated[str | None, typer.Option(help="Voice id.")] = None,
    engine: Annotated[str | None, typer.Option(help="TTS engine.")] = None,
    speed: Annotated[float | None, typer.Option(min=MIN_SPEED, max=MAX_SPEED)] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write a WAV file instead of playing.")] = None,
    no_audio: Annotated[bool, typer.Option("--no-audio")] = False,
) -> None:
    """Quickly preview a voice."""
    from lisn.text.pipeline import document_from_text

    config = load_config().with_overrides(engine=engine, voice=voice, speed=speed)
    document = document_from_text(text, title="sample", source="sample")
    if out is not None:
        _write_wav(document, config, out)
        console.print(f"Wrote {out}")
        return
    _play_headless(document, config, 0, no_audio=no_audio, no_cache=False)


@app.command()
def voices(
    engine: Annotated[str | None, typer.Option(help="Only list voices for this engine.")] = None,
) -> None:
    """List available voices per engine, with a sample command for each."""
    from lisn.errors import EngineUnavailableError
    from lisn.tts.registry import get_engine

    names = (engine,) if engine else ENGINE_NAMES
    for name in names:
        try:
            voices_list = get_engine(name).voices()
        except EngineUnavailableError as exc:
            console.print(f"[yellow]{name}[/yellow]: not available ({exc})")
            continue
        table = Table(title=f"{name} voices", show_lines=False)
        table.add_column("voice", style="bold")
        table.add_column("lang")
        table.add_column("description")
        table.add_column("try it", style="dim")
        for voice in voices_list:
            table.add_row(
                voice.id, voice.language, voice.description, f'lisn sample --engine {name} --voice {voice.id} "Hello"'
            )
        console.print(table)


@app.command()
def history(
    limit: Annotated[int, typer.Option(help="How many items to show.")] = 20,
    forget: Annotated[str | None, typer.Option(help="Forget the saved position for this source.")] = None,
) -> None:
    """Recently read items with their progress."""
    from lisn.player.state import StateStore

    store = StateStore()
    if forget is not None:
        matches = [p for p in store.history(limit=500) if p.source == forget or p.key == forget]
        if not matches:
            raise LisnError(f"No history entry matches '{forget}'.")
        for position in matches:
            store.forget(position.key)
        console.print(f"Forgot {len(matches)} item(s).")
        return
    items = store.history(limit=limit)
    if not items:
        console.print("No history yet. Read something with `lisn read`.")
        return
    table = Table(title="history")
    table.add_column("when", style="dim")
    table.add_column("progress", justify="right")
    table.add_column("title", style="bold")
    table.add_column("source")
    for item in items:
        table.add_row(_ago(item.updated_at), f"{item.percent:5.1f}%", item.title, item.source)
    console.print(table)


@app.command()
def bookmarks(
    source: Annotated[str | None, typer.Argument(help="Only bookmarks for this source (path or URL).")] = None,
    delete: Annotated[int | None, typer.Option(help="Delete the bookmark with this id.")] = None,
) -> None:
    """List (or delete) bookmarks saved with the `b` key."""
    from lisn.player.state import StateStore

    store = StateStore()
    if delete is not None:
        store.delete_bookmark(delete)
        console.print(f"Deleted bookmark {delete}.")
        return
    key = None
    if source is not None:
        matches = [p for p in store.history(limit=500) if p.source == source]
        if not matches:
            raise LisnError(f"'{source}' is not in the history.")
        key = matches[0].key
    items = store.bookmarks(key)
    if not items:
        console.print("No bookmarks yet. Press `b` while reading.")
        return
    titles = {p.key: p.title for p in store.history(limit=500)}
    table = Table(title="bookmarks")
    table.add_column("id", justify="right")
    table.add_column("when", style="dim")
    table.add_column("title", style="bold")
    table.add_column("sentence", justify="right")
    table.add_column("excerpt")
    for item in items:
        table.add_row(
            str(item.id),
            _ago(item.created_at),
            titles.get(item.doc_key, "?"),
            str(item.sentence_index + 1),
            item.excerpt,
        )
    console.print(table)


@config_app.command("show")
def config_show() -> None:
    """Print the current configuration."""
    from dataclasses import fields

    from lisn.paths import config_file

    config = load_config()
    table = Table(title=f"config ({config_file()})")
    table.add_column("key", style="bold")
    table.add_column("value")
    for field in fields(Config):
        value = getattr(config, field.name)
        table.add_row(field.name, "••••" if field.name == "server_token" and value else str(value))
    console.print(table)


@config_app.command("set")
def config_set(
    assignments: Annotated[list[str], typer.Argument(help="key=value pairs, or 'key value'.")],
) -> None:
    """Set one or more values: lisn config set voice af_heart speed=1.3"""
    config = load_config()
    for key, value in _parse_assignments(assignments):
        config = set_value(config, key, value)
    path = save_config(config)
    console.print(f"Saved to {path}")


@config_app.command("get")
def config_get(key: str) -> None:
    """Print a single config value."""
    config = load_config()
    if not hasattr(config, key):
        raise LisnError(f"Unknown config key '{key}'.")
    console.print(str(getattr(config, key)))


@config_app.command("path")
def config_path() -> None:
    """Print where the config file lives."""
    from lisn.paths import config_file

    console.print(str(config_file()))


@app.command()
def cache(
    clear: Annotated[bool, typer.Option("--clear", help="Delete all cached audio.")] = False,
) -> None:
    """Show (or clear) the on-disk audio cache."""
    from lisn.tts.cache import AudioCache

    store = AudioCache()
    if clear:
        console.print(f"Removed {store.clear()} cached clips.")
        return
    console.print(f"{store.directory}: {store.size_bytes() / 1_048_576:.1f} MB")


@app.command()
def export(
    source: Annotated[str, typer.Argument(help="File path, URL, Google Doc URL, or '-' for stdin.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output file: .mp3, .m4b (chapters) or .wav.")],
    engine: Annotated[str | None, typer.Option(help="TTS engine.")] = None,
    voice: Annotated[str | None, typer.Option(help="Voice id.")] = None,
    speed: Annotated[float | None, typer.Option(min=MIN_SPEED, max=MAX_SPEED)] = None,
    bitrate: Annotated[str, typer.Option(help="Audio bitrate for mp3/m4b.")] = "96k",
    read_code: Annotated[bool, typer.Option("--read-code")] = False,
) -> None:
    """Export a document to an audio file (M4B keeps chapters)."""
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    from lisn.export import export_document, render_document
    from lisn.extract import extract
    from lisn.tts.cache import AudioCache
    from lisn.tts.registry import get_engine

    config = load_config().with_overrides(engine=engine, voice=voice, speed=speed, read_code=read_code or None)
    document = _build(extract(source, config.read_code))
    tts_engine = get_engine(config.engine)
    with Progress(
        TextColumn("synthesizing"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=err_console,
    ) as bar:
        task = bar.add_task("render", total=len(document))
        rendered = render_document(
            document,
            tts_engine,
            config.voice,
            config.speed,
            AudioCache(),
            progress=lambda done, total: bar.update(task, completed=done),
        )
    path = export_document(rendered, out, title=document.title, bitrate=bitrate)
    minutes = rendered.duration / 60
    console.print(f"Wrote {path} ({minutes:.1f} min, {len(rendered.chapters)} chapter(s))")


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1.")] = 7391,
    show_token: Annotated[bool, typer.Option("--show-token", help="Print the auth token and exit.")] = False,
    rotate_token: Annotated[bool, typer.Option("--rotate-token", help="Generate a new auth token and exit.")] = False,
) -> None:
    """Run the local API used by the browser extension (and `lisn mcp`)."""
    from lisn.server.auth import ensure_token
    from lisn.server.auth import rotate_token as _rotate

    config = load_config()
    if rotate_token:
        _, token = _rotate(config)
        console.print(f"New token: {token}")
        return
    config, token = ensure_token(config)
    if show_token:
        console.print(token)
        return
    from lisn.server.run import serve as _serve

    err_console.print(f"[dim]lisn server on http://127.0.0.1:{port}  token: {token}[/dim]")
    err_console.print("[dim]Paste the token into the extension popup. Ctrl-C to stop.[/dim]")
    try:
        _serve(config, port=port)
    except KeyboardInterrupt:
        pass


gdoc_app = typer.Typer(help="Google sign-in for private Google Docs.")
app.add_typer(gdoc_app, name="gdoc")


@gdoc_app.command("login")
def gdoc_login(
    client_secret: Annotated[
        Path | None, typer.Argument(help="OAuth 'Desktop app' client JSON from Google Cloud.")
    ] = None,
) -> None:
    """Sign in to Google (read-only Drive scope) so private docs can be read."""
    from lisn.extract.gdoc_oauth import login

    path = login(client_secret)
    console.print(f"Signed in. Token cached at {path}")


@gdoc_app.command("logout")
def gdoc_logout() -> None:
    """Forget the cached Google token."""
    from lisn.extract.gdoc_oauth import logout

    console.print("Signed out." if logout() else "You were not signed in.")


@app.command()
def setup(
    claude: Annotated[bool, typer.Option("--claude", help="Claude Code")] = False,
    codex: Annotated[bool, typer.Option("--codex", help="Codex CLI")] = False,
    gemini: Annotated[bool, typer.Option("--gemini", help="Gemini CLI")] = False,
    all_clis: Annotated[bool, typer.Option("--all", help="All of the above (default when none is given).")] = False,
    no_mcp: Annotated[
        bool, typer.Option("--no-mcp", help="Install the skill only; do not register the MCP server.")
    ] = False,
    uninstall: Annotated[bool, typer.Option("--uninstall", help="Remove the skill and the MCP registration.")] = False,
) -> None:
    """Install the 'lisn' agent skill (and MCP server) into Claude Code, Codex CLI and Gemini CLI."""
    from lisn.setup_cli import install_skill, known_clis, register_mcp, remove_skill, unregister_mcp

    wanted = {"claude": claude, "codex": codex, "gemini": gemini}
    if all_clis or not any(wanted.values()):
        wanted = dict.fromkeys(wanted, True)
    for cli_def in known_clis():
        if not wanted[cli_def.name]:
            continue
        if uninstall:
            removed = remove_skill(cli_def)
            console.print(f"{cli_def.name}: skill {'removed' if removed else 'was not installed'}")
            if not no_mcp:
                console.print(unregister_mcp(cli_def))
            continue
        path = install_skill(cli_def)
        console.print(f"{cli_def.name}: skill installed at {path}")
        if not no_mcp:
            console.print(register_mcp(cli_def))
    if not uninstall:
        console.print("Restart the CLIs, then ask e.g. 'read your last answer to me' or 'read notes.pdf aloud'.")


@app.command()
def mcp() -> None:
    """Run the MCP server (stdio) so coding agents can ask lisn to read aloud."""
    from lisn.mcp.server import run_mcp

    run_mcp(load_config())


# ---- helpers ------------------------------------------------------------------------


def _build(extracted) -> Document:  # type: ignore[no-untyped-def]
    from lisn.text.pipeline import build_document

    try:
        return build_document(extracted)
    except ValueError as exc:
        raise LisnError(str(exc)) from exc


def _start_index(document: Document, from_: str | None, chapter: int | None) -> int | None:
    """Explicit start from --chapter / --from, or None to let resume decide."""
    if chapter is not None:
        if not document.chapters:
            raise LisnError("This document has no chapters or headings.")
        if not (1 <= chapter <= len(document.chapters)):
            raise LisnError(f"--chapter must be between 1 and {len(document.chapters)}.")
        return document.chapters[chapter - 1].start_sentence
    if from_ is not None:
        match = _PERCENT_RE.match(from_)
        if not match:
            raise LisnError("--from expects a percentage like 40 or 40%.")
        percent = max(0.0, min(100.0, float(match.group(1))))
        target = percent / 100.0 * document.total_chars
        seen = 0
        for sentence in document.sentences:
            if seen + len(sentence.text) >= target:
                return sentence.index
            seen += len(sentence.text)
        return len(document.sentences) - 1
    return None


def _parse_assignments(items: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending_key: str | None = None
    for item in items:
        if pending_key is not None:
            pairs.append((pending_key, item))
            pending_key = None
        elif "=" in item:
            key, value = item.split("=", 1)
            pairs.append((key.strip(), value.strip()))
        else:
            pending_key = item
    if pending_key is not None:
        raise LisnError(f"Missing value for '{pending_key}'. Use key=value.")
    if not pairs:
        raise LisnError("Nothing to set. Example: lisn config set voice af_heart")
    return pairs


def _ago(timestamp: float) -> str:
    delta = max(0, int(time.time() - timestamp))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} h ago"
    return f"{delta // 86400} d ago"


def _warm_engine(config: Config) -> TTSEngine:
    """Create the engine and start loading its model on a background thread."""
    import threading

    from lisn.tts.registry import get_engine

    engine = get_engine(config.engine)

    def warm() -> None:
        try:
            engine.warm_up()
        except LisnError:
            pass  # the real synthesize call will report the error with context

    threading.Thread(target=warm, name="lisn-warmup", daemon=True).start()
    return engine


class _Session:
    """Everything a front end (TUI or headless) needs: player, persistence hooks, voices."""

    def __init__(self, document: Document, config: Config, start_index: int, engine, store, key, no_audio, no_cache):  # type: ignore[no-untyped-def]
        from lisn.player.audio import DeviceOutput, SilentOutput
        from lisn.player.engine import Player
        from lisn.tts.cache import AudioCache
        from lisn.tts.registry import get_engine

        self.document, self.config, self.store, self.key = document, config, store, key
        self.engine = engine or get_engine(config.engine)
        self.listeners: list = []
        output = SilentOutput(volume=config.volume) if no_audio else DeviceOutput(volume=config.volume)
        self.player = Player(
            document,
            self.engine,
            config,
            output=output,
            cache=None if no_cache else AudioCache(),
            listener=self._on_event,
            start_index=start_index,
        )
        known = self.engine.voices()
        self.voice_ids = tuple(v.id for v in known if v.id[0] == config.voice[0]) if known else ()

    def _on_event(self, event) -> None:  # type: ignore[no-untyped-def]
        for listener in self.listeners:
            listener(event)
        if self.store is not None and event.kind in ("sentence", "finished"):
            self.save()

    def save(self) -> None:
        if self.store is not None:
            self.store.save_position(self.key, self.document, self.player.state.index, self.player.percent_complete())

    def bookmark(self, index: int) -> str:
        mark = self.store.add_bookmark(self.key, self.document, index)
        return f"bookmarked sentence {mark.sentence_index + 1}"

    def finish(self) -> None:
        self.save()
        if self.player.state.error:
            raise LisnError(self.player.state.error)


def _play_headless(
    document: Document,
    config: Config,
    start_index: int,
    *,
    engine: TTSEngine | None = None,
    store=None,  # type: ignore[no-untyped-def]
    key: str = "",
    no_audio: bool,
    no_cache: bool,
) -> None:
    from lisn.player.headless import HeadlessController, HeadlessRenderer, run_headless

    session = _Session(document, config, start_index, engine, store, key, no_audio, no_cache)
    renderer = HeadlessRenderer(document, console=console, highlight=config.highlight)
    session.listeners.append(renderer.on_event)
    on_bookmark = session.bookmark if store is not None else None
    controller = HeadlessController(session.player, renderer, on_bookmark=on_bookmark, voices=session.voice_ids)
    run_headless(session.player, renderer, controller)
    session.finish()


def _play_tui(
    document: Document,
    config: Config,
    start_index: int,
    *,
    engine: TTSEngine | None = None,
    store=None,  # type: ignore[no-untyped-def]
    key: str = "",
    no_audio: bool,
    no_cache: bool,
) -> None:
    from lisn.tui.app import LisnApp

    session = _Session(document, config, start_index, engine, store, key, no_audio, no_cache)
    app = LisnApp(
        document,
        session.player,
        highlight=config.highlight,
        autoscroll=config.autoscroll,
        voices=session.voice_ids,
        on_bookmark=session.bookmark if store is not None else None,
    )
    session.listeners.append(app.player_event)
    app.run()
    session.finish()


def _write_wav(document: Document, config: Config, out: Path) -> None:
    import numpy as np
    import soundfile as sf

    from lisn.tts.cache import AudioCache
    from lisn.tts.registry import get_engine

    engine = get_engine(config.engine)
    store = AudioCache()
    clips = []
    sample_rate = 0
    for sentence in document.sentences:
        cache_key = AudioCache.key(engine.name, config.voice, config.speed, sentence.speech_text)
        audio = store.get(cache_key) or engine.synthesize(sentence.speech_text, config.voice, config.speed)
        store.put(cache_key, audio)
        clips.append(audio.samples)
        clips.append(np.zeros(int(audio.sample_rate * 0.25), dtype=np.float32))
        sample_rate = audio.sample_rate
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), np.concatenate(clips), sample_rate)


if __name__ == "__main__":
    main()
