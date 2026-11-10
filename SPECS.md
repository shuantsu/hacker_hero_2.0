# Hacker Hero — Full Application Specification

Status: draft for PySide6 migration  
Legacy reference: `main.py` (Python 2.7 / Tkinter), `Cerealizer.py` (v0.5, bundled)  
Target stack: Python 3.12+, PySide6, `requirements.txt` (no conda)

---

## 1. Overview

### 1.1 Purpose

Hacker Hero is a desktop editor for **Frets on Fire** song `.ini` files. It lets users view and edit:

- Song metadata (`artist`, `name`, `count`, `cassettecolor`)
- High-score tables (`scores`) across four difficulties

It does **not** edit notes/charts (`.ini` chart data lives elsewhere); it only edits the score/metadata INI that FoF stores alongside a song.

### 1.2 Goals for the migration

| Goal | Description |
|------|-------------|
| Parity | Reproduce all legacy behaviors listed in §3 unless marked otherwise |
| Modern stack | Python 3 + PySide6; drop conda, drop vendored full Cerealizer |
| Testability | Core (codec + document model) fully testable without a GUI |
| Robustness | Fix known legacy crashes (§7) while keeping file-format compatibility |
| Packaging | `requirements.txt` / `pyproject.toml`; optional later PyInstaller build |

### 1.3 Non-goals (v1)

- Editing `scores_ext`, `scores_bass`, `scores_coop`, `scores_rhythm` (preserved byte-for-byte as opaque hex — see §8.1)
- Chart/note editing, audio preview, song import/export
- Multi-file batch editing
- Online score submission

---

## 2. Domain model

### 2.1 INI file structure

Files are standard INI with a single section used by the app:

```ini
[song]
artist = <string>
name = <string>
count = <integer>
cassettecolor = #RRGGBB          ; optional
scores = <hex>                   ; Cerealizer blob, see §2.3
scores_ext = <hex>               ; optional, opaque to v1
scores_bass = <hex>              ; optional, opaque
scores_coop = <hex>              ; optional, opaque
scores_rhythm = <hex>            ; optional, opaque
delay = <integer>                ; optional, opaque
frets = <string>                 ; optional, opaque
tutorial = <integer>             ; optional, opaque
version = <string>               ; optional, opaque
lol = <string>                   ; optional, opaque
```

Rules:

- Only the `[song]` section is read/written by the app.
- Unknown keys and any other sections **must be preserved** on save.
- Key names are case-insensitive on read (standard INI); canonical form is lowercase.
- Values are UTF-8 / latin-1 safe strings; FoF historically used iso-8859-1 for player names (§2.4).

### 2.2 Score tables (`scores`)

Logical structure after decoding:

```text
scores: dict[int, list[tuple]]
```

- **Key** = difficulty id:
  | id | Difficulty |
  |----|------------|
  | 0  | Amazing    |
  | 1  | Medium     |
  | 2  | Easy       |
  | 3  | Supaeasy   |
- **Value** = ordered list of score entries for that difficulty.
- Difficulties with no entries may be **absent** from the dict (not empty lists). Observed in samples; the app must tolerate both absent keys and empty lists.
- Entry tuple (length **4**):

  ```text
  (score: int, stars: int, name: str, hash: str)
  ```

  | Field | Type | Rules |
  |-------|------|-------|
  | `score` | int ≥ 0 | displayed/edited as decimal digits only |
  | `stars` | int 0–5 (legacy UI); data may contain 6 | digits only |
  | `name` | str | player name; stored as latin-1 bytes in hash input |
  | `hash` | 40-char lowercase hex | SHA-1, recomputed on every edit (§2.4) |

- List order is significant (listbox index = tuple index).
- Duplicate names are allowed.

### 2.3 Cerealizer wire format (minimal codec)

The hex value in `scores` is:

```text
hex( utf-8/latin-1 bytes of a Cerealizer dump )
```

Legacy: `Cerealizer.dumps(obj).encode('hex')` / `loads(data.decode('hex'))`.

#### 2.3.1 Scope of the codec

Full `Cerealizer.py` supports many types. **All observed FoF `scores*` blobs use only:**

- container objects: `dict`, `list`, `tuple`
- inline refs: `int` (`i…`), `str` (`s…`), object ref (`rN`), `None` (`n`)

