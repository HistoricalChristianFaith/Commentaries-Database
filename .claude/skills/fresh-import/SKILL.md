---
name: fresh-import
description: Replace an old import of a church father's commentary with a fresh public-domain translation (resolve the work, survey, delete the old blocks, pilot, chunks, final review, close the issue), autonomously unless the user asks for checkpoints. Takes a Writings-Database html path, or a historicalchristian.faith / GitHub url of one.
argument-hint: <work html path or url>
disable-model-invocation: true
---

# Fresh-translation import

Work to import: `$ARGUMENTS`

The process for replacing an old (usually machine-translated) import of a commentary with a fresh
public-domain translation, worked out over the "fresh Jerome" series (Commentaries-Database
issues #32 onwards). Everything it needs is in this folder:

- `SKILL.md` (this file): what every run needs. Read all of it, and the project `CLAUDE.md`,
  before starting.
- `reference/` (tracked): what applies only to some works or cases, read when a step below
  says so: `works-keys.md`, `new-importer.md` (other fathers and layouts, *Models by layout*),
  `selective.md`, `source-proofreading.md`, `old-blocks.md`, `audit-flags.md` (HARD lines, log
  format), `log-digest.md` (big runs).
- `scripts/` (gitignored, never committed): the importers, the audit, the per-piece checks, the
  deletion tool, extra checks, a KJV lookup. The importers' `WORKS` entries, with their notes,
  record every work imported so far and are the models for a new run.
- `RUNS.md` (gitignored): the history of every run on this machine ([Run history](#run-history)).
- `work/` (gitignored, made by the importer): the cut pieces and the run logs.

The rules were approved by the user across the series; follow them exactly. If a rule changes
during a run, update the docs (Phase 7). Run every command from the Commentaries-Database root;
`scripts/` means `.claude/skills/fresh-import/scripts/`.

**Prerequisites:** Python 3.11+ (`tomllib`), the `claude` CLI on the PATH, `gh` logged in, and a
checkout of `HistoricalChristianFaith/Writings-Database`, found next to this repo
(`../Writings-Database`) or at `$WRITINGS_DB`.

---

## 1. The shape of the job

- **Source:** one HTML file in the Writings-Database, e.g. `Jerome/Commentary on Joel.html`:

  ```
  <article class="writing">
  <h1>Commentary on Joel</h1><i>translator's note</i><br><br>    (the preamble)
  <h2>Prologue</h2> ...                    (non-verse: the work's prologue)
  <h2>Book Two</h2> ...                    (non-verse: a book preface, in multi-book works)
  <h2>1:1</h2> <i>lemma</i> exposition...  (a verse section)
  ```

  **Read the translator's note:** how the lemmas are laid out (the Hebrew version, then "LXX:"),
  how Psalms are numbered, how Greek and Hebrew are rendered, whether there are footnotes.
- **Target:** `[[commentary]]` blocks in `<Father>/<Book C_V>.toml`, each with `quote`,
  `source_url` (the historicalchristian.faith url of the html, built by `source_url_for()`) and
  `source_title`.
- **Old blocks:** the earlier import shares that source_url; sometimes there are also url-less
  excerpts of an older translation, `#anchor` variants and old cross-references in other books.
  All are deleted first. Blocks from the father's other works are never touched.
- **Who does what:** the Python driver cuts the work into pieces and hands each to a headless
  `claude` agent, which decides the verse file for every stretch, then checks the piece and sends
  a second prompt built from what the checks found. You prepare the notes, run the deletion,
  pilot and rest yourself (in the background), review, fix mechanical problems, commit, and bring
  the user only the decisions that are theirs ([Run modes](#run-modes)).

## 2. Tools

All in `scripts/`; read them before using them.

| Tool | Use |
|---|---|
| `process_jerome_commentary.py <Work> …` | The importer. Splits on `<h2>` into pieces (one per chapter; a chapter over 30k is cut at section boundaries). Per piece, one conversation: prompt 1 (import), the per-piece checks, prompt 2 built from them, the checks again; HARD lines left ABORT the run. Options: `--dry-run` (pieces, prompt 1, BASE, a sample prompt 2), `--split-only`, one piece name, `--start-after NAME`, `--through NAME`, `--check`, `--base <commit>`, `--legacy-prompt2` (the old "Double check…" prompt, no checks). Logs: `work/jerome_<work>_import_logs/run-*.jsonl` (answers and check records), `run-*.events.jsonl` (full stream). |
| `piece_review.py <Work> <BASE> <piece> [--prompt2] [--raw]` | The per-piece checks, read-only: the audit narrowed to one piece, sorted HARD / SOFT / INFO (§5). |
| `delete_commentaries.py <Father> <url> [--title-prefix P] [--titles-file F] [--file-prefix P] [--dry-run]` | Deletes blocks whose source_url matches exactly (and title starts with P / is a line of F; `--file-prefix` limits the files). Cuts blocks out of the text, so other blocks keep their bytes. **Never run it with an empty url and no prefix.** |
| `audit_jerome_import.py <Work> --headings` / `<BASE> <pieces…>\|--all` | Before: headings vs the KJV, lemma hints, lemma-only sections. After: every check in §5 (verbatim, coverage, lemmas, placement hints, filenames, cross-refs), where the non-verse sections went, a per-section LAYOUT. `BASE` = the deletion commit. |
| `import_checks.py <Work> continuity\|boundaries\|pieces\|notes\|order\|oldranges <BASE>` | Heading continuity; lemma-only sections and piece openings; reassembly of the pieces; the notes' quotations; source order; the verses only the old import (every block deleted in BASE) covered, old blocks in other files, old filenames that aren't KJV verses. |
| `kjv_lookup.py "<Book> <C>:<V>[-<V>]"` | KJV text (`kjv.sqlite`, which the audit also reads). The prompt tells the agents to use it. |

Other fathers have their own importers (`process_<father>[_<work>]_commentary.py`); the audit and
`import_checks.py` use the one whose `WORKS` has the work key. They still send the old generic
prompt 2 with no per-piece checks (`reference/new-importer.md`). A `WORKS` entry holds `html`,
`book`, `source_title` and `notes`, plus optional layout keys (`reference/works-keys.md`).

**Gotchas**
- A run deletes the units folder when every piece succeeded, and keeps it on an abort. Only a run
  reaching the LAST piece runs `--check` by itself; otherwise run it yourself.
- `--start-after A --through B` runs everything between A and B: chain ranges around the pilot
  pieces with `&&` so they aren't run twice.
- The audit's "files added or changed since BASE" counts only tracked files; new files are
  untracked and don't appear there.
- zsh passes an unquoted `$VAR` of several piece names as ONE argument, and `$P` holding a
  command fails ("no such file or directory"): write names and commands out, or use `${=VAR}`.
- Changing `load_work`, `strip` or `pack_chars` after the pilot can move piece boundaries: re-run
  `--dry-run` for every work of that importer and run what's left by explicit piece names. After
  any source or `load_work` change, re-run `--check` on everything already imported.
- Never re-serialize TOML (rtoml, tomlkit): edit the text and verify by re-parsing.
- Don't fix files in the father's folder while a run is going: the running piece's snapshot sees a
  file you merged or renamed as DELETED (HARD) and the run aborts. Note fixes, apply them after.
- **Concurrent imports:** assume the user has other imports running, maybe in the same father
  folder and the same `WORKS`. Scope `git status`, the audit's changed files and any rollback by
  this work's source_url; never blanket-checkout or delete untracked files; edit only your own
  `WORKS` entry. Commit only your own changes, at the set times (Phase 2, Phase 6), staged by an
  explicit list (`git add --pathspec-from-file=<list>`), never `git add -A`/`-u`/`.` on a folder.
  A glob doesn't match deleted files: build the deletion's list from the dry run. Read
  `git diff --cached --stat` before each commit. A shared file goes in only if all its changes
  since HEAD are this work's blocks.

## 3. Standing rules (approved by the user)

1. **The agent decides placement, not the script.** The driver only cuts the source and passes
   hints (headings, numbering notes); the agents choose the KJV verse file for each stretch.
   Never precompute a section-to-file table in Python: headings can be off, and judging placement
   is the point of using an agent. Give known numbering quirks to the agents as prose in the
   notes. Deterministic checks afterwards check coverage and format, not exact placement. The
   prompt pushes toward the SMALLEST verse ranges; never add wording that lets the agents default
   to the source's own section ranges.
2. **Placement by commentary, not lemma.** File every block under the verse(s) its COMMENTARY
   addresses; a lemma quoting several verses never widens a block's range ("We are interested in
   the commentary, not so much the lemma").
   - If the exposition covers only the lemma's first verse, the first block (lemma included,
     uncut) goes under that verse (Jerome's "9:14ff." quoting Isaiah 9:14-21 → `Isaiah 9_14`).
   - If the comment starts on a later verse (the lemma opens with a bare formula verse, "And the
     word of the Lord came to me, saying:"), the first block starts its range there.
   - But a range is never narrower than the text: when the exposition treats the whole lemma as
     one unit, the file covers every verse it spans (LEMMA VERSES UNFILED, §5).
3. **Lemmas stay whole.** Each section's lemma (Hebrew AND LXX version, plus remarks inside the
   LXX parenthesis) stays uncut at the start of the section's first block, and every section's
   first block starts exactly at the section start. When an agent joins the end of one section to
   the next section's lemma (same verse), split at the section start, both blocks in the same
   file. A tail after a mid-sentence editors' break stays with its own section. The exception: a
   lemma-only section whose exposition is in the next section (`attach_next`, Phase 1).
4. **Smaller is better, but no fragments.** Split by verse where the text really moves verse by
   verse. Keep a range when a pass sweeps the verses as one argument (Jerome usually expounds a
   lemma twice: historically, then spiritually). Overlapping ranges are fine when one sentence
   crosses a verse boundary; no text is ever duplicated within the book.
5. **Prologue:** a prologue that introduces the book's content goes in WHOLE, without asking, as
   the first block of `<Book> 1_1`, before the 1:1 commentary and after any existing blocks
   (Jerome's separate Vulgate "Prologue to <Book>" stays first), even if it discusses a later
   verse: a reader opening the first verse should see it. A prologue that is purely dedicatory or
   autobiographical, with nothing tied to Scripture (e.g. Jerome's Ecclesiastes preface, on
   Blesilla's death and his way of translating), is NOT filed automatically: it goes into the
   Phase 1 table for the user to decide, like a book preface (rule 6). Scribal rubrics ("HERE
   BEGINS THE BOOK.") are left out.
6. **Book prefaces** (multi-book works):
   - A substantive one gets its own block under the verse(s) it explains, possibly in another
     book, possibly after that verse's commentary: Galatians' Book Two preface ("senseless
     Galatians") as the second block of `Galatians 3_1`, Isaiah's Book Sixteen to Romans
     3_13-18, Ezekiel's Book Eleven ("This Gog is the Goth") to Ezekiel 38_2.
   - A dedicatory or autobiographical one is skipped, even if it quotes Scripture in passing
     (Galatians Book Three: Jerome's style, eyesight and dictation); filed under a verse it would
     mislead that verse's readers. An empty heading has nothing to import.
   - You read every preface yourself and bring the user a table; the user decides case by case,
     and the decisions go into the notes as fixed instructions the agents don't judge.
7. **Closing notes** to a patron (end of the work or of a book) are cut, as are notes closing a
   book (Ezekiel's end of Book Eleven: "Thus far we have spoken…"). Short transitions ("let us
   pass on to…", "We have touched briefly on the obvious things…") are kept.
8. **Cross-references** stay on: a stretch that genuinely QUOTES AND EXPOUNDS another book's verse
   is also filed under that verse. It must be the father's OWN exposition of that verse: not a
   reading he reports and leaves unresolved, not a passing proof-text. The excerpt starts at a
   sentence a reader of THAT verse can follow, never at one whose "here", "this passage" or "he
   says" means the host book. Its filename covers every KJV verse the quoted words span, matched
   by wording: Latin/Greek verse division differs from the KJV's beyond the Psalms too. Check
   every Psalm cross-reference's number and verse against the KJV wording (Jerome uses the Latin
   numbering, often with the Hebrew in brackets). In review, read every XREF OPENINGS line.
9. **Append-only:** pre-existing files only get blocks appended. A "-1 line" diff where the old
   text is still a prefix is just a file that lacked a final newline.
10. **Source order:** within a file, this work's blocks follow the source's order. Out-of-sequence
    pieces (pilots) can break this: run `import_checks.py <Work> order` and reorder by cutting
    the file text, only in files new since BASE.
11. **Verbatim.** Copy the translation exactly: Origenian signs (÷ ※ ⁚), Greek, transliterated
    Hebrew with its glosses, quotation marks, dashes, odd punctuation. Drop html tags (italics
    become plain text, not quotation marks), the translator's note, the `<h2>` headings,
    manuscript rubrics and the editors' inline sub-lemma labels like "19 d.". Separate paragraphs
    with a blank line.
12. **Commits** (Commentaries-Database, directly on `master`, never pushed by you):
    - the deletion: `remove old <father> on <book> import (ahead of fresh translation, #N)` (Jerome's
      importer finds BASE by "remove old <father> on <book> import": keep those words);
    - ONE commit for the whole import: `<father> on <book>: import fresh translation (#N)`;
    - only if the run changed the skill's tracked docs (a rule, a tool's documented behaviour, a
      general lesson; Phase 7): `fresh-import: <what changed>`. A routine run makes no skill
      commit: `RUNS.md`, `WORKS` and `scripts/` are gitignored.
    - With no issue, leave out ` (#N)` / `, #N`.
    - Autonomous mode: make these commits yourself; checkpoint mode: ask before the import and
      skill commits (the user sometimes makes and pushes them). Either way check `git log`
      first. Never commit in the Writings-Database.
13. **What to import from a selective work:** a stretch where the father quotes or plainly refers
    to a specific verse AND DOES SOMETHING WITH IT; never a verse quoted in passing, a bare
    proof-text, a chain of proof-texts or a mere mention. One continuous verbatim stretch per
    block, under the smallest range it addresses, never two overlapping blocks of the work in one
    file. The full approved wording is in `reference/selective.md`.

## 4. The process

### Run modes

**Autonomous (the default).** Unless the user asks for checkpoints, run the whole job: prep, the
deletion and its commit, the pilot, the rest if the pilot is clean, the final review, the import
commit, the issue's closing and the run record. A ⏸ is then a short status, not a stop. Stop and
ask only:
- where a step says so (Phase 0: an unresolvable path or url, a checkout behind and not clean, a
  work that isn't verse-by-verse, an existing `WORKS` entry or earlier fresh import);
- for the user's decisions: dedicatory or autobiographical prologues, book prefaces and closing
  notes (rules 5-7; a prologue introducing the book's content needs none); old blocks of unclear
  identity (strays under the father, possible excerpts of another work, out-of-book blocks you
  can't match); a fix to the Writings-Database source; a change to a standing rule;
- when the pilot or a run isn't clean.

Ask everything in one go, with the facts needed, then carry on.

**Clean** means: no piece aborted; after mechanical fixes (§6) the audit has no HARD line (§5);
every coverage gap is an intended skip; every SOFT flag checks out against the KJV wording; every
LEMMA VERSES UNFILED line is classified and every XREF OPENINGS line read; and the prompt answers
raise nothing the notes didn't foresee. If a pilot shows only that the notes need a sharper
instruction, roll it back (Phase 3), amend the notes and run it again; stop and ask if the second
pilot isn't clean either.

The run ends with one report: the Phase 5 summary, the commits, the issue's closing comment.

**Checkpoints** (when asked: "with checkpoints", "stop at each stage", "let me review each
step"): stop at every ⏸, ask before the import and skill commits, and ask (AskUserQuestion)
whether the user or you runs the pilot and each chunk.

Start every ⏸ message with where you are and what's next, e.g. "**Phase 2 (deletion) done, BASE =
abc1234. Next: Phase 3 (pilot).**", so the run can resume after a pause or a context summary.

### Phase 0: Resolve the work (no changes anywhere)

1. **Turn the argument into a local html file** in the Writings-Database checkout (not found:
   ask). A local path must be inside it (else stop and ask). A historicalchristian.faith url
   (`by_father.php?file=…`): url-decode `file` until no `%` escapes remain and join it onto the
   root (project `CLAUDE.md`). A GitHub url of the Writings-Database (`…/blob/<branch>/…`,
   `raw.githubusercontent.com/…/<branch>/…`): url-decode the path after the branch. Any other
   url: stop and ask; don't download into the Writings-Database.
2. **Make it current.** If the file is missing or a GitHub url was given, `git -C <WDB> fetch`
   and compare with upstream: behind and clean → `git pull --ff-only`; otherwise stop and tell
   the user.
3. **Gather the facts** and show them in one short block:
   - father (top folder), title (`<h1>`), KJV book (from `book_names.json`), `WORKS` key (the
     book name, as in existing entries); size and `<h2>` section count;
   - the source_url exactly as `source_url_for()` builds it, compared with the old blocks' url;
   - the importer: Jerome's, or the father's own. **No importer fits** (a father with none, a
     layout none handles): read `reference/new-importer.md`;
   - **not a verse-by-verse commentary** (treatise, dialogue, sermons, letters): read
     `reference/selective.md`, then stop and ask whether to import it selectively, and which old
     blocks to delete;
   - an existing `WORKS` entry, or an earlier fresh import
     (`git log --oneline -i --grep "on <book>: import fresh translation"`): stop and ask;
   - **the issue:** `gh issue list --repo HistoricalChristianFaith/Commentaries-Database --state
     open --search "<Father> <Book>"`. A clear match is `#N`; none: say so (no number in the
     commits, nothing to close).
4. **Read** the scripts in §2 and the `WORKS` entries of the closest earlier works (size,
   structure; `RUNS.md` and *Models by layout* in `reference/new-importer.md` name them). Read
   their `RUNS.md` entries (source fixes, the user's decisions, what went wrong);
   `git log --oneline -i --grep "<book>.*fresh translation"` gives their commits and
   `gh issue view N --comments` their closing comment.

### Phase 1: Prep (no database changes)

1. **Survey the source:** size, section count, non-verse sections and their lengths, heading
   formats (a/b/c half-verses, "ff.", commas, cross-chapter ranges), lemma layout, Psalm
   numbering, footnotes/`<sup>`, inline references like "(Matt 7:7)"; compare with the
   translator's note.
   - **OCR'd, an unchecked fresh translation, split over several files, or with footnotes or
     Greek to verify:** read `reference/source-proofreading.md` and proofread now.
   - Add a skeleton `WORKS` entry (html, book, source_title, empty notes); for anything more
     (many short chapters, lemma-only sections, a lead-in before lemmas, chapter headings,
     editorial marks to strip) read `reference/works-keys.md`. `--dry-run` then prints the pieces.
2. **Check the headings:** `audit_jerome_import.py <Work> --headings` and `import_checks.py <Work>
   continuity`. The "lemma opens like" flags are noisy (part-verse lemmas look like the previous
   verse): check every flag and discontinuity against the KJV. Known kinds:
   - editors' references off by a verse (Isaiah);
   - Vulgate chapter starts unlike the KJV (Ezekiel "2:1b" = KJV 1:28; Haggai ch. 2 a verse ahead);
   - a heading skipping a verse's second half (Ezekiel "11:2b-12" starts at 11:1b);
   - Hebrew-vs-KJV chapter divisions (Joel 2:28-32 = Hebrew 3:1-5; Ezekiel 20:45-49 = Hebrew
     21:1-5): settle which numbering the headings follow;
   - labels following the Latin verse division: list every section opening with the previous
     verse's end, running into an unlabelled verse, or running ahead; the pilot agents often find
     more, so add them to the notes before the rest runs.
3. **Check the piece boundaries:** `import_checks.py <Work> boundaries` (lemma-only sections,
   sections not opening with italics, every piece's opening). A lemma-only section whose
   exposition is in the next section: list it in `attach_next` and tell the agents to join the
   two in one block (better than merging by hand). A piece starting mid-lemma otherwise (Isaiah's
   "13:18ff." / "14:1"): write a note telling the next piece where to append, and merge the two
   blocks yourself afterwards.
4. **Read every non-verse section and the end of every book.** Draft a table: book · what it
   precedes · size · content · recommendation (skip / keep → file). A prologue introducing the
   book needs no row (rule 5); a purely dedicatory or autobiographical one does.
5. **Survey the old blocks:** `delete_commentaries.py <Father> "<url>" --dry-run` and, if needed,
   `… "" --title-prefix "COMMENTARY ON <BOOK>" --dry-run`; search all blocks for the book's name
   in source_url and source_title (anchor and title variants). **Url-less excerpts, other-site
   urls, odd titles or blocks of uncertain origin:** read `reference/old-blocks.md`. List the old
   blocks outside the book's files with their opening words; compute the after-state (blocks,
   files touched, files emptied, files keeping other works' blocks) and what `<Book> 1_1` will hold.
6. **Write `WORKS["<Work>"]["notes"]`,** modelled on the closest entries (Ezekiel's, Joel's and
   Ecclesiastes' are thorough):
   - **numbering:** headings are hints, with the off-heading examples from step 2; a/b/c means
     the whole verse; how cross-chapter ranges are written (`Ezekiel 1_27-2_1`);
   - **lemma layout:** how this work marks its lemmas, the irregular ones by heading, and "every
     section starts its own block; never join sections";
   - **verbatim specifics:** this work's signs, glosses, quotation marks, dashes; "cut between
     sentences" if sections are long paragraphs;
   - **Psalm and other numbering:** it differs by translator and within one work (Latin, Hebrew,
     the title as verse 1, misprints): name every non-KJV reference with its wording and tell the
     agents to place by wording; likewise Latin-numbered Sirach, Baruch, Jonah, and Greek Esther
     (KJV Apocrypha numbering, which `kjv.sqlite`'s `esther,greek` doesn't follow);
   - **rule 2**, with an example from this book, and the double pass with "don't fragment";
   - **"Earlier pieces of THIS run"** leave blocks of this work in the files: leave them and
     append; name files holding other works' blocks if useful;
   - **the prologue's placement** in `<Book> 1_1`;
   - **the fixed decisions:** each preface and closing note (its first and last words, so the
     agent finds the cut) and any piece-boundary instructions.

   Quote source text exactly, then `import_checks.py <Work> notes`: a fragment it can't find is a
   paraphrase in quotation marks or a typo. It reads every text between two `"` as a quotation;
   with many quotations, check the PAIRED ones (`re.findall(r'"([^"]+)"', notes)`) instead.
7. `--dry-run` again (read all of prompt 1), `--split-only`, `import_checks.py <Work> pieces`
   (the pieces must reassemble into the source), then delete `work/jerome_<work>_units/`.
8. **⏸ Show the user:** the non-verse table with recommendations, a summary of the notes, the
   heading findings, the deletion dry runs with the after-state and the old out-of-book blocks.
   Autonomous: a status, unless the table needs decisions or the old blocks have strays.

### Phase 2: Deletion

Run the deletion(s) for real; verify every file parses, no targeted block remains, and each
trimmed file holds exactly its other blocks (parsed, vs `git show HEAD:<path>` minus the deleted
ones). Commit only those `<Father>/` files, staged by list, with rule 12's message, in ONE commit,
never with skill edits. That commit is **BASE** for the audit and `oldranges`, and must exist
before the pilot: Jerome's importer finds it by message (or `--base`) and won't run without it;
`--dry-run` shows the one it found.

### Phase 3: Pilot

Choose 2–6 pieces covering the risks: Part001 (prologue, `<Book> 1_1`), half-verse or off
headings, a substantive preface, a numbering boundary, a closing note, the last piece. Name each
with its risk and its command, e.g.
`python3 .claude/skills/fresh-import/scripts/process_jerome_commentary.py <Work> Part003_Ch02.html`.

**Run them yourself,** chained with `&&` in ONE background Bash call (`run_in_background`), so a
failed or aborted piece stops the rest (each piece takes minutes, beyond the foreground timeout);
output to a log in your scratchpad. Wait for the
notification; don't poll. Check the log's tail for `ABORTING`: an abort leaves the piece's blocks
and units in place, and its `error` record names the HARD lines; fix them (§6) or roll back and
sharpen the notes. (Checkpoint mode: first ask whether the user runs it in their terminal.)

**⏸ After the pilot:** start from the per-piece check records and prompt answers in the
`run-*.jsonl` log (§5); run `audit_jerome_import.py <Work> <BASE> <pilot pieces…>`; check every
SOFT flag, LEMMA VERSES UNFILED and XREF OPENINGS line; fix mechanical problems. Clean → go on;
otherwise, or in checkpoint mode, bring the user the judgment calls.

**Rollback:** everything of this work after BASE is pilot output: restore the pre-existing files
holding this work's url from BASE and delete the new files holding only this work's blocks,
checking each file first (*Concurrent imports*).

### Phase 4: The rest

- **Up to ~12 pieces in all:** after a clean pilot, everything left in one chained background
  command (ranges around the pilot pieces, e.g. `Part002` alone, then `--start-after Part003
  --through Part012`).
- **More:** chunks of 20–35 pieces, run the same way; once one comes back clean, the rest can go
  in one command.
- **⏸ After each run:** read its check records and audit its pieces; for 20 or more pieces, or
  an importer still on the old prompt 2, read `reference/log-digest.md` and have a subagent
  digest the prompt answers; run `import_checks.py
  <Work> order`; fix mechanical problems (§6). Clean → go on; otherwise, or in checkpoint mode,
  bring the user the judgment calls.

### Phase 5: Final review

1. `process_jerome_commentary.py <Work> --check`. Expected failures: skipped prefaces (start and
   end probes), cut closing notes (end probe), dropped labels like "19 d." (start probe), a
   preface filed in another book (checked only in the book's own files). Anything else is real.
2. `audit_jerome_import.py <Work> <BASE> --all`: every gap an intended skip; no HARD line; every
   SOFT flag checked, every LEMMA VERSES UNFILED line classified, every XREF OPENINGS line read
   (§5); the `<Book> 1_1` blocks in the right order.
3. **Old vs new:** `import_checks.py <Work> oldranges <BASE>`. Paste its output into the review
   and read each miss: genuine (add it, or widen a narrowed range), covered, or passing. Many
   misses or old filenames to read: `reference/old-blocks.md`. Bring genuine misses needing new
   text to the user.
4. `import_checks.py <Work> order`; spot-check the Psalm cross-references (number, verse by wording).
5. Counts: blocks and files in the book; cross-ref blocks and files; new vs appended files
   (`git status --porcelain --untracked-files=all -- <Father>`; `git diff --stat BASE --
   <Father>` shows only insertions).
6. **⏸ Summarize** with a draft closing comment. Autonomous and clean: on to Phase 6, the summary
   going into the final report; not clean: stop and ask.

### Phase 6: Finish

Commit the import (checkpoint mode: after approval; never if the user already did). Stage only
this work's files: every new or changed `<Father>/` file since BASE holding this work's url,
never another session's; check every other block in each is unchanged since HEAD; `git add
--pathspec-from-file=<list>`. With an issue, close it:
`gh issue close N --repo HistoricalChristianFaith/Commentaries-Database --comment "…"`, ONE
paragraph in the style of #35, #36 and #37 (`gh issue view N --comments`): both commits; what was
deleted (counts, out-of-book blocks, url-less excerpts); what was imported (blocks and files,
cross-references with the notable verses and why); where the prologue and kept prefaces went;
what was left out; a sentence on lemmas and heading quirks; ending "Blocks from other works in
pre-existing files were kept unchanged."

### Phase 7: Record the run

The `WORKS` entry (with its final notes) is the record a later import models itself on. Then:
1. **Append the run's entry to `RUNS.md`** (gitignored, no commit; create it per
   [Run history](#run-history) if missing), with what a later run of a similar work would want
   (its header lists it); a short paragraph for one more entry in an existing importer. Claims
   like "every old verse covered", "100% coverage" or "nothing to fix" must come from a command's
   output (`oldranges`, the audit, `--check`), never from a hand-written check.
2. **Edit the docs only for what is general:** a new or changed rule (with the user's approval),
   a tool's changed behaviour, a *Models by layout* row, or a lesson any future run should check
   for (one to three lines, no counts or dates): in `SKILL.md` if every run needs it, else in the
   `reference/` file for its case. Nothing about this run alone.
3. If the docs changed, make the skill commit (rule 12). Then send the final report.

## Run history

`RUNS.md`, next to this file, holds one entry per work run on THIS machine (source quirks and
fixes, the user's decisions, pilot and run, counts, agent slips, old blocks, the review's
additions). It is gitignored, so a fresh checkout has none. It is reference, not instructions:
read the entries for works like the one at hand (Phase 0), never the whole file. Without it, the
history up to Ambrosiaster on Philippians is in `git show
084de666:.claude/skills/fresh-import/SKILL.md` (§2, "Other fathers" to "Gotchas with the tools");
start a new `RUNS.md` with a one-paragraph header saying what it is and what an entry records.

## 5. Reviewing a batch

**The run logs.** Jerome's importer logs each prompt's answer and, after each prompt, a check
record per piece (`check: "after prompt N"`, `counts`, `hard`, `soft`, `lemma_unfiled`, `info`);
an aborted piece has an `error` record. Start every review there (they replace most of the log
digest's job; still read the prompt answers). The checks (`piece_review.py`)
sort the audit's lines for the piece:
- **HARD:** NOT VERBATIM, MULTI-MATCH, OVERLAP, LEMMA CUT, LEMMA (unless the expected join after
  an `attach_next` section), START, JOINED?, NOT APPEND-ONLY, a GAP in a verse section, BAD
  FILENAME, STRAY, PSALM NEIGHBOUR, a wrong title, TOML PARSE ERROR, DELETED, CHECK CRASHED;
- **SOFT:** PLACEMENT?, OUTSIDE HEADING, XREF CONTEXT?, wide range, small block, a GAP in a
  non-verse section, and any code `piece_review.py` doesn't know yet (never fatal);
- **INFO:** LEMMA VERSES UNFILED, XREF OPENINGS, LEMMA? (no opening italics), the expected joins.

Prompt 2 lists the HARD lines to fix or, with none, asks for a targeted review (unfiled lemma
verses, cross-references considered and not filed, the openings of those filed, the SOFT flags),
each with a reason either way so agents don't over-file. A piece that needed the fix prompt gets
no review: review its SOFT and INFO lines yourself. `piece_review.py <Work> <BASE> <piece>`
re-checks one piece (`--prompt2`: the prompt it'd give; `--raw`: the whole audit). **A HARD line
in your review, an abort, or a code not explained here:** read `reference/audit-flags.md`.

**Reading the audit**
- **PLACEMENT?** is a hint; most are correct, of three kinds: (1) a bare formula verse skipped
  ("the word of the Lord came to me" → the next verse); (2) a part-verse lemma opening with the
  second half of a verse; (3) rule 2, the first comment on a later verse (a textual note on
  33:25-26 → `33_25-26`). Read the lemma and what follows against the KJV: a real misplacement
  is a lemma filed under a verse it doesn't quote and whose comment it doesn't contain.
- **OUTSIDE HEADING** is expected where a heading is known to be off ("2:1b" → `1_28`).
- **wide range** is fine for whole-passage summaries and sweeping passes (Ezekiel's "Now the
  whole vision is this…" → `1_4-28`); read the opening. **small block** is fine when coherent:
  merge only true fragments, never across a section start. **A big block** on one verse: compare
  its opening with the next verse's first quotation before calling it under-split.
- **GAP** lines must all be intended skips; a gap inside a verse section is lost text: re-import
  it (in source order) or report it.
- **XREF OPENINGS:** read every line: each excerpt must make sense to a reader of THAT verse
  (rule 8). **XREF CONTEXT?** marks a first sentence pointing back to the host book ("said
  above", "the same thing", "this place", "something of the kind", "what follows", "he says"):
  start the excerpt later or drop it.
- **LEMMA VERSES UNFILED:** verses the lemma quotes that no file of this work in the book covers.
  Classify each: "comment silent on it" (fine) or "narrowed too far" (widen the filename).

**Things that are NOT problems** (don't "fix" them):
- formula verses missing from filenames;
- overlapping ranges from sentences crossing verses, or from second passes;
- verses with no file because the father never comments on them separately (NOT a verse quoted
  in a lemma whose exposition treats the lemma as one unit: that's a narrowed range, LEMMA VERSES
  UNFILED);
- cross-ref excerpts ending at a semicolon where the father turns to a new point;
- a cross-ref filed as its own `Psalms 118_9` beside an existing `Psalms 118_8-9`.

## 6. Mechanical fixes

Edit the file text, never re-serialize: split at lines matching `^\[\[commentary\]\][ \t]*$`,
rearrange or cut the block texts, re-join, parse, and assert the result equals the intended list.
- **Two sections joined in one block:** split at the section start into two blocks with identical
  source fields, same file, in order.
- **Blocks out of source order:** reorder the block texts, only in files new since BASE (old blocks
  stay first in pre-existing files).
- **A lemma-only block at a piece boundary:** join it with its continuation (consecutive in the
  source: use the source's separator) in the first file, and delete the continuation block.
- **A wrong source_url or source_title** on this work's block: fix the string in place.
- **A misnamed file** (BAD FILENAME, PSALM NEIGHBOUR, a narrowed range): `mv` it; if the target
  exists, append the blocks to it instead.
- Re-run the audit on the affected pieces (or `piece_review.py`) after any fix.
