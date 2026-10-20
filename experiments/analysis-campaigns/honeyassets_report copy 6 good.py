#!/usr/bin/env python3
"""
honeypot_report.py
==================

Turn the artefacts of a single Caldera adversary-emulation run against a
honey-asset-instrumented open5gs pod into a set of analysis plots plus two
machine-readable summary files (a timeline CSV and a metrics JSON).

Inputs (all passed by path, see the CONFIG section / CLI):
  1. event-logs.json          Caldera operation event log (list of commands).
  2. honey-asset-manifest.csv  ENV / binary / history / process honey assets.
  3. honeyfiles.csv            Honeyfile manifest (decoy files on disk).
  4. discovery.log             Attacker-POV output dump of the whole operation.
  5. tetragon-udr.log          Tetragon runtime events (EXEC / READ / WRITE).

Outputs (written into the output directory):
  - attack_timeline.csv                        (table of the attack)
  - phase_metrics.json                         (first command per tactic)
  - 01_phases_caldera_vs_tetragon.png
  - 02_overview_caldera_tetragon_honey.png
  - 03_honey_assets_vs_normal_files.png
  - 04_honey_interaction_timeline.png

Design notes
------------
Every plot has its own ``plot_*`` function so it can be produced on its own.
Shared work (parsing, matching Caldera<->Tetragon, honey-asset detection) lives
in small reusable helpers and in the ``AnalysisData`` container that is built
once in ``load_analysis_data`` and handed to each plot function.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless / file output
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import AutoMinorLocator

# --------------------------------------------------------------------------- #
# Configuration / constants
# --------------------------------------------------------------------------- #

# Number of genuine, legitimate files the honey assets are compared against.
NORMAL_FILE_COUNT = 77

# One stable colour per MITRE ATT&CK tactic so every plot is consistent.
TACTIC_COLORS = {
    "discovery": "#d62728",          # red
    "collection": "#ff7f0e",         # orange
    "credential-access": "#9467bd",  # purple
    "execution": "#2ca02c",          # green
    "exfiltration": "#1f77b4",       # blue
}
DEFAULT_TACTIC_COLOR = "#7f7f7f"     # grey for anything unexpected

# Tactics we want the "time of first command" metric for, and the JSON key used.
FIRST_COMMAND_TACTICS = {
    "discovery": "first_discovery_cmd",
    "collection": "first_collection_cmd",
    "credential-access": "first_credential_access_cmd",
    "execution": "first_execution_cmd",
    "exfiltration": "first_exfiltration_cmd",
}

ALERT_NAMES = [
    "Detected_at_least_3_Honey_FILE_Interactions",
    "Detected_at_least_3_Honey_ENV_Interactions",
    "Detected_at_least_1_Honey_BINARY_Interactions",
    "Detected_at_least_1_Honey_BINARY_Execution",
    "Detected_at_least_7_Suspicious_BINARY_Executions",
]

# How similar a Tetragon `/bin/sh -c ...` command must be to a Caldera command
# before we accept it as "the same command seen by Tetragon".
MATCH_THRESHOLD = 0.55

# Tolerance (seconds) for clock skew between the Caldera server and the node
# running Tetragon when deciding whether a Tetragon event may belong to a
# command. Kept small: a Tetragon event is otherwise never before delegation.
CLOCK_SKEW_GRACE_S = 2.0


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #

@dataclass
class CalderaEvent:
    """One command as reported by Caldera."""
    delegated: datetime
    finished: datetime
    tactic: str
    ability_name: str
    command: str
    status: int

    @property
    def color(self) -> str:
        return TACTIC_COLORS.get(self.tactic, DEFAULT_TACTIC_COLOR)


@dataclass
class HoneyHit:
    """One Tetragon event that touched a honey asset."""
    ts: datetime
    asset_type: str          # env / binary / history / process / file
    target: str              # the path or name that was touched
    is_execution: bool       # True -> honey *binary* was executed


@dataclass
class AnalysisData:
    """Everything the plot functions need, parsed exactly once."""
    caldera: list[CalderaEvent]
    # For each Caldera event (same index) the matched Tetragon timestamp, or None.
    tetragon_match: list[datetime | None]
    # For each Caldera event (same index) the matched raw Tetragon line, or None.
    tetragon_match_line: list[str | None]
    honey_hits: list[HoneyHit]
    # Campaign start: all timestamps are normalised relative to this (-> 00:00:00).
    t0: datetime | None = None
    # Per Caldera command (same index): human-readable honey-effect summary.
    command_honey_effects: list[str] = field(default_factory=list)
    honey_asset_counts: dict[str, int] = field(default_factory=dict)
    honey_asset_status: dict[str, dict[str, int]] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp (with optional 'Z' / nanoseconds) to UTC."""
    ts = ts.strip()
    # Tetragon uses nanosecond precision; Python only handles microseconds.
    m = re.match(r"(.*\.\d{6})\d*Z?$", ts)
    if m:
        ts = m.group(1)
        dt = datetime.fromisoformat(ts)
        return dt.replace(tzinfo=timezone.utc)
    ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Fixed reference used when plotting elapsed time: the campaign start (t0) is
# mapped onto this midnight epoch so the x-axis / timestamps read from 00:00:00.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _shift(dt: datetime, t0: datetime) -> datetime:
    """Shift an absolute datetime to elapsed time since t0 (t0 -> 00:00:00)."""
    return EPOCH + (dt - t0)