The migration **shall** implement a dedicated `scores_codec` supporting exactly this subset (plus defensive rejection of unknown type names). No need to port class instances, sets, unicode `u` refs, etc., unless a real file requires them (add golden tests if discovered).

#### 2.3.2 Binary/text layout

Dump is ASCII lines (latin-1 safe). Layout:

```text
cereal1\n
<object_count>\n
# --- Phase A: one block per object, in registration order ---
<classname block for object 0>
<classname block for object 1>
...
# --- Phase B: data block per object, same order ---
<data block for object 0>
<data block for object 1>
...
# --- Root reference ---
<ref to root object>
```

**Classname blocks:**

| Class | Block |
|-------|--------|
| `dict` | `dict\n` |
| `list` | `list\n` |
| `tuple` | `tuple\n` + `<len>\n` + `<ref for elem 0>…<ref for elem n-1>` |

Note: **tuples write their full contents in Phase A** (not Phase B). This matches legacy `TupleHandler.dump_obj`.

**Data blocks (Phase B):**

| Class | Block |
|-------|--------|
| `dict` | `<n>\n` then `n` times: `<ref value> <ref key>` (**value before key**) |
| `list` | `<n>\n` then `n` times: `<ref item>` |
| `tuple` | *(empty — no Phase B data)* |

**References (`<ref>`):**

| Syntax | Meaning |
|--------|---------|
| `i<decimal>\n` | inline int |
| `s<len>\n` + exactly `len` bytes | inline str (no trailing newline after payload) |
| `r<index>\n` | reference to object `index` (0-based, Phase A order) |
| `n` | None (no newline) |
| `b0` / `b1` | bool (unlikely in scores; optional support) |

Unknown ref type byte → raise `ScoresCodecError`.

#### 2.3.3 Object collection order (for dump)

When serializing, object order must be stable enough for round-trip tests. Legacy order:

1. Root and all reachable non-tuple containers (`dict`/`list`) in DFS discovery order (dict: keys then values; list: items).
2. Then all distinct tuples, sorted by **immutable depth** (max nested-tuple depth), stable for ties.

Empty dict `{}` serializes as a single dict object with `0\n` data and root `r0`.

For **round-trip equality** (load→dump→load), order of dict keys may differ (Python dict order). Tests should compare decoded structures, not raw hex, except for dedicated golden-byte tests where order is fixed.

#### 2.3.4 Hex encoding

- Encode: `bytes.hex()` (lowercase) — matches legacy `encode('hex')`.
- Decode: `bytes.fromhex(s)` — tolerate surrounding whitespace; reject odd length / non-hex with `ScoresCodecError`.

### 2.4 Score hash algorithm

On every mutation of `(score, stars, name)` for difficulty `i`:

```python
def score_hash(difficulty: int, score: int, stars: int, name: str) -> str:
    # name encoded as latin-1 (iso-8859-1) to match legacy hashlib input
    payload = f"{difficulty}{score}{stars}{name}".encode("iso-8859-1", errors="strict")
    return hashlib.sha1(payload).hexdigest()  # 40 lowercase hex chars
```

- If `name` contains characters outside latin-1, encode with `errors="strict"` and surface a validation error in the UI (do not silently corrupt). Legacy would raise on `encode('iso8859-1')` only at hash time.
- Hash is **always** recomputed on save/edit; never trusted from file for the active row after an edit. On load, hash from file is kept until that row is edited.

### 2.5 `cassettecolor`

- Stored as `#RRGGBB` (leading `#`, 6 hex digits), case-insensitive on read; write lowercase or preserve as user picked.
- Empty/missing → treated as no color (white default in UI).
- Invalid format → treat as no color; do not crash; optionally warn.

### 2.6 `count`

- Non-negative integer.
- Legacy UI: spinbox `0 .. sys.maxsize`.
- Empty on save → do not write / leave existing (see FR-F4 for desired clear behavior).

---

## 3. Functional requirements

IDs: `FR-<area>-<n>`. **Parity** = must match legacy unless noted.

### 3.1 File — Open

| ID | Requirement |
|----|-------------|
| FR-O-1 | File → Open (Ctrl+O) opens a file dialog filtered to `*.ini` + all files. |
| FR-O-2 | If document is dirty, prompt Save / Don't save / Cancel before opening. Cancel aborts open. |
| FR-O-3 | Parse INI; build document model (§4.2). Missing `[song]` → error dialog, no crash, controls stay disabled. |
| FR-O-4 | Decode `scores` if present. Decode failure → treat as no scores, show warning, do not crash (legacy crashed — **fix**). |
| FR-O-5 | Load metadata into fields; apply color to `cassettecolor` widget; enable song controls. |
| FR-O-6 | Enable only difficulty radio buttons for keys present in `scores` (or all four if scores is empty/none — see FR-D-2). |
| FR-O-7 | Select a difficulty (legacy: last key iterated; **new:** prefer Amazing→…→Supaeasy first available, or Medium if present — document choice in UI tests). Reset score list selection; clear Name/Stars/Score editors. |
| FR-O-8 | Clear dirty flag after successful open. |
| FR-O-9 | Remember last directory for subsequent Open/Save As (enhancement over legacy; low risk). |

### 3.2 File — Save / Save As / Exit

| ID | Requirement |
|----|-------------|
| FR-S-1 | Save (Ctrl+S): if no document loaded → warning “Please open a file”. |
| FR-S-2 | First save of an opened file (no Save As yet): confirm “Rewrite this file?” Yes/No. |
| FR-S-3 | Save As: dialog `*.ini`, default extension `.ini`; sets save path; subsequent Save writes there without re-asking rewrite confirmation (legacy `saveFileName` behavior). |
| FR-S-4 | Write path: apply UI values into model, serialize `scores` to hex, write INI preserving unknown keys/sections. |
| FR-S-5 | **Clearing a text field:** if user clears `artist`/`name`/`count`/`cassettecolor`, save shall **remove or write empty** that key (legacy left stale value — **fix**, see FR-F-4). Config: prefer writing empty string only if key existed; or delete key — pick delete-if-cleared for cleanliness; tests define choice. |
| FR-S-6 | If `scores` model is `None` (no scores), do not invent a `scores` key; leave absent or preserve original hex untouched. |
| FR-S-7 | If `scores` model is non-`None`, always rewrite `scores` hex from model (even if empty dict → empty-structure blob). |
| FR-S-8 | Dirty flag cleared only after successful write. IO errors → message box, stay dirty. |
| FR-S-9 | Exit / window close: if dirty → prompt Save / Don't save / Cancel (yes/no/cancel). Cancel keeps app open. |

### 3.3 Dirty tracking

| ID | Requirement |
|----|-------------|
| FR-D-1 | Dirty when: metadata field edited, color changed, score row fields edited, difficulty list mutation (future add/delete), successful edit operations. Not dirty on mere open or failed validation revert. |
| FR-D-2 | Enter key in text fields does not mark dirty by itself (legacy skipped keycode 13); programmatic set of fields must not mark dirty. |
| FR-D-3 | Spinbox arrow clicks mark dirty (legacy crashed here — **fix**: treat as change). |

### 3.4 Song metadata

| ID | Requirement |
|----|-------------|
| FR-M-1 | Editable fields: `artist` (line edit), `name` (line edit), `count` (spin int ≥ 0), `cassettecolor` (read-only line edit + picker). |
| FR-M-2 | `count` rejects non-digits on input (strip non-digits or validator). |
| FR-M-3 | Color: clicking/focusing `cassettecolor` opens color dialog initialized to current color. |
| FR-M-4 | On color choose: write `#rrggbb` into field; set widget background to that color; set foreground black/white by luminance (average RGB > 127 → black else white). |
| FR-M-5 | Cancel color dialog → no change. |
| FR-M-6 | Focus workaround (legacy): when opening picker from `count`/`artist` focus dance — **optional**; PySide6 can drop if picker behaves. Not required for parity. |

### 3.5 Difficulties and score list

| ID | Requirement |
|----|-------------|
| FR-T-1 | Radio group: Supaeasy=3, Easy=2, Medium=1, Amazing=0 (labels as legacy). |
| FR-T-2 | Switching difficulty reloads listbox from `scores[diff]` (or empty). |
| FR-T-3 | Listbox shows **player name only** (entry[2]), one row per entry, order preserved. |
| FR-T-4 | Selecting a row enables score editor and loads `score`, `stars`, `name` into fields. |
| FR-T-5 | No selection → score editor disabled. |
| FR-T-6 | Difficulties missing from `scores` → radio disabled (cannot switch to them). If `scores` is None/empty → all difficulty UI disabled or list empty without crash. |