def _elapsed_hms(dt: datetime, t0: datetime) -> str:
    """Render elapsed time since t0 as 'HH:MM:SS' (campaign start = 00:00:00)."""
    secs = (dt - t0).total_seconds()
    sign = "-" if secs < 0 else ""
    secs = abs(int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


def _normalise_cmd(cmd: str) -> str:
    """Collapse a shell command to a comparable fingerprint."""
    cmd = cmd.strip()
    # Drop surrounding -c and quotes that Tetragon/Caldera quote differently.
    cmd = re.sub(r"^-c\s+", "", cmd)
    cmd = cmd.replace('"', " ").replace("'", " ")
    cmd = re.sub(r"\s+", " ", cmd)
    return cmd.strip().lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalise_cmd(a), _normalise_cmd(b)).ratio()


def _style_time_axis(ax, times: list[datetime]) -> None:
    """Format the x-axis in minutes with 10-second minor ticks.

    Major ticks / labels are every minute; minor ticks mark every 10 seconds
    so short inter-command gaps are easy to read off the axis.
    """
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    # 7 minor divisions inside each 1-min major step => one tick per ~8.5s;
    # SecondLocator gives us exact 10s ticks instead.
    ax.xaxis.set_minor_locator(mdates.SecondLocator(bysecond=range(0, 60, 10)))
    # Rotate the time labels to vertical so dense ticks never overlap.
    # (Change `labelrotation` here to adjust the angle for every timeline plot.)
    ax.tick_params(axis="x", which="major", length=7, labelrotation=90)
    ax.tick_params(axis="x", which="minor", length=3)
    ax.grid(axis="x", which="major", alpha=0.25)
    ax.grid(axis="x", which="minor", alpha=0.10)
    if times:
        pad = (max(times) - min(times)).total_seconds() * 0.03 or 10
        from datetime import timedelta
        ax.set_xlim(min(times) - timedelta(seconds=pad),
                    max(times) + timedelta(seconds=pad))