### 3.6 Score row editing

| ID | Requirement |
|----|-------------|
| FR-E-1 | Editable: Name (text), Stars (0–5 spin or validated int), Score (digits only). |
| FR-E-2 | On any change to Name/Stars/Score for selected row: update model tuple, recompute hash (§2.4), mark dirty. |
| FR-E-3 | If Name changed: update listbox row text in place; keep selection. |
| FR-E-4 | Enter in score fields: do not mark dirty by key alone; actual value change marks dirty (align with FR-D-2). |
| FR-E-5 | Stars out of range → clamp 0–5 on commit (legacy spin limits); score empty → treat as 0 on hash/save. |
| FR-E-6 | Changing difficulty with dirty row: row edits already applied live to model (legacy applied on each keystroke); no extra prompt. |

### 3.7 About / Help

| ID | Requirement |
|----|-------------|
| FR-H-1 | Help → About: dialog with app name, author Filipe Teixeira, contact `shuantsu@gmail.com`, runtime Python/PySide6 versions (replace hardcoded “Python 2.7.8”). |

### 3.8 Window

| ID | Requirement |
|----|-------------|
| FR-W-1 | Title: `::Hacker Hero::` |
| FR-W-2 | Non-resizable (legacy) — **optional** to allow resize with min size; default parity = fixed. |
| FR-W-3 | Decorative header image (legacy base64 GIF `thumb.png`) — optional; may use `thumb.png` resource or drop. |

---

## 4. UI specification (PySide6)

### 4.1 Widget tree (parity mapping)

```text
QMainWindow (or QWidget) title "::Hacker Hero::"
├─ QMenuBar
│  ├─ File: Open (Ctrl+O), Save (Ctrl+S), Save As…, separator, Exit
│  └─ Help: About
├─ QVBoxLayout
│  ├─ [optional] header image QLabel
│  ├─ QGroupBox "Song Configurations"  (grid)
│  │  ├─ QLabel artist      → QLineEdit artist
│  │  ├─ QLabel cassettecolor → QLineEdit cassettecolor (readOnly) + color button
│  │  ├─ QLabel count       → QSpinBox count (0..2^31-1)
│  │  └─ QLabel name        → QLineEdit name
│  ├─ QHBoxLayout
│  │  ├─ QGroupBox "Difficulties" (QVBoxLayout of QRadioButton)
│  │  │  ├─ Supaeasy (id 3)
│  │  │  ├─ Easy (id 2)
│  │  │  ├─ Medium (id 1)
│  │  │  └─ Amazing (id 0)
│  │  └─ QGroupBox "Scores"
│  │     └─ QListWidget scoresList
│  └─ QGroupBox "Edit Score" (grid)
│     ├─ QLabel Name    → QLineEdit playerName
│     ├─ QLabel Stars   → QSpinBox stars (0..5)
│     └─ QLabel Score   → QLineEdit score (digits only)
└─ QStatusBar (optional: path + dirty indicator)
```

### 4.2 Document model (core, non-GUI)

```text
SongDocument
  path: Path | None
  save_path: Path | None
  dirty: bool
  artist: str
  name: str
  count: int
  cassettecolor: str  # "#rrggbb" or ""
  scores: dict[int, list[ScoreEntry]] | None
  extra: dict[str, str]          # all other [song] keys preserved
  other_sections: dict[str, dict[str, str]]  # non-song sections

ScoreEntry = (score: int, stars: int, name: str, hash: str)
```

Operations: `load(path)`, `save(path=None)`, `set_metadata(...)`, `set_score_entry(diff, idx, ...)`, `is_dirty`.

### 4.3 Signals / control flow

| UI event | Core call |
|----------|-----------|
| Open | `document.load` → populate widgets (block signals) |
| Metadata `textEdited` / `valueChanged` | `document.set_*` + `dirty=True` |
| Difficulty toggled | read `scores[diff]` → fill list |
| List `currentRowChanged` | load entry into editors (block signals) |
| Score editor edited | `document.set_score_entry` + refresh list row + dirty |
| Save | `document.save` |

Use `QSignalBlocker` (or equivalent) when programmatically filling widgets to avoid false dirty.

### 4.4 Validation UX

- Digits-only: `QIntValidator` or input mask / `textChanged` strip.
- Invalid color: leave field text as typed; color swatch falls back to white.
- Codec errors on save: modal with file path and reason; abort write.

---

## 5. Architecture

### 5.1 Proposed layout

```text
hacker-hero/
├── pyproject.toml              # or requirements.txt
├── README.md
├── SPECS.md                    # this file
├── thumb.png
├── example .INIs/              # golden fixtures
├── src/hacker_hero/
│   ├── __init__.py
│   ├── __main__.py             # python -m hacker_hero
│   ├── app.py                  # QApplication bootstrap
│   ├── core/
│   │   ├── __init__.py
│   │   ├── document.py         # SongDocument, ScoreEntry, dirty, save/load orchestration
│   │   ├── scores_codec.py     # minimal Cerealizer subset (§2.3)
│   │   ├── hashing.py          # score_hash (§2.4)
│   │   └── errors.py           # ScoresCodecError, DocumentError, ...
│   ├── io/
│   │   ├── __init__.py
│   │   └── ini_file.py         # configparser read/write + preservation rules
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py      # MainWindow widgets + slots
│       └── resources.py        # optional header image
└── tests/
    ├── test_scores_codec.py    # golden round-trips from example .INIs
    ├── test_hashing.py
    ├── test_document.py
    ├── test_ini_roundtrip.py
    └── test_main_window.py     # optional pytest-qt
```

### 5.2 Dependency rules

- `ui` → `core`, `io` (never reverse).
- `core` → stdlib only (`hashlib`, `dataclasses`, …).
- `io` → stdlib `configparser` + `core.scores_codec`.
- No global mutable codec state; codec is pure functions: `loads(bytes) -> obj`, `dumps(obj) -> bytes`.

### 5.3 Dependencies (requirements.txt)

```text
PySide6>=6.6
# dev
pytest>=8
pytest-qt>=4
```

Drop: conda `environment.yml`, full vendored `Cerealizer.py` (replaced by `scores_codec`).

---

## 6. Error handling matrix

| Condition | Behavior |
|-----------|----------|
| File not found / unreadable | Message; stay on current doc |
| No `[song]` section | Message; open as empty disabled state or refuse — **refuse with message** |
| `scores` hex invalid | Warning; `scores=None`; metadata still editable; score UI disabled |
| `scores` decodes but wrong shape | Same as invalid; validate `dict[int, list[tuple[int,int,str,str]]]` |
| `scores_ext` etc. invalid | Ignore (opaque); preserve raw string on save |
| Name not latin-1 encodable | Block save/edit with validation message |
| Disk write failure | Message; dirty remains True |
| Empty file | Message; refuse |

---

## 7. Legacy bugs and migration decisions

| Legacy issue | Decision |
|--------------|----------|
| `showStats` crashes when `scores` is None/empty | **Fix:** guard; empty list UI |
| Spinbox `command` passes no event → `event.keycode` crash | **Fix:** mark dirty on `valueChanged` |
| Clearing artist/name does not clear saved key | **Fix:** FR-S-5 |
| `scores_ext` desyncs when `scores` edited | **v1:** leave untouched (documented); enhancement §8.1 |
| No add/delete score | **v1:** parity = edit only; enhancement §8.2 |
| `sys.maxint`, `encode('hex')`, `print` stmts, `StandardError` | N/A in Py3 rewrite |
| Difficulty iteration order nondeterministic (Py2 dict) | Define stable preference in FR-O-7 |
| Debug `print` on every score change | Remove; optional log |
| Stars data can be 6 in files | On load show 6 if present; spin max 6 or allow read-only display beyond 5 — **choose:** spin 0–6 to avoid silent clamp on load |

---

## 8. Optional enhancements (out of v1 parity)

### 8.1 `scores_ext` synchronization

When editing a `scores` entry at `(diff, idx)`:

- If `scores_ext[diff][idx]` exists: update field0 = new hash, field1 = stars, field2 = score (observed layout: `(hash, stars, score, …)` — verify per file; do not assume if lengths differ).
- If structures diverge (observed mismatches in samples): only update when index exists and length == 8; else leave.

### 8.2 Add / delete score rows

- Add: append `(0, 0, "Player", hash(0,0,"Player"))` to current difficulty; enable difficulty key if missing.
- Delete: remove selected row; optional confirm.
- Would require list context menu or buttons — new UI.

### 8.3 Edit other keys

`delay`, `frets`, `tutorial`, `version` — optional “Advanced” group.

### 8.4 Instrument scores

`scores_bass` / `scores_coop` / `scores_rhythm` — same editor pattern, separate tabs.

---

## 9. Migration checklist

- [ ] Implement `scores_codec` loads/dumps; golden test: every `scores` and `scores_ext` in `example .INIs/` decodes; `loads(dumps(x)) == x`
- [ ] Implement `score_hash` tests against known tuples from samples (e.g. holydiver entry)
- [ ] `SongDocument` load/save round-trip on all examples: unknown keys preserved; `scores` semantically equal
- [ ] `configparser` settings: `interpolation=None`, `strict=False` optional, `optionxform=str.lower` (or preserve case — default lower matches FoF)
- [ ] Preserve line endings: read with `newline=''` semantics or accept `\n` normalization; document if CRLF files are rewritten as LF
- [ ] MainWindow parity widgets + shortcuts Ctrl+O / Ctrl+S
- [ ] Dirty/close/open prompts (QMessageBox Save/Discard/Cancel)
- [ ] Color picker + luminance fg/bg
- [ ] Digit validators; stars range
- [ ] Disable controls until open (legacy initial state)
- [ ] About dialog
- [ ] Remove conda/env; add `requirements.txt` / `pyproject.toml`
- [ ] README run instructions: `pip install -r requirements.txt && python -m hacker_hero`
- [ ] Optional: PyInstaller spec for Windows release (parity with old GitHub releases)

### 9.1 Suggested test fixtures

Use `example .INIs/*.ini` as golden files:

- `holydiver.ini` — single difficulty, single row, hash known  
- `tutorial.ini` — multi-row, `scores_ext` present, `tutorial=1`  
- `canon rock.ini` — empty `scores_bass/coop/rhythm`, `delay`  
- `black_sabbath-iron_man-…` — all four difficulties  
- File without `scores_ext` — e.g. `sonic_2-robotnick_theme-…`

---

## 10. Acceptance criteria (v1)

1. Open every file in `example .INIs/` without crash; metadata displays correctly.
2. Edit name/stars/score; save; reopen → values and hash match; `scores_ext` and unknown keys unchanged.
3. Save As to new path; original file untouched until explicit Save on original.
4. Dirty prompts on open-another and exit behave per FR-S-9.
5. `pytest` green for codec, hash, document, ini round-trip.
6. App runs on Python 3.12 + PySide6 with `pip install -r requirements.txt` only.

---

## Appendix A — Difficulty / UI value map

| Radio label | Internal id |
|-------------|-------------|
| Amazing     | 0 |
| Medium      | 1 |
| Easy        | 2 |
| Supaeasy    | 3 |

## Appendix B — Legacy API → Py3 quick map

| Legacy | Migration |
|--------|-----------|
| `ConfigParser.ConfigParser` | `configparser.ConfigParser(interpolation=None)` |
| `data.encode('hex')` | `data.hex()` |
| `hexstr.decode('hex')` | `bytes.fromhex(hexstr)` |
| `sys.maxint` | `sys.maxsize` |
| `tkColorChooser.askcolor` | `QColorDialog.getColor` |
| `tkFileDialog.askopenfilename` | `QFileDialog.getOpenFileName` |
| `tkMessageBox.askquestion` | `QMessageBox.question` |
| `Cerealizer.dumps/loads` | `hacker_hero.core.scores_codec` |
| `hashlib.sha1(str)` | `hashlib.sha1(str.encode('iso-8859-1'))` |

## Appendix C — Sample decoded structures

`holydiver.ini`:

```text
scores     = {1: [(240018, 5, "Filipe o bom", "519598ae32bfb6be8306100056e5599d828aaf57")]}
scores_ext = {1: [("519598ae32bfb6be8306100056e5599d828aaf57", 5, 977, 982, 417,
                   "RF-mod-4.15", "000000000", "")]}
```

Hash check: `sha1("1" + "240018" + "5" + "Filipe o bom")` → matches.