def _tactic_legend_handles(tactics: list[str]) -> list[Patch]:
    return [Patch(color=TACTIC_COLORS.get(t, DEFAULT_TACTIC_COLOR),
                  label=t.replace("-", " ").title())
            for t in tactics]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def parse_caldera_events(path: str | Path) -> list[CalderaEvent]:
    """Read the Caldera event log into a sorted list of CalderaEvent."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    events: list[CalderaEvent] = []
    for item in raw:
        events.append(CalderaEvent(
            delegated=_parse_iso(item["delegated_timestamp"]),
            finished=_parse_iso(item["finished_timestamp"]),
            tactic=(item.get("attack_metadata", {}) or {}).get("tactic", "unknown"),
            ability_name=(item.get("ability_metadata", {}) or {}).get("ability_name", ""),
            command=item.get("plaintext_command", item.get("command", "")),
            status=int(item.get("status", 0)),
        ))
    events.sort(key=lambda e: e.delegated)
    return events


# Only the fixed prefix fields are split on '|'; everything after the command
# name is the argument string, which may itself contain '|' (pipes, e.g. tee).
#   EXEC: TS | OP | PID=.. | PPID=.. | /path/comm | args...
#   READ: TS | OP | PID=.. | /path/comm | path
_TETRAGON_RE = re.compile(
    r"^\s*(?P<ts>\S+)\s*\|\s*(?P<op>\w+)\s*\|\s*PID=\d+\s*\|\s*"
    r"(?:PPID=\d+\s*\|\s*)?"
    r"(?P<comm>\S+)\s*\|\s*(?P<args>.*)$"
)


def _read_tetragon(path: str | Path) -> list[tuple[datetime, str, str, str, str]]:
    """Parse the Tetragon log into (ts, op, comm, args, raw_line) tuples.

    The argument field is captured as a whole, so commands containing pipes
    (e.g. ``... | tee -a ...``) are preserved intact instead of being split.
    EXEC lines carry a PPID field, READ/WRITE lines do not; both are handled.
    """
    rows: list[tuple[datetime, str, str, str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            raw = line.rstrip("\n")
            m = _TETRAGON_RE.match(raw)
            if not m:
                continue
            try:
                ts = _parse_iso(m.group("ts"))
            except ValueError:
                continue
            rows.append((ts, m.group("op"), m.group("comm").strip(),
                         m.group("args").strip(), raw))
    return rows


def _tetragon_shell_commands(
    rows: list[tuple[datetime, str, str, str, str]]
) -> list[tuple[datetime, str, str]]:
    """Return (ts, command_text, raw_line) for every top-level ``/bin/sh -c`` EXEC."""
    out = []
    for ts, op, comm, args, raw in rows:
        if op == "EXEC" and comm.endswith("/sh") and args.startswith("-c"):
            out.append((ts, args, raw))
    return out


def match_caldera_to_tetragon(
    caldera: list[CalderaEvent],
    tetragon_rows: list[tuple[datetime, str, str, str, str]],
) -> list[tuple[datetime | None, str | None]]:
    """For each Caldera command find the best-matching Tetragon exec event.

    Matching is by textual similarity of the command (path + arguments), bounded
    to Tetragon events at or after the command was delegated (execution cannot
    precede the order). Each Tetragon line is consumed at most once.

    Returns, per Caldera command, ``(timestamp, raw_line)`` of the matched
    Tetragon event, or ``(None, None)`` when nothing matched.
    """
    shell_cmds = _tetragon_shell_commands(tetragon_rows)
    used: set[int] = set()
    matches: list[tuple[datetime | None, str | None]] = []

    for ev in caldera:
        best_idx, best_score = None, MATCH_THRESHOLD
        for idx, (ts, text, _raw) in enumerate(shell_cmds):
            if idx in used:
                continue
            # A command can only be observed *after* it was issued: never pair a
            # Tetragon event that occurred before the Caldera delegation time.
            # (A small grace absorbs minor clock skew between the two sources.)
            if (ts - ev.delegated).total_seconds() < -CLOCK_SKEW_GRACE_S:
                continue
            score = _similarity(ev.command, text)
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx is not None:
            used.add(best_idx)
            ts, _text, raw = shell_cmds[best_idx]
            matches.append((ts, raw))
        else:
            matches.append((None, None))
    return matches


# --------------------------------------------------------------------------- #
# Honey-asset bookkeeping
# --------------------------------------------------------------------------- #

def load_honey_assets(manifest_path: str | Path, honeyfiles_path: str | Path):
    """Load both honey manifests.

    Returns
    -------
    asset_rows : list[dict]      rows of the honey-asset manifest
    honeyfiles : list[dict]      rows of the honeyfiles manifest
    """
    def _read_csv(path):
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    return _read_csv(manifest_path), _read_csv(honeyfiles_path)


def _honey_lookup(asset_rows, honeyfiles):
    """Build helper structures mapping on-disk identifiers to a honey asset.

    Returns ``(by_path, by_basename, binary_paths, binary_names)`` where
    *by_path* / *by_basename* map an identifier to (asset_type, target) and the
    binary sets hold the honey executables used to flag honey-binary executions.
    """
    by_path: dict[str, tuple[str, str]] = {}
    by_basename: dict[str, tuple[str, str]] = {}
    binary_paths: set[str] = set()
    binary_names: set[str] = set()

    for row in asset_rows:
        atype = row.get("asset_type", "").strip()
        path = row.get("path", "").strip()
        name = row.get("name", "").strip()
        if atype in ("binary", "process"):
            if path:
                binary_paths.add(path)
                by_path[path] = (atype, path)
                by_basename[Path(path).name] = (atype, path)
            if name:
                binary_names.add(name)
        elif atype == "env":
            # ENV assets are flagged by their variable name (e.g. API_TOKEN).
            if name:
                by_basename[name] = ("env", name)
        elif atype == "history":
            continue  # history hints are discovery-only, not file touches

    for row in honeyfiles:
        path = row.get("path", "").strip()
        if path:
            by_path[path] = ("file", path)
            by_basename[Path(path).name] = ("file", path)

    return by_path, by_basename, binary_paths, binary_names


def detect_honey_hits(tetragon_rows, asset_rows, honeyfiles) -> list[HoneyHit]:
    """Scan Tetragon events for any interaction with a honey asset."""
    by_path, by_basename, binary_paths, binary_names = _honey_lookup(
        asset_rows, honeyfiles)

    hits: list[HoneyHit] = []
    for ts, op, comm, args, _raw in tetragon_rows:
        # 1) Execution of a honey *binary* (the executed comm is a honey path).
        if op == "EXEC" and (comm in binary_paths or Path(comm).name in binary_names):
            atype, target = by_path.get(comm, ("binary", comm))
            hits.append(HoneyHit(ts, atype, target, is_execution=True))
            continue

        # 2) READ / WRITE / EXEC whose touched path is a honey file or asset.
        #    For READ/WRITE the touched path is the args field; for EXEC it is comm.
        candidates = [args, comm]
        for cand in candidates:
            cand = cand.strip()
            if not cand:
                continue
            info = by_path.get(cand) or by_basename.get(Path(cand).name)
            if info:
                atype, target = info
                hits.append(HoneyHit(ts, atype, target,
                                     is_execution=(atype in ("binary", "process")
                                                   and op == "EXEC")))
                break
    return hits


def _plural(word: str, n: int) -> str:
    return word if n == 1 else word + "s"


def _format_honey_effects(hits: list[HoneyHit]) -> str:
    """Summarise a set of honey hits as e.g. 'honeyfile: 2 interactions, honeybinary: 1 execution'.

    Assets are counted *distinctly* (by target), so a copy that both reads the
    source honeyfile and writes a same-named staged copy counts once.
    """
    files = {h.target for h in hits if h.asset_type == "file"}
    envs = {h.target for h in hits if h.asset_type == "env"}
    bin_exec = {h.target for h in hits
                if h.asset_type in ("binary", "process") and h.is_execution}
    bin_touch = {h.target for h in hits
                 if h.asset_type in ("binary", "process") and not h.is_execution} - bin_exec

    parts: list[str] = []
    if files:
        parts.append(f"honeyfile: {len(files)} {_plural('interaction', len(files))}")
    if envs:
        parts.append(f"honeyenv: {len(envs)} {_plural('interaction', len(envs))}")
    if bin_exec:
        parts.append(f"honeybinary: {len(bin_exec)} {_plural('execution', len(bin_exec))}")
    if bin_touch:
        parts.append(f"honeybinary: {len(bin_touch)} {_plural('interaction', len(bin_touch))}")
    return ", ".join(parts)


def compute_command_honey_effects(caldera, honey_hits) -> list[str]:
    """Attribute Tetragon honey hits to the Caldera command that caused them.

    The command windows are made to tile the timeline: a hit belongs to the most
    recently delegated command (``[delegated_i, delegated_{i+1})``), which captures
    the honey touch that happens between a command being issued and finishing.
    """
    effects: list[str] = []
    for i, ev in enumerate(caldera):
        start = ev.delegated
        end = caldera[i + 1].delegated if i + 1 < len(caldera) else datetime.max.replace(tzinfo=timezone.utc)
        in_window = [h for h in honey_hits if start <= h.ts < end]
        effects.append(_format_honey_effects(in_window))
    return effects


def compute_asset_breakdown(asset_rows, honeyfiles, honey_hits, discovery_text):
    """Count honey assets per category and classify them.

    Each honey asset is placed into exactly one of three buckets:
      * accessed    -> appeared in a Tetragon honey hit
      * discovered  -> showed up in the attacker discovery.log but not accessed
      * undiscovered-> never seen by the attacker

    Returns (counts, status) where
      counts[category]              = total number of assets in the category
      status[category]              = {'accessed':x, 'discovered':y, 'undiscovered':z}
    """
    accessed_targets = {h.target for h in honey_hits}
    accessed_basenames = {Path(t).name for t in accessed_targets}

    def is_accessed(path, name):
        return (path in accessed_targets
                or (path and Path(path).name in accessed_basenames)
                or (name and name in accessed_targets))

    # History pins are not assets of their own -- they reference binaries we
    # already have. But a pin the attacker actually saw in the bash-history dump
    # counts as DISCOVERY of the binary it points at. Build that credit set
    # explicitly (path and name) so the attribution is intentional, not merely a
    # side effect of substring matching.
    binary_ids = [(r.get("path", "").strip(), r.get("name", "").strip())
                  for r in asset_rows
                  if r.get("asset_type", "").strip() in ("binary", "process")]
    history_discovered: set[str] = set()
    for r in asset_rows:
        if r.get("asset_type", "").strip() != "history":
            continue
        pinned = (r.get("value_or_target", "") or "").strip()
        if not pinned or pinned not in discovery_text:
            continue  # only count pins the attacker actually collected
        for bpath, bname in binary_ids:
            if (bname and bname in pinned) or (bpath and bpath in pinned):
                if bpath:
                    history_discovered.add(bpath)
                if bname:
                    history_discovered.add(bname)

    def is_discovered(path, name, value):
        # Discovered via a history pin that references this binary.
        if (path and path in history_discovered) or (name and name in history_discovered):
            return True
        for token in (path, name, value):
            if token and token in discovery_text:
                return True
        if path and Path(path).name in discovery_text:
            return True
        return False

    # Define the categories shown on the stacked bar chart.
    categories = {
        "Honey files": [],
        "Honey ENVs": [],
        "Honey binaries/processes": [],
    }

    # Binaries and processes are the *same* asset (a process is a running
    # binary), so they are merged and de-duplicated by path (falling back to
    # name). This collapses a binary that also appears as a process, and any
    # duplicate rows from multiple deployment snapshots, into a single asset.
    # 'history' pins are bash-history hints, not binaries/processes, and are not
    # counted here (matching the evaluator, which only scores binary/process).
    envs_seen: dict[str, tuple] = {}
    bin_proc_seen: dict[str, tuple] = {}
    for row in asset_rows:
        atype = row.get("asset_type", "").strip()
        entry = (row.get("path", "").strip(),
                 row.get("name", "").strip(),
                 row.get("value_or_target", "").strip())
        if atype == "env":
            envs_seen.setdefault(entry[1] or entry[0], entry)
        elif atype in ("binary", "process"):
            bin_proc_seen.setdefault(entry[0] or entry[1], entry)
        # history / unknown asset types are intentionally skipped.

    categories["Honey ENVs"] = list(envs_seen.values())
    categories["Honey binaries/processes"] = list(bin_proc_seen.values())

    # Honeyfiles de-duplicated by path for the same robustness.
    files_seen: dict[str, tuple] = {}
    for row in honeyfiles:
        path = row.get("path", "").strip()
        files_seen.setdefault(path or row.get("filename", "").strip(),
                              (path, row.get("filename", "").strip(), ""))
    categories["Honey files"] = list(files_seen.values())

    counts: dict[str, int] = {}
    status: dict[str, dict[str, int]] = {}
    for cat, entries in categories.items():
        acc = disc = undisc = 0
        for path, name, value in entries:
            if is_accessed(path, name):
                acc += 1
            elif is_discovered(path, name, value):
                disc += 1
            else:
                undisc += 1
        counts[cat] = len(entries)
        status[cat] = {"accessed": acc, "discovered": disc, "undiscovered": undisc}

    return counts, status


# --------------------------------------------------------------------------- #
# Load everything once
# --------------------------------------------------------------------------- #

def load_analysis_data(paths: dict[str, str]) -> AnalysisData:
    """Parse every input file and return a populated AnalysisData."""
    caldera = parse_caldera_events(paths["events"])
    tetragon_rows = _read_tetragon(paths["tetragon"])
    asset_rows, honeyfiles = load_honey_assets(paths["manifest"], paths["honeyfiles"])
    discovery_text = Path(paths["discovery"]).read_text(encoding="utf-8", errors="replace")

    match_pairs = match_caldera_to_tetragon(caldera, tetragon_rows)
    matches = [ts for ts, _line in match_pairs]
    match_lines = [line for _ts, line in match_pairs]
    honey_hits = detect_honey_hits(tetragon_rows, asset_rows, honeyfiles)
    counts, status = compute_asset_breakdown(
        asset_rows, honeyfiles, honey_hits, discovery_text)

    # Campaign start = first Caldera command; everything is measured from here.
    t0 = min((e.delegated for e in caldera), default=EPOCH)
    command_effects = compute_command_honey_effects(caldera, honey_hits)

    return AnalysisData(
        caldera=caldera,
        tetragon_match=matches,
        tetragon_match_line=match_lines,
        honey_hits=honey_hits,
        honey_asset_counts=counts,
        honey_asset_status=status,
        t0=t0,
        command_honey_effects=command_effects,
    )


# --------------------------------------------------------------------------- #
# Output 1: attack timeline table (CSV)
# --------------------------------------------------------------------------- #

def write_attack_timeline_csv(data: AnalysisData, out_path: str | Path) -> None:
    """Write one row per Caldera command (time-only timestamps)."""
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["#", "delegated_timestamp", "finished_timestamp",
                         "tactic", "ability_name", "plaintext_command", "status"])
        for i, ev in enumerate(data.caldera, start=1):
            writer.writerow([i, _elapsed_hms(ev.delegated, data.t0),
                             _elapsed_hms(ev.finished, data.t0),
                             ev.tactic, ev.ability_name, ev.command, ev.status])
    print(f"[+] wrote {out_path}")


def write_attack_honeyasset_timeline_csv(data: AnalysisData, out_path: str | Path) -> None:
    """Like attack_timeline.csv, plus a per-command 'honey_effects' column."""
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["#", "delegated_timestamp", "finished_timestamp", "tactic",
                         "ability_name", "plaintext_command", "status", "honey_effects"])
        for i, (ev, effect) in enumerate(zip(data.caldera, data.command_honey_effects), start=1):
            writer.writerow([i, _elapsed_hms(ev.delegated, data.t0),
                             _elapsed_hms(ev.finished, data.t0),
                             ev.tactic, ev.ability_name, ev.command, ev.status, effect])
    print(f"[+] wrote {out_path}")


def _normalise_event_line(raw: str | None, ts: datetime | None, t0: datetime) -> str:
    """Return the Tetragon line with its leading absolute timestamp replaced by
    the normalised (campaign-relative) time, so the whole report shares one
    time reference. Everything after the timestamp is left untouched.
    """
    if not raw or ts is None:
        return raw or ""
    _, sep, rest = raw.partition("|")
    if not sep:
        return raw
    return f"{_elapsed_hms(ts, t0)} |{rest}"


def write_caldera_tetragon_map_csv(data: AnalysisData, out_path: str | Path) -> None:
    """Map each Caldera command to its matched Tetragon event.

    Every timestamp in this file is normalised to campaign start (00:00:00) for
    a single, comprehensible time reference -- including the leading timestamp
    of the matched Tetragon event line (the rest of the line is unchanged).
    Tetragon columns are left blank when no event could be matched.

    Columns: row number, Caldera start/end, tactic, ability name, plaintext
    command, earliest matched Tetragon event timestamp, matched Tetragon line.
    """
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["#", "caldera_start", "caldera_end", "tactic",
                         "ability_name", "plaintext_command",
                         "tetragon_earliest_timestamp", "tetragon_event_line"])
        for i, (ev, t_match, line) in enumerate(
                zip(data.caldera, data.tetragon_match, data.tetragon_match_line), start=1):
            tet_ts = _elapsed_hms(t_match, data.t0) if t_match is not None else ""
            writer.writerow([i, _elapsed_hms(ev.delegated, data.t0),
                             _elapsed_hms(ev.finished, data.t0),
                             ev.tactic, ev.ability_name, ev.command,
                             tet_ts, _normalise_event_line(line, t_match, data.t0)])
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Output 2: phase metrics (JSON)
# --------------------------------------------------------------------------- #

def write_phase_metrics_json(data: AnalysisData, out_path: str | Path) -> None:
    """Record the wall-clock time of the first command of each tactic."""
    metrics = {key: None for key in FIRST_COMMAND_TACTICS.values()}
    for ev in data.caldera:  # already sorted by delegated time
        key = FIRST_COMMAND_TACTICS.get(ev.tactic)
        if key and metrics[key] is None:
            metrics[key] = _elapsed_hms(ev.delegated, data.t0)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
    print(f"[+] wrote {out_path}")


def write_alert_timeline_csv(
    data: AnalysisData,
    alerts_path: str | Path,
    out_path: str | Path,
) -> None:
    """
    Create a campaign-relative timeline of Alertmanager alerts.

    Campaign start is normalised to 00:00:00.

    Output rows:
      - campaign_start
      - each expected alert
      - campaign_end

    Alert time is taken from Alertmanager 'startsAt'.
    Time-to-alert is:
        alert startsAt - campaign start

    Alerts that did not fire are included with empty timestamps.
    """

    # ---------------------------------------------------------------
    # Read Alertmanager alerts
    # ---------------------------------------------------------------

    with open(alerts_path, encoding="utf-8") as fh:
        raw_alerts = json.load(fh)

    # Keep the first occurrence of each expected alert.
    alerts_by_name: dict[str, dict] = {}

    for alert in raw_alerts:
        name = alert.get("alertname", "").strip()

        if name not in ALERT_NAMES:
            continue

        starts_at = alert.get("startsAt")

        if not starts_at:
            continue

        try:
            ts = _parse_iso(starts_at)
        except ValueError:
            print(
                f"[!] Could not parse startsAt for alert "
                f"{name}: {starts_at}"
            )
            continue

        # If the same alert occurs more than once, retain the earliest
        # occurrence because time-to-alert is based on first detection.
        existing = alerts_by_name.get(name)

        if existing is None or ts < existing["timestamp"]:
            alerts_by_name[name] = {
                "timestamp": ts,
                "state": alert.get("state", ""),
                "summary": alert.get("summary", ""),
            }

    # ---------------------------------------------------------------
    # Campaign start/end
    # ---------------------------------------------------------------

    campaign_start = data.t0

    if campaign_start is None:
        raise ValueError("Campaign start time could not be determined.")

    # The campaign ends when the final CALDERA command finishes.
    campaign_end = max(
        (event.finished for event in data.caldera),
        default=campaign_start,
    )

    # ---------------------------------------------------------------
    # Build timeline
    # ---------------------------------------------------------------

    rows = []

    # Campaign start
    rows.append({
        "event": "campaign_start",
        "timestamp": campaign_start,
        "relative_time": "00:00:00",
        "time_to_alert_seconds": "",
        "state": "",
        "summary": "",
    })

    # Alerts
    for alert_name in ALERT_NAMES:

        alert = alerts_by_name.get(alert_name)

        # Alert did not fire.
        if alert is None:
            rows.append({
                "event": alert_name,
                "timestamp": None,
                "relative_time": "",
                "time_to_alert_seconds": "",
                "state": "",
                "summary": "",
            })
            continue

        ts = alert["timestamp"]

        time_to_alert = (ts - campaign_start).total_seconds()

        rows.append({
            "event": alert_name,
            "timestamp": ts,
            "relative_time": _elapsed_hms(ts, campaign_start),
            "time_to_alert_seconds": round(time_to_alert, 3),
            "state": alert["state"],
            "summary": alert["summary"],
        })

    # Campaign end
    rows.append({
        "event": "campaign_end",
        "timestamp": campaign_end,
        "relative_time": _elapsed_hms(campaign_end, campaign_start),
        "time_to_alert_seconds": "",
        "state": "",
        "summary": "",
    })

    # ---------------------------------------------------------------
    # Sort chronologically
    #
    # Alerts that did not fire have timestamp=None and are placed
    # after all timestamped events.
    # ---------------------------------------------------------------

    rows.sort(
        key=lambda row: (
            row["timestamp"] is None,
            row["timestamp"] if row["timestamp"] is not None
            else datetime.max.replace(tzinfo=timezone.utc),
        )
    )

    # ---------------------------------------------------------------
    # Write CSV
    # ---------------------------------------------------------------

    with open(out_path, "w", newline="", encoding="utf-8") as fh:

        writer = csv.writer(fh)

        writer.writerow([
            "event",
            "absolute_timestamp",
            "relative_timestamp",
            "time_to_alert_seconds",
            "state",
            "summary",
        ])

        for row in rows:

            absolute = (
                row["timestamp"].isoformat().replace("+00:00", "Z")
                if row["timestamp"] is not None
                else ""
            )

            writer.writerow([
                row["event"],
                absolute,
                row["relative_time"],
                row["time_to_alert_seconds"],
                row["state"],
                row["summary"],
            ])

    print(f"[+] wrote {out_path}")

# --------------------------------------------------------------------------- #
# Plot helpers shared by plot 1 and plot 2
# --------------------------------------------------------------------------- #

def _draw_caldera_tetragon_lanes(ax, data: AnalysisData,
                                 y_caldera: float, y_tetragon: float) -> list[datetime]:
    """Draw Caldera & Tetragon command marks plus connecting lines.

    All timestamps are normalised to elapsed time since the campaign start
    (data.t0 -> 00:00:00). Returns the shifted timestamps drawn (for scaling).
    """
    all_times: list[datetime] = []
    for ev, t_match in zip(data.caldera, data.tetragon_match):
        color = ev.color
        c_time = _shift(ev.delegated, data.t0)
        # Caldera mark (lower lane).
        ax.plot(c_time, y_caldera, marker="|", markersize=22,
                markeredgewidth=2.2, color=color)
        all_times.append(c_time)
        # Tetragon mark (upper lane) + connecting line, if matched.
        if t_match is not None:
            t_time = _shift(t_match, data.t0)
            ax.plot(t_time, y_tetragon, marker="|", markersize=22,
                    markeredgewidth=2.2, color=color)
            ax.plot([c_time, t_time], [y_caldera, y_tetragon],
                    color=color, linewidth=0.7, alpha=0.6)
            all_times.append(t_time)
    return all_times


# --------------------------------------------------------------------------- #
# Plot 1: Phases & detection (Caldera vs Tetragon)
# --------------------------------------------------------------------------- #

def plot_phases_caldera_vs_tetragon(data: AnalysisData, out_path: str | Path) -> None:
    y_caldera, y_tetragon = 0.0, 1.0
    fig, ax = plt.subplots(figsize=(14, 4.5))

    times = _draw_caldera_tetragon_lanes(ax, data, y_caldera, y_tetragon)

    ax.set_yticks([y_caldera, y_tetragon])
    ax.set_yticklabels(["Caldera", "Tetragon"])
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("Time since campaign start [minutes]")
    ax.set_title("Phases and Detection by Caldera-Log and Tetragon Log")

    _style_time_axis(ax, times)
    present_tactics = [t for t in TACTIC_COLORS if any(e.tactic == t for e in data.caldera)]
    ax.legend(handles=_tactic_legend_handles(present_tactics),
              loc="upper left", ncol=len(present_tactics), fontsize=8,
              bbox_to_anchor=(0, 1.22), frameon=False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Plot 2: Overview incl. honey-asset interaction / execution
# --------------------------------------------------------------------------- #

def plot_overview_with_honey(data: AnalysisData, out_path: str | Path) -> None:
    y_caldera, y_tetragon = 0.0, 1.0
    fig, ax = plt.subplots(figsize=(14, 5))

    times = _draw_caldera_tetragon_lanes(ax, data, y_caldera, y_tetragon)

    # Honey-asset markers live on the Tetragon lane:
    #   solid  = interaction with any honey asset
    #   dashed = execution of a honey binary
    for hit in data.honey_hits:
        h_time = _shift(hit.ts, data.t0)
        times.append(h_time)
        if hit.is_execution:
            ax.vlines(h_time, y_tetragon - 0.12, y_tetragon + 0.42,
                      color="black", linewidth=1.3, linestyle="--", zorder=1)
        else:
            ax.vlines(h_time, y_tetragon - 0.12, y_tetragon + 0.42,
                      color="black", linewidth=1.3, linestyle="-", zorder=1)

    ax.set_yticks([y_caldera, y_tetragon])
    ax.set_yticklabels(["Caldera", "Tetragon"])
    ax.set_ylim(-0.6, 1.9)
    ax.set_xlabel("Time since campaign start [minutes]")
    ax.set_title("Overview: Interaction between Caldera Commands, "
                 "Tetragon Detection and Honey Assets")

    _style_time_axis(ax, times)

    present_tactics = [t for t in TACTIC_COLORS if any(e.tactic == t for e in data.caldera)]
    handles = _tactic_legend_handles(present_tactics)
    handles += [
        Line2D([0], [0], color="black", linestyle="-", label="Honey-asset interaction"),
        Line2D([0], [0], color="black", linestyle="--", label="Honey-binary execution"),
    ]
    ax.legend(handles=handles, loc="upper left", ncol=4, fontsize=8,
              bbox_to_anchor=(0, 1.22), frameon=False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Plot 3: Honey assets vs normal files (stacked bar)
# --------------------------------------------------------------------------- #

def plot_honey_vs_normal(data: AnalysisData, out_path: str | Path) -> None:
    file_cat = "Honey files"
    env_cat = "Honey ENVs"
    bin_cat = "Honey binaries/processes"

    def totals(cat):
        s = data.honey_asset_status.get(cat, {})
        return s.get("accessed", 0), s.get("discovered", 0), s.get("undiscovered", 0)

    # Aggregate across all honey categories for the "Total honey assets" bar.
    tot_acc = sum(totals(c)[0] for c in data.honey_asset_status)
    tot_disc = sum(totals(c)[1] for c in data.honey_asset_status)
    tot_undisc = sum(totals(c)[2] for c in data.honey_asset_status)

    f_acc, f_disc, f_undisc = totals(file_cat)
    e_acc, e_disc, e_undisc = totals(env_cat)
    b_acc, b_disc, b_undisc = totals(bin_cat)

    labels = ["Normal files", "Total honey assets", "Honey files",
              "Honey ENVs", "Honey binaries/\nprocesses"]
    accessed = [0, tot_acc, f_acc, e_acc, b_acc]
    discovered = [0, tot_disc, f_disc, e_disc, b_disc]
    undiscovered = [NORMAL_FILE_COUNT, tot_undisc, f_undisc, e_undisc, b_undisc]

    fig, ax = plt.subplots(figsize=(11, 6.5))
    x = range(len(labels))

    c_acc, c_disc, c_undisc = "#1f77b4", "#ff7f0e", "#2ca02c"
    p1 = ax.bar(x, accessed, color=c_acc, label="Accessed / interacted")
    p2 = ax.bar(x, discovered, bottom=accessed, color=c_disc,
                label="Discovered, not accessed")
    bottom2 = [a + d for a, d in zip(accessed, discovered)]
    p3 = ax.bar(x, undiscovered, bottom=bottom2, color=c_undisc,
                label="Not discovered")

    # Segment value labels (skip zeros).
    for bars in (p1, p2, p3):
        for rect in bars:
            h = rect.get_height()
            if h > 0:
                ax.text(rect.get_x() + rect.get_width() / 2,
                        rect.get_y() + h / 2, str(int(h)),
                        ha="center", va="center", fontsize=9, fontweight="bold")

    # Per-bar totals above each stack.
    totals_per_bar = [a + d + u for a, d, u in zip(accessed, discovered, undiscovered)]
    for xi, tot in zip(x, totals_per_bar):
        ax.text(xi, tot + max(totals_per_bar) * 0.01, f"Total: {tot}",
                ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Number of entities")
    ax.set_title("Honey Assets vs Normal Files")
    ax.legend(loc="upper right")
    ax.margins(y=0.12)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Plot 4: Honey-asset interaction timeline (count per timestamp)
# --------------------------------------------------------------------------- #

def plot_honey_interaction_timeline(data: AnalysisData, out_path: str | Path) -> None:
    # Group honey hits by whole-second timestamp; count distinct targets.
    grouped: dict[datetime, set[str]] = {}
    type_at: dict[datetime, set[str]] = {}
    for hit in data.honey_hits:
        key = _shift(hit.ts, data.t0).replace(microsecond=0)
        grouped.setdefault(key, set()).add(hit.target)
        type_at.setdefault(key, set()).add(hit.asset_type)

    fig, ax = plt.subplots(figsize=(14, 4.5))

    if not grouped:
        ax.text(0.5, 0.5, "No honey-asset interactions detected in Tetragon log",
                ha="center", va="center", transform=ax.transAxes)
    else:
        times = sorted(grouped)
        max_count = max(len(v) for v in grouped.values())
        for t in times:
            n = len(grouped[t])
            ax.vlines(t, 0, n, color="#d62728", linewidth=2)
            ax.plot(t, n, marker="o", color="#d62728", markersize=5)
            label = f"{n}\n({', '.join(sorted(type_at[t]))})"
            ax.annotate(label, (t, n), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=8)
        ax.set_ylim(0, max_count + 1.2)
        _style_time_axis(ax, times)

    ax.set_ylabel("# honey assets affected")
    ax.set_xlabel("Time since campaign start [minutes]")
    ax.set_title("Honey-Asset Interaction Timeline (from Tetragon log)")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


def plot_detection_delay(data: AnalysisData, out_path: str | Path) -> None:
    """Plot Tetragon detection delay per command over the course of the campaign.

    delay = (matched Tetragon event time) - (Caldera command start / delegated)

    The command start (``delegated_timestamp``) is the anchor: a command can only
    be observed *after* it was issued, so the delay is non-negative by
    construction. (Using Caldera's finish time would be wrong here -- Tetragon
    records a process at EXEC, i.e. its start, which can precede the command's
    completion and would yield impossible negative "delays".)

    A dashed line marks the average delay across all matched commands.
    x-axis: campaign time (normalised, command start). y-axis: delay in seconds.
    """
    xs, ys, colors = [], [], []
    for ev, t_match in zip(data.caldera, data.tetragon_match):
        if t_match is None:
            continue
        delay = (t_match - ev.delegated).total_seconds()
        # Guard: matches are constrained to occur at/after delegation, but clamp
        # any residual sub-second clock-skew artefact so no negative point shows.
        delay = max(0.0, delay)
        xs.append(_shift(ev.delegated, data.t0))  # position on the timeline
        ys.append(delay)
        colors.append(ev.color)

    fig, ax = plt.subplots(figsize=(14, 5))
    if xs:
        order = sorted(range(len(xs)), key=lambda k: xs[k])
        xs_s = [xs[k] for k in order]
        ys_s = [ys[k] for k in order]
        cols_s = [colors[k] for k in order]
        ax.plot(xs_s, ys_s, color="#888888", linewidth=0.8, zorder=1)
        ax.scatter(xs_s, ys_s, c=cols_s, s=60, zorder=2, edgecolors="black", linewidths=0.4)

        avg = sum(ys_s) / len(ys_s)
        ax.axhline(avg, color="black", linewidth=1.4, linestyle="--", zorder=3,
                   label=f"average = {avg:.1f}s")
        ax.set_ylim(0, max(ys_s) * 1.15 + 0.5)
        _style_time_axis(ax, xs_s)
    else:
        ax.text(0.5, 0.5, "No Caldera<->Tetragon matches to plot",
                ha="center", va="center", transform=ax.transAxes)

    ax.set_ylabel("Tetragon detection delay [s]")
    ax.set_xlabel("Time since campaign start [minutes]")
    ax.set_title("Tetragon Detection Delay per Command "
                 "(delay = Tetragon event - Caldera command start)")

    present_tactics = [t for t in TACTIC_COLORS if any(e.tactic == t for e in data.caldera)]
    handles = _tactic_legend_handles(present_tactics)
    if xs:
        handles.append(Line2D([0], [0], color="black", linestyle="--",
                              label=f"average = {avg:.1f}s"))
    ax.legend(handles=handles, loc="upper left", ncol=len(handles),
              fontsize=8, frameon=False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


def _truncate(text: str, width: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def _light(color: str, amount: float = 0.82) -> tuple:
    """Return a lightened version of a matplotlib colour for row tinting."""
    import matplotlib.colors as mcolors
    r, g, b = mcolors.to_rgb(color)
    return (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


def plot_attack_honeyasset_table(data: AnalysisData, out_path: str | Path) -> None:
    """Render the attack timeline as a table, incl. the honey-effects column."""
    col_labels = ["#", "del→fin", "tactic", "ability_name",
                  "plaintext_command", "status", "honey effects"]
    # Per-column display width budgets (characters) for truncation.
    cmd_w, ab_w, eff_w = 54, 26, 34

    rows, row_colors = [], []
    for i, (ev, effect) in enumerate(zip(data.caldera, data.command_honey_effects), start=1):
        time_cell = f"{_elapsed_hms(ev.delegated, data.t0)}→{_elapsed_hms(ev.finished, data.t0)}"
        rows.append([
            str(i),
            time_cell,
            ev.tactic,
            _truncate(ev.ability_name, ab_w),
            _truncate(ev.command, cmd_w),
            str(ev.status),
            _truncate(effect, eff_w),
        ])
        row_colors.append(_light(ev.color))

    n = len(rows)
    fig, ax = plt.subplots(figsize=(18, max(2.0, 0.42 * n + 1.0)))
    ax.axis("off")
    ax.set_title("Attack & Honey-Asset Timeline", fontweight="bold", pad=12)

    table = ax.table(cellText=rows, colLabels=col_labels,
                     cellLoc="left", loc="upper center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    # Relative column widths (sum ~1.0): #, time, tactic, ability, command, status, effects.
    col_widths = [0.035, 0.11, 0.10, 0.165, 0.32, 0.05, 0.22]
    for (r, c), cell in table.get_celld().items():
        cell.set_width(col_widths[c])
        cell.set_height(0.9 / (n + 1))
        if r == 0:  # header
            cell.set_facecolor("#333333")
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor(row_colors[r - 1])
            # Emphasise non-empty honey-effect cells (now column index 6).
            if c == 6 and rows[r - 1][6]:
                cell.set_text_props(fontweight="bold")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def build_default_paths(samples: str) -> dict[str, str]:
    s = Path(samples)
    return {
        "events": str(s / "event-logs.json"),
        "manifest": str(s / "honey-asset-manifest.csv"),
        "honeyfiles": str(s / "honeyfiles.csv"),
        "discovery": str(s / "discovery.log"),
        "tetragon": str(s / "tetragon-udr.log"),
        "alerts": str(s / "alertmanager-alerts.json"),

    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", help="Caldera event-logs.json")
    ap.add_argument("--manifest", help="honey-asset-manifest.csv")
    ap.add_argument("--honeyfiles", help="honeyfiles.csv")
    ap.add_argument("--discovery", help="discovery.log (attacker POV)")
    ap.add_argument("--tetragon", help="tetragon-udr.log")
    ap.add_argument("--alerts", help="Alertmanager alertmanager-alerts.json")
    ap.add_argument("--samples", default="samples",
                    help="directory holding the 5 inputs with default names")
    ap.add_argument("--out", default="out", help="output directory")
    args = ap.parse_args()

    paths = build_default_paths(args.samples)
    for key in paths:
        override = getattr(args, key)
        if override:
            paths[key] = override

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    data = load_analysis_data(paths)

    # Tabular / JSON outputs.
    write_attack_timeline_csv(data, out / "attack_timeline.csv")
    write_attack_honeyasset_timeline_csv(data, out / "attack-honeyasset-timeline.csv")
    write_caldera_tetragon_map_csv(data, out / "caldera-tetragon-map.csv")
    write_phase_metrics_json(data, out / "phase_metrics.json")

    # Plots — each callable on its own with the same `data` object.
    plot_phases_caldera_vs_tetragon(data, out / "01_phases_caldera_vs_tetragon.png")
    plot_overview_with_honey(data, out / "02_overview_caldera_tetragon_honey.png")
    plot_honey_vs_normal(data, out / "03_honey_assets_vs_normal_files.png")
    plot_honey_interaction_timeline(data, out / "04_honey_interaction_timeline.png")
    plot_attack_honeyasset_table(data, out / "05_attack_honeyasset_table.png")
    plot_detection_delay(data, out / "06_tetragon_detection_delay.png")
    write_alert_timeline_csv(data, paths["alerts"], out / "alert_timeline.csv",)

    print("[✓] done.")


if __name__ == "__main__":
    main()