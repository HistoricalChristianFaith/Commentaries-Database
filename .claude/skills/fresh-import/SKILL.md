---
name: fresh-import
description: Replace an old import of a church father's commentary with a fresh public-domain translation (resolve the work, survey, delete the old blocks, pilot, chunks, final review, close the issue), autonomously unless the user asks for checkpoints. Takes a Writings-Database html path, or a historicalchristian.faith / GitHub url of one.
argument-hint: <work html path or url>
disable-model-invocation: true
---

# Fresh-translation import

Work to import: `$ARGUMENTS`

This is the process for replacing an old (usually machine-translated) import of a commentary with
a fresh public-domain translation. It was worked out over the "fresh Jerome" series
(Commentaries-Database issues #32 onwards). Everything it needs is in this folder:

- `SKILL.md` (this file): the process, the standing rules, how to review, mechanical fixes.
- `scripts/` (gitignored: it stays on the user's machine and is never committed): the
  importer, the audit, the deletion tool, the extra checks and a KJV lookup. The importer's
  `WORKS` entries record every work imported so far, with the notes that described its quirks;
  they are the models for a new run.
- `RUNS.md` (gitignored, local only): the history of every run on this machine, one entry per
  work. See [Run history](#run-history).
- `work/` (gitignored, created by the importer): the cut pieces and the run logs.

Read the whole of this file before starting, and the project `CLAUDE.md`. The rules below were
approved by the user across the series; follow them exactly. If a rule changes during a run,
update this file (see Phase 7).

Run every command from the Commentaries-Database root. `scripts/` below means
`.claude/skills/fresh-import/scripts/`.

**Prerequisites:** Python 3.11+ (`tomllib`), the `claude` CLI on the PATH (the importer runs it
headless), `gh` logged in to GitHub, and a checkout of
`HistoricalChristianFaith/Writings-Database`. The scripts look for that checkout next to the
Commentaries-Database (`../Writings-Database`); set `WRITINGS_DB=/path/to/Writings-Database` to
point them elsewhere.

---

## 1. The shape of the job

- **Source:** one HTML file in the Writings-Database, e.g. `Jerome/Commentary on Joel.html`,
  laid out as:

  ```
  <article class="writing">
  <h1>Commentary on Joel</h1><i>translator's note</i><br><br>    (the preamble)
  <h2>Prologue</h2> ...                    (non-verse: the work's prologue)
  <h2>Book Two</h2> ...                    (non-verse: a book preface, in multi-book works)
  <h2>1:1</h2> <i>lemma</i> exposition...  (a verse section)
  <h2>1:2-3</h2> ...
  ```

  **Read the translator's note:** it says how the lemmas are laid out (the Hebrew version, then "LXX:"),
  how Psalms are numbered, how Greek and Hebrew are rendered, and whether there are footnotes.
- **Target:** `[[commentary]]` blocks in `<Father>/<Book C_V>.toml`, each with `quote`,
  `source_url` and `source_title`. The source_url is the historicalchristian.faith url of the html
  file (`source_url_for()` in the importer builds it).
- **Old blocks:** the earlier import of the same work shares that source_url. Sometimes there are
  also variants: url-less excerpts of an even older translation (titled e.g. "COMMENTARY ON
  EZEKIEL 11:34.1-31"), `#anchor` variants of the url, and old cross-references filed under other
  books. All of them get deleted first. Blocks from the father's other works are never touched.
- **Who does what:** the Python driver cuts the work into pieces and hands each piece to a
  headless `claude` agent, which decides the verse file for every stretch of text. You, the
  orchestrating agent, prepare the notes, run the deletion, the pilot and the rest of the import
  yourself (in the background), review each batch, fix mechanical problems, commit, and bring the
  user only the decisions that are theirs. By default the whole run is autonomous; the user can
  ask for checkpoints at every stage instead (see [Run modes](#run-modes)).

## 2. Tools

All are in `scripts/`. Read them before using them.

| Tool | Use |
|---|---|
| `process_jerome_commentary.py <Work> …` | The importer. Splits the html on `<h2>` into pieces (one per chapter; a chapter over 30k chars is cut at section boundaries, and an oversized section stands alone). For each piece it runs `claude -p` twice in one conversation: the import prompt, then "Double check, was this fully imported properly?". Options: `--dry-run`, `--split-only`, a single piece name, `--start-after NAME`, `--through NAME`, `--check`. Per-work settings are in `WORKS` (html path, book, source_title, `notes` injected into every piece's prompt). Logs go to `work/jerome_<work>_import_logs/run-*.jsonl` (summaries) and `run-*.events.jsonl` (full event stream). |
| `delete_commentaries.py <Father> <source_url> [--title-prefix P] [--titles-file F] [--file-prefix P] [--dry-run]` | Deletes blocks whose source_url matches exactly (and whose title starts with P, or is exactly one of F's lines, if given; `--file-prefix "1 Corinthians "` limits it to files whose name starts with that, for an excerpt title shared by two works). It cuts blocks out of the file text, so the other blocks keep their exact bytes, and it refuses an empty url without a prefix. **Never run it with an empty url and no prefix.** |
| `audit_jerome_import.py <Work> --headings` | Before importing: heading formats, headings not in the KJV, "lemma opens like KJV x:y" hints, sections not opening with italics, lemma-only sections. |
| `audit_jerome_import.py <Work> <BASE> <pieces…>` / `--all` | After importing: verbatim + unique match of every block, overlaps, coverage gaps (with opening words), append-only status of pre-existing files, LEMMA/LEMMA CUT checks, PLACEMENT? and OUTSIDE HEADING hints, wide ranges, small blocks, where each non-verse section went, and a per-section LAYOUT. `BASE` is the deletion commit. |
| `import_checks.py <Work> continuity\|boundaries\|pieces\|notes\|order` | Heading continuity, lemma-only sections and piece openings, reassembly of the pieces, verification of every quotation in the notes, and the source-order check after out-of-sequence runs. |
| `kjv_lookup.py "<Book> <C>:<V>[-<V>]"` | KJV text of a verse or range (e.g. `"Psalms 118:8-9"`). The data is `kjv.sqlite` (table `bible_kjv`, `book` lowercase without spaces, `txt_location = chapter*1000000 + verse`), which the audit also reads. The import prompt tells the piece agents to use this lookup. |

**Many short chapters:** `WORKS[…]["pack_chars"]` makes the Jerome importer pack whole chapters
greedily into pieces up to that size (`Part001_Ch01-03.html`) instead of one piece per chapter
(Hebrew Questions on Genesis: 46 pieces → 12 at 15000). `WORKS[…]["lemma_formula"]` (a regex) lets
the audit's lemma check and `boundaries` accept a lead-in before the italic lemma ("Then there
follows <i>…</i>").

**Chapter-headed works:** when the `<h2>` headings are chapters and each paragraph opens with its
own lemma (Matthew, Jeremiah), set `chapter_re` and `lemma_paragraphs` in `WORKS`. Rules 3 and 4 then
apply per paragraph, and `audit --headings` lists every paragraph's guessed verse ("LOW" = weak match).
A chapter is one section, so it is never cut: a long chapter makes one big piece (Jeremiah 31, 53k
chars, imported cleanly). The guesses are weak where a lemma quotes a long passage, so expect OUTSIDE
HEADING flags there.

**Other fathers and other layouts:** `process_jerome_commentary.py` hard-codes `FATHER = "Jerome"`
and assumes the `<h2>` layout above. For another father or work, copy the closest existing importer
(table below) to `scripts/process_<father>[_<work>]_commentary.py`, change `FATHER`, the units/logs
folder prefix, the prompt wording and `WORKS`, and keep the two-prompt flow and `--check`. The audit
and `import_checks.py` load every `process_*_commentary.py` and use the one whose `WORKS` has the
work key, so a key must not be in two importers (Ambrosiaster's are `AmbGal` etc., because Jerome's
importer has `Galatians`). Keep the copy's paths relative to the skill folder, so it works on any
checkout. Another work of a father who already has an importer usually goes into that importer as
a new `WORKS` entry (a `"kind"` can pick work-specific prompt wording); compare an earlier work's
parsed bodies and `--dry-run` prompt before and after any change to shared code.

A different source layout is handled in the copy's `load_work`, which returns one section per
lemma or unit: `heading` (its verse label or unit name, an audit hint), `html` (the raw text the
agent sees, labels and notes included as hints) and `body` (the text that is imported and checked).
Then pieces, prompts, `--check`, the audit and `import_checks.py` all work unchanged.

**Models by layout** (all in `scripts/`; `RUNS.md` has an account of each run, if this checkout
has one — see [Run history](#run-history)):

| Layout | Importer to copy (keys) |
|---|---|
| Verse sections under `<h2>`, Hebrew lemma then `LXX:` | `process_jerome_commentary.py` |
| Bold verse labels inside chapters; text before the first label is a preface | `process_berengaudus_commentary.py` |
| Verse labels at paragraph starts, `7:36-50. <i>…</i>` / `(1 Cor. 1:1) <i>…</i>` | `process_cyril_commentary.py`; `process_ambrosiaster_commentary.py` (`Amb1Cor` … `AmbPhil`: a new epistle is just a `WORKS` entry) |
| Bare verse numbers mid-sentence | `process_theodoret_commentary.py` (`label_sections`) |
| Numbered propositions with no verse labels (verse guessed as a hint) | `process_augustine_romans_commentary.py` (`intro_lemmas`) |
| Homily series, one file per sermon, no lemmas | `process_augustine_commentary.py` (Tractates, `"homily": True`), `process_jerome_psalms_commentary.py`, `process_basil_hexaemeron_commentary.py` |
| Homily series in ONE file, `<h3>` chapters, one section per chapter (`cont` for a homily's later chapters) | `process_ambrose_hexameron_commentary.py` |
| One file per psalm, long psalms cut into pieces | `process_augustine_psalms_commentary.py` |
| Selective, chapters under `<h2>` (with or without summary lines) | `process_cassian_commentary.py` (the original), `process_damascene_commentary.py`, `process_novatian_commentary.py`, `process_basil_spirit_commentary.py`, `process_augustine_grace_commentary.py`, `process_isaac_commentary.py` |
| Selective, one file per book, chapters/sections numbered at paragraph starts | `process_salvian_commentary.py`, `process_augustine_harmony_commentary.py`, `process_eusebius_history_commentary.py` |
| Selective, bold chapter headings and a printed apparatus to drop | `process_eusebius_commentary.py` |
| Questions and answers | `process_basil_commentary.py` |
| Letters, one file per letter | `process_athanasius_commentary.py`; many short letters packed into pieces: `process_basil_letters_commentary.py`; sermons packed likewise: `process_leo_commentary.py` |
| Several works in one file sharing one url | `process_aphrahat_commentary.py` (`block_is_mine`) |

**Lessons from earlier runs.** Each of these cost a run something once; check for them up front.

*Locating the work*
- A work in a subfolder keeps `%2F` between segments (Jerome's `source_url_for` would give
  `%252F`); a father folder with spaces is double-encoded too (`Cyril%2520of%2520Alexandria`, as
  `process_cyril_commentary.py` does). Compare the result with the old blocks' url before deleting.
- A work split over many Writings-Database files: with the user's OK, merge it into one
  standard-format file first (renumber the footnotes 1..k, check the visible text is the inputs
  joined), so the import has one url and one `WORKS` entry.
- Fix source errors in the Writings-Database with the user's OK; commit there only when the user
  approves.

*Proofreading the source (Phase 1, before anything is imported)*
- An OCR'd source with an authoritative transcription (CCEL's NPNF pages): word-diff against it
  (tokenise both, `difflib`, map each difference back to an html offset so a fix keeps the file's
  markup). Strip CCEL's `<span class="pb">` first and reject CCEL's page-break word splits and own
  typos. Review every difference, stage the fixes in the scratchpad, re-diff, then write them with
  the user's OK.
- With no transcription, diff against archive.org scans of the print (drop running headers and
  hyphenated line ends; long scan-only runs are footnotes), then a second pass against the CLEANER
  scan alone, since a noisy scan shares the source's misreads. Where every scan agrees with the
  source, it is the printer's own misprint: keep it. A pattern sweep (shall/shalt, hut, arc, "1"
  for "I") finds what the diff misses.
- With neither, two read-only subagents proofread half the text each (exact unique snippet,
  correction, confidence); check each finding in context.
- A word diff can't see punctuation: dashes typed as single hyphens and quotes on the wrong side of
  their space need a character-level alignment against CCEL, and a lost paragraph break shows up
  only at `--check`.
- A fresh translation: compare it with its Latin section by section (note markers, length ratio,
  notes' references), then two read-only subagents proofread half each against the Latin for
  substantive errors.
- Footnotes: check that markers and notes pair 1..n, and that each note's reference matches the
  words before its marker (score at shift 0 and ±1..6, per file and per run of ten markers; a
  one-note swap doesn't move the score, so compare with an authoritative copy as well). CCEL swaps
  notes too: read the text before a marker before moving its note. The low scorers are often the
  editor's misprinted references; name each in the notes.
- Repeated note references carry their own ids (`id="r18-2"`): make sure the marker regex catches
  them, and compare the body with the visible text using a LOOSER regex than the importer's (the
  reassembly check uses the importer's own and can't see this).
- Greek: check `unicodedata.is_normalized`. Oxia forms (U+1F73) get retyped as tonos (U+03AD); the
  importers' `_norm` NFC-normalizes both sides of the check.
- An unconverted Pearse page: the Writings-Database's `standardization/pearse_transform.py --file …
  --dry-run` says why it failed closed.

*Making the body match what the agents write*
- Editorial matter (translator's introductions, provenance notes, rubrics, colophons, page marks,
  margin references, the editors' apparatus) goes in `strip` or in `load_work`'s paragraph drops;
  make each rule refuse to run if it matches nothing, and list every source paragraph absent from
  the bodies to confirm nothing else was lost. The translator's bracketed supplements stay.
- A removed mark leaves a space the agents rightly don't copy (after an opening quote or a
  paragraph start, before closing punctuation, a dash or " )", after a hyphen), or glues words
  (`Christ.<sup>39</sup>And`). Replace each removed mark with a placeholder and settle the spacing
  (`make_body`/`_settle` in `process_eusebius_commentary.py`; `MARK_BEFORE_PAREN_RE`,
  `MARK_AFTER_OPEN_QUOTE_RE`, `GLUED_REF_RE` in later importers). Strip unlinked `<sup>` marks
  case-insensitively; mend broken markup (`<sup> </sup>`, an unclosed `<i>`) with `FIXUPS` or in
  the source.
- Chapter summaries and the editor's chapter titles are cut from the body and shown in the `<h2>`
  the agent sees, or every block crossing them fails the check. Irregular ones (split italic runs,
  no italics, a last word outside the italics, running into italic text) each need handling: list
  the chapters whose opening doesn't fit the pattern, and make `load_work` refuse a chapter with no
  summary.
- Section and paragraph numbers are dropped from body and pieces; `load_work` requires them to run
  1..n (with an explicit list of exceptions), so a misprint or a lost heading surfaces. Bare numbers
  mid-sentence: cut only at a number continuing the chapter's sequence (prev < v <= prev+5), after
  surveying each chapter for misprints and numbers glued to the word before.
- NOT VERBATIM often means the agent silently mended source debris or dropped an inline editorial
  mark. Diff the block against the body at the divergence: fix the source (or `strip`) when the
  agent was right, the block when it copied a misprint. After any source or `load_work` change,
  re-run `--check` on everything already imported.

*Pieces and prompts*
- Pack consecutive units greedily up to the cap (an even split leaves stray tiny pieces); a unit
  over the cap stands alone (chapters of 50–68k imported fine). Use a cap of ~25k where most of the
  text is imported into several files. Truncate very long editors' notes in the hints.
- Changing `load_work` after the pilot can move piece boundaries: re-run `--dry-run` for every
  work, and run what the pilot didn't cover by explicit piece or chapter range.
- Psalm numbering differs by translator and even within one work (Latin, Hebrew, the title counted
  as verse 1, misprints). Name every non-KJV reference in the notes, with its wording, and tell the
  agents to place by wording; likewise Latin-numbered Sirach, Baruch, Jonah, and Greek Esther
  (KJV Apocrypha numbering, which `kjv.sqlite`'s `esther,greek` doesn't follow).
- Labels that follow the Latin verse division: list every section that opens with the previous
  verse's end, runs on into an unlabelled verse, or runs ahead; the pilot agents often find more,
  so add them to the notes before the rest runs.
- `import_checks.py … notes` reads every text between two `"` as a quotation, prose between
  quotations included; with many quotations check the PAIRED ones
  (`re.findall(r'"([^"]+)"', notes)`) against the body instead.

*Reviewing the output*
- Agents name Psalm files `Psalm 69_28` and open new files with a blank line; `--check` flags
  both. Rename with `mv`, since `git mv -k` silently skips untracked files.
- Pilots leave files out of source order: `--order` / `--fix-order BASE` (only this work's appended
  blocks move; old blocks stay first). The per-book order check can't see a file shared by
  several BOOKS of one work: check (book, chapter) order across the work's urls.
- Cross-psalm parallels count as the book's own files, so for psalm works check coverage and
  duplicates per psalm by its OWN files, and that no OUTSIDE HEADING block lies inside the
  homily's own psalm.
- A big block where the father dwells on one verse: compare its opening with the next verse's
  first quotation before calling it under-split.
- In selective runs the agents are generous (one stretch under several verses, thin one-sentence
  blocks); that has been kept unless the user decided otherwise. One exposition copied whole under
  each verse of one passage is a scope slip: merge it into a range file.

*Old blocks*
- They come as this url, `#anchor` variants, newadvent urls (often the same translation), Google
  Books urls, and url-less ACCS excerpts under many title spellings, some untitled, some
  OCR-garbled, some under the work's volume title (FC's *Exegetic Homilies* for the Hexaemeron),
  plus strays by other authors misfiled under the father. Survey every title form, and search the
  url-less text for the work's name.
- Identify each excerpt by its text, not its title: a rarity-weighted word overlap (windowed for
  long works) against every section of the father's works, then read the low scorers and every
  title/text disagreement. Different translations score low, and unrelated passages 0.3–0.5, so for
  loose paraphrases let the filing book or read-only judges decide. For an abridged edition, judge
  SAME / PARTIAL / ABSENT and keep excerpts of passages the edition lacks; keep excerpts of
  untranslated parts and of other works.
- Delete by url, `--title-prefix`, `--titles-file` (exact titles: one may be a prefix of
  another; check no excerpt of another work shares one) or `--file-prefix` (a title shared by two
  works); an untitled block by hand, after checking the file. Bring every stray to the user.
- After the import, compare the old verse RANGES with the new blocks' parsed ranges (not
  filenames); have read-only subagents judge the misses (genuine / covered / passing), bring the
  genuine ones to the user, add them from the source (check the end punctuation), then
  `--fix-order`.

**Selective works** (treatises, dialogues, sermons and letters with no verse sections; first done
for John Cassian's *Conferences*). With the user's approval (ask in Phase 0) they are imported
**selectively**: the agents read every section and file only the stretches that comment on a
verse, under rule 13; everything else is left out on purpose.
- Mark the work's `WORKS` entry `"selective": True`, `"book": None`. `load_work` returns one
  section per chapter (or whatever unit the source has), with `chapter` None and a `chapter_no`,
  and `make_units` packs runs of whole chapters into pieces up to `SPLIT_CHARS`.
- A work whose parts are separate files with their own urls gets one `WORKS` entry per file; a
  dedicatory preface file gets none (rule 6), nor does an untranslated part.
- **source_title** carries the unit: `"<work title>, Chapter N"`, or `"Chapters N-M"` for a block
  crossing chapters (ask the user the form in Phase 0). `--check` and the audit check it against
  the chapter(s) the text really comes from.
- **Editors' footnotes** that give Scripture references are the best placement hints there are:
  `load_work` puts them inline in the pieces as `<sup>[note: …]</sup>` and drops them from the
  body, so a block that copies one fails the check. Check that they line up with their markers in
  Phase 1 (see *Proofreading the source*), and fix misalignments in the source, not by mapping in
  the importer.
- Phase 0 questions for the user, beyond "selective?": which parts to skip (letters written TO the
  father, untranslated or duplicate parts, an editor's introduction), the title form, and, for a
  history or anthology, whether documents the father quotes are imported.
- **Checks:** there is no coverage, lemma or placement check. `--check` and `audit … <BASE>
  <pieces>|--all` (which branches to `selective_main` for these works) test that every block is
  one verbatim stretch found once, its source_title, no two overlapping blocks of the work in one
  file, append-only, and print the same text filed under several verses (allowed, rule 13),
  overlapping texts in different files, wide ranges, small blocks and a per-chapter LAYOUT.
  `audit … --headings` lists the chapters with their sizes and footnoted references.
- The prompt asks each agent to end with a list of the blocks it wrote and of the expositions it
  considered and left out, with the reason: read those lists when reviewing, since no GAP check
  can tell you what was missed. Most misses in the old-excerpt comparison turn out to be on those
  lists (chains of proof-texts, a verse used as one instance within the exposition of another).

**Gotchas with the tools**
- Every run deletes the units folder at the end (even a single piece). Only a run that reaches the
  LAST piece runs `--check` by itself; otherwise run `--check` yourself.
- `--start-after A --through B` runs everything between A and B. If pilot pieces sit in that
  range, chain several ranges with `&&` so they aren't run twice.
- The audit's "files added or changed since BASE" counts only tracked (pre-existing) files. New
  files are untracked and don't appear there.
- In zsh an unquoted `$VAR` holding several piece names is passed as ONE argument. Write the names
  out, or use `${=VAR}`. The same goes for a command held in a variable (`P="python3 …"; $P
  Part001…` fails with "no such file or directory"): write the commands out.
- The audit's lemma detector knows Jerome's layouts (a Hebrew lemma then an LXX one, introduced
  by "LXX:" or by a phrase, in parentheses, with inline alternatives, or with a half-verse first
  paragraph), a formula before the lemma (`intro_lemmas`) and bold lemma paragraphs
  (`bold_lemmas`). For a new layout, confirm that it finds every lemma before trusting LEMMA CUT,
  and extend it if needed; then make sure the earlier works' results don't change, except for
  improvements.
- Editorial marks the user wants left out of the import (Migne brackets, edition section numbers)
  go in `WORKS[…]["strip"]`: a list of regexes that `load_work` removes from the sections (not the
  preamble), so the pieces, `--check`, the audit and `import_checks.py` all see the same text. Say
  in the notes that the full source html still has them.
- Never re-serialize TOML files with rtoml or tomlkit. Edit the text and verify by re-parsing.
- **Concurrent imports:** another session may be importing a different work into the same father
  folder at the same time. Then `git status`, the audit's changed-file list, and a pilot rollback
  will include that session's files too. Scope everything by this work's source_url, and never
  roll back with a blanket checkout or delete of untracked files without checking which work each
  file belongs to. Both sessions also edit `WORKS` in the same importer file, so edit only your
  own entry and don't revert the other's.
  **Assume the user has other imports running, and commit only your own changes, at the
  appropriate times** (the deletion commit at the end of Phase 2, the import commit in Phase 6).
  Stage by an explicit list of paths (`git add --pathspec-from-file=<list>`), never with
  `git add -A`/`-u`/`.` on the father folder or a directory, which would sweep in the other
  session's deletions and appends. A shell glob (`"<Father>/<Book> "*`) doesn't match deleted
  files, so build the deletion's list from the dry run's file list. Before each commit, read
  `git diff --cached --stat` and check that every staged path is yours. A shared file (a
  cross-reference appended to a file the other session also writes to) goes in only if all
  of its changes since HEAD are this work's blocks.

## 3. Standing rules (approved by the user)

1. **The agent decides placement, not the script.** The Python driver only cuts the source and
   passes hints (headings, numbering notes) to the piece agents; the agents choose the KJV verse
   file for each stretch. Never precompute a section-to-file table in Python: headings can be
   off, and judging placement is the whole point of using an agent. Give known numbering quirks
   to the agents as prose in the notes. Deterministic checks afterwards are welcome, but they
   check coverage and format, not exact placement. The prompt pushes toward the SMALLEST verse
   ranges; never add wording that lets the agents default to the source's own section ranges.
2. **Placement by commentary, not lemma.** File every block under the verse(s) its COMMENTARY
   addresses. A lemma quoting several verses never widens a block's range. The user put it this
   way: "We are interested in the commentary, not so much the lemma."
   - If the exposition after a lemma covers only its first verse, the first block (lemma
     included, uncut) goes under that verse (Jerome's "9:14ff." quoting Isaiah 9:14-21 →
     `Isaiah 9_14`).
   - If the comment starts on a later verse (e.g. the lemma opens with a bare formula verse,
     "And the word of the Lord came to me, saying:"), the first block starts its range there.
3. **Lemmas stay whole.** Each section's lemma (Hebrew version AND LXX version, plus any remarks
   inside the LXX parenthesis) stays uncut at the start of the section's first block, and every
   section's first block starts exactly at the section start. Agents sometimes join the end of one
   section to the next section's lemma when both are the same verse. Fix that mechanically by
   splitting at the section start and keeping both blocks in the same file. If the editors'
   section break falls mid-sentence, the tail stays with its own section anyway.
4. **Smaller is better, but no fragments.** Split by verse where the text really moves verse by
   verse. Keep a range when a pass sweeps the verses as one argument (Jerome usually expounds a
   lemma twice: historically, then spiritually). Overlapping ranges are fine when one sentence
   crosses a verse boundary; no text is ever duplicated within the book.
5. **Prologue:** first block of `<Book> 1_1`, before the 1:1 commentary, appended after any
   existing blocks (e.g. Jerome's separate Vulgate "Prologue to <Book>" from the Biblical Prefaces
   stays first). The whole prologue goes in, even if it discusses a later verse: it introduces the
   work as a whole, so a reader opening the first verse should see it there. Scribal rubrics
   ("HERE BEGINS THE BOOK.") are left out.
6. **Book prefaces** (multi-book works):
   - A substantive one gets its own block under the verse(s) it explains, which can be in another
     book, and it can come after that verse's commentary. Galatians' Book Two preface ("senseless
     Galatians") went in as the second block of `Galatians 3_1`, Isaiah's Book Sixteen preface to
     Romans 3_13-18, and Ezekiel's Book Eleven ("This Gog is the Goth") to Ezekiel 38_2.
   - A dedicatory or autobiographical one is skipped, even if it quotes Scripture in passing
     (Galatians Book Three, on Jerome's style, eyesight and dictation). Autobiography filed under a
     verse would mislead that verse's readers. An empty heading has nothing to import.
   - You read every preface yourself and bring the user a table, because the user decides case
     by case. The decisions then go into the notes as fixed instructions, so the piece agents
     don't judge them.
7. **Closing notes** to a patron (at the end of the work or of a book) are cut, as are notes closing
   a book, e.g. Ezekiel's end of Book Eleven: "Thus far we have spoken…". Short transitional
   sentences ("let us pass on to…", "We have touched briefly on the obvious things…") are kept.
8. **Cross-references** stay on: a stretch that genuinely QUOTES AND EXPOUNDS another book's verse
   is also filed under that verse, in addition to its own placement. Passing proof-texts are not
   cross-filed. Check every Psalm cross-reference's number and verse against the KJV wording,
   because Jerome uses the Latin numbering, often with the Hebrew number in brackets or parentheses.
9. **Append-only:** pre-existing files only get blocks appended. A "-1 line" diff where the old text
   is still a prefix is just a file that lacked a final newline.
10. **Source order:** within a file, this work's blocks follow the source's order. Pieces run out of
    sequence (pilots) can break this. Run `import_checks.py <Work> order` and reorder by cutting the
    file text, only in files that are new since BASE.
11. **Verbatim.** Copy the translation exactly: Origenian signs (÷ ※ ⁚), Greek, transliterated
    Hebrew with its bracketed or parenthesized glosses, quotation marks, dashes, and odd punctuation
    as printed. Drop html tags (italics become plain text, not quotation marks). Drop the
    translator's note, the `<h2>` headings, manuscript rubrics ("HERE BEGINS THE BOOK."), and the
    editors' inline sub-lemma labels like "19 d.". Separate paragraphs with a blank line.
12. **Commits** (Commentaries-Database, directly on `master`, never pushed by you):
    - one commit for the deletion: `remove old <father> on <book> import (ahead of fresh translation, #N)`;
    - ONE commit for the whole import at the end: `<father> on <book>: import fresh translation (#N)`;
    - only if the run changed this file (a standing rule, a tool's documented behaviour, or a
      general lesson; see Phase 7), one commit for that: `fresh-import: <what changed>`. A
      routine run makes no skill commit: its record goes in the gitignored `RUNS.md`, and the
      `WORKS` entry and tool changes in `scripts/` are gitignored too.
    - With no issue, leave out ` (#N)` / `, #N`.
    - In the default autonomous mode, make the deletion, import and skill commits yourself; in
      checkpoint mode, ask before the import commit and any skill commit, because the user
      sometimes makes them (and pushes) themselves. Either way, check `git log` first that the
      user hasn't already made one. Never commit in the Writings-Database.
13. **What to import from a selective work** (§2, "Selective works"; the user chose this
    threshold for Cassian's *Conferences*). Import a stretch when the father quotes or plainly
    refers to a specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its
    words (literally, morally or spiritually), resolves a difficulty in it, applies a figure in
    it, builds the argument on its wording, or APPLIES it to the spiritual or monastic life in a
    way that shows how he reads it (a verse brought in to describe a stage of prayer, a vice or
    its remedy, and then drawn out). Leave out a verse quoted in passing, a bare proof-text, a
    chain of proof-texts without comment, and narrative or teaching that merely mentions
    Scripture. The test: would a reader studying this verse learn something about how the father
    understood or used it? Each block is one continuous verbatim stretch, from sentence boundary
    to sentence boundary, able to stand alone (with the question it answers, in a dialogue, when
    needed), under the smallest verse range its exposition addresses. The same stretch may be
    filed under two verses when it really expounds both (the project `CLAUDE.md` welcomes this),
    but never two overlapping blocks of the work in one file.

## 4. The process

### Run modes

**Autonomous (the default).** Unless the user asks for checkpoints, run the whole job yourself:
prep, the deletion and its commit, the pilot, and, if the pilot is clean, the rest of the work,
then the final review, the import commit, the issue's closing and the run record. A ⏸ is then
not a stop: post a short status there and go on. Stop and ask only:
- where a step says to stop and ask (Phase 0: a path or url that can't be resolved, a checkout
  that is behind and not clean, a work that isn't verse-by-verse, an existing `WORKS` entry or
  an earlier fresh import);
- for the decisions that belong to the user: which book prefaces and closing notes to keep or
  skip (rules 6 and 7; a prologue alone needs no decision, rule 5), old blocks whose identity is
  unclear (strays filed under the father, possible excerpts of another work, out-of-book blocks
  you can't match to this work's text), a fix to the Writings-Database source, and a change to a
  standing rule;
- when the pilot or a chunk isn't clean.

Ask everything you need in one go, with the facts the user needs to decide, then carry on
autonomously after the answer.

**Clean** means: no piece aborted; after mechanical fixes (§6) the audit has no NOT VERBATIM,
MULTI-MATCH, OVERLAP, LEMMA, LEMMA CUT or NOT APPEND-ONLY entry; every coverage gap is an
intended skip; every PLACEMENT? and OUTSIDE HEADING flag checks out against the KJV wording; and
the run summaries raise nothing the notes didn't foresee. If a pilot shows only that the notes
need a sharper instruction, roll it back (Phase 3), amend the notes and run the pilot again; stop
and ask if the second pilot isn't clean either.

The run ends with one report: the Phase 5 summary, the commits, and the issue's closing comment.

**Checkpoints (when the user asks for them,** e.g. "with checkpoints", "stop at each stage", "let
me review each step"). Stop and wait for the user at every ⏸, ask before the import commit and
any skill commit (rule 12), and ask (with AskUserQuestion) whether the user or you runs the pilot
and each chunk.

In either mode, start every ⏸ message with where you are and what comes next, e.g.
"**Phase 2 (deletion) done, BASE = abc1234. Next: Phase 3 (pilot).**", so the run can resume
cleanly after a pause or a context summary.

### Phase 0: Resolve the work (no changes anywhere)

1. **Turn the argument into a local html file** in the Writings-Database checkout (see
   Prerequisites for where that is; if it can't be found, ask the user):
   - **Local path:** use it as given. It must be inside the Writings-Database; if it isn't, stop
     and ask the user where it should go there.
   - **historicalchristian.faith url** (`by_father.php?file=…`): url-decode the `file` parameter
     until no `%` escapes remain (the segments after the father folder are double-encoded) and
     join it onto the Writings-Database root, as the project `CLAUDE.md` describes.
   - **GitHub url** of `HistoricalChristianFaith/Writings-Database` (`…/blob/<branch>/…` or
     `raw.githubusercontent.com/…/<branch>/…`): take the path after the branch and url-decode it.
   - **Any other url:** stop and ask the user. Don't download it into the Writings-Database
     yourself.
2. **Make sure the local file is current.** If the file is missing, or a GitHub url was given,
   run `git -C <Writings-Database> fetch` and compare with the upstream branch. If the local copy
   is behind and its working tree is clean, `git pull --ff-only`; otherwise stop and tell the user
   what's different.
3. **Gather the work's facts** and show them to the user in one short block:
   - father (the top folder), work title (the `<h1>`), the KJV book it comments on (a name from
     `book_names.json`), and the `WORKS` key (the book name, as in the existing entries);
   - the source_url, built exactly the way `source_url_for()` in the importer builds it;
   - size and `<h2>` section count;
   - the importer: `process_jerome_commentary.py` for Jerome, or a per-father copy (§2, "Other
     fathers");
   - whether the work is a verse-by-verse commentary at all. If it isn't (a treatise, dialogue
     or sermons with no verse sections), stop and ask the user whether to import it selectively
     (§2, "Selective works"; rule 13), and which old blocks to delete;
   - whether a `WORKS` entry already exists, and whether
     `git log --oneline -i --grep "on <book>: import fresh translation"` finds an earlier fresh
     import (if either does, stop and ask the user before going on);
   - **the GitHub issue:** `gh issue list --repo HistoricalChristianFaith/Commentaries-Database
     --state open --search "<Father> <Book>"`. If one clearly matches, its number is `#N`. If none
     does, say so; the commits then leave out the number and Phase 6 skips closing the issue.
4. **Read:** the scripts in §2, and the `WORKS` entries of the earlier works closest to this one
   (similar size and structure; the *Models by layout* table in §2 names them), which are the
   models for the notes. If `RUNS.md` exists, read those works' entries in it: they record the
   source fixes, the user's decisions, and what went wrong. For those works,
   `git log --oneline -i --grep "<book>.*fresh translation"` gives the deletion and import
   commits, and the closed issue's closing comment (`gh issue view N --comments`) summarizes the
   run and the user's review decisions.

### Phase 1: Prep (no database changes)

1. **Survey the source.**
   - Size, section count, the non-verse sections and their lengths, heading formats (a/b/c
     half-verse markers, "ff.", commas, cross-chapter ranges), lemma layout, Psalm numbering,
     footnotes/`<sup>`/notes sections, and inline editor references like "(Matt 7:7)".
   - Compare with the translator's note.
   - `python3 scripts/process_jerome_commentary.py <Work> --dry-run` prints the pieces once a
     `WORKS` entry exists. Add a skeleton entry (html, book, source_title, empty notes) first.
2. **Check the headings.**
   - Run `audit_jerome_import.py <Work> --headings` and `import_checks.py <Work> continuity`.
   - The "lemma opens like" flags are noisy, because part-verse lemmas look like the previous
     verse. Check every flag, and every discontinuity, by reading the lemma against the KJV.
   - Known kinds of problems:
     - editors' references off by a verse (Isaiah, about 7%);
     - Vulgate chapter starts that differ from the KJV (Ezekiel "2:1b" = KJV 1:28, Haggai ch. 2
       one verse ahead);
     - a heading that skips the second half of a verse (Ezekiel "11:2b-12" starts at 11:1b);
     - Hebrew-vs-KJV chapter divisions (Joel 2:28-32 = Hebrew 3:1-5; Ezekiel 20:45-49 = Hebrew
       21:1-5). Settle which numbering the headings follow.
3. **Check the piece boundaries.**
   - `import_checks.py <Work> boundaries` lists lemma-only sections, sections that don't open with
     italics, and the opening of every piece.
   - If a piece starts mid-lemma (Isaiah: "13:18ff." held only a lemma's start and "14:1" opened
     with its end), write a specific note telling the next piece where to append. Merge the two
     blocks yourself afterwards.
4. **Read every non-verse section** (prologue, book prefaces) and **the end of every book** (closing
   notes). Draft a table: book · what it precedes · size · content · recommendation (skip / keep →
   file).
5. **Survey the old blocks.**
   - Run `delete_commentaries.py <Father> "<url>" --dry-run` and, if needed,
     `delete_commentaries.py <Father> "" --title-prefix "COMMENTARY ON <BOOK>" --dry-run`.
   - Search all blocks for the book's name in source_url and source_title, to catch anchor and
     title variants.
   - List the old blocks outside the book's own files, with their opening words.
   - Compute the combined after-state: blocks, files touched, files emptied (= removed), and files
     that keep blocks from other works (list them).
   - Note what `<Book> 1_1` will hold afterwards.
6. **Write `WORKS["<Work>"]["notes"]`.** Model them on the closest earlier entries (Ezekiel's and
   Joel's are thorough). Cover:
   - **numbering:** headings are hints, with the concrete off-heading examples from step 2;
     a/b/c means the whole verse; how cross-chapter ranges are written (`Ezekiel 1_27-2_1`);
   - **lemma layout:** exactly how this work marks the Hebrew and LXX lemmas, the irregular
     lemmas by heading, and "every section starts its own block; never join sections";
   - **verbatim specifics:** the signs, glosses, quotation marks and dashes this work has;
     "most sections are one long paragraph, so cut between sentences" if true;
   - **Psalm numbering**, and "match a Psalm cross-reference's verse by its wording";
   - **rule 2**, with an example in this book's headings, and the double historical/spiritual
     pass with "don't fragment";
   - **"Earlier pieces of THIS run"** will have left blocks of this work in the files: leave them
     and append. Name the files that hold other works' blocks, if useful;
   - **the prologue's placement** in `<Book> 1_1` (what's already there, what goes after);
   - **the fixed decisions:** each preface and each closing note (quote its first and last words
     so the agent can find the cut), plus any piece-boundary merge instructions.

   Quote source text exactly, then run `import_checks.py <Work> notes`. Any quoted fragment it
   can't find is either a paraphrase that shouldn't be in quotation marks or a typo.
7. `--dry-run` again (read the full first prompt), then `--split-only`, then
   `import_checks.py <Work> pieces` (the written pieces must reassemble into the source). Then
   delete `work/jerome_<work>_units/`.
8. **⏸ Show the user:** the preface/closing-note table with recommendations, a summary of the
   notes, the heading findings, and the deletion dry runs with the combined after-state, including
   the old cross-references outside the book. In autonomous mode this is a status, not a stop,
   unless the table has prefaces or closing notes to decide or the old blocks have strays (see
   [Run modes](#run-modes)).

### Phase 2: Deletion

Run the deletion(s) for real, then verify:
- every file still parses;
- no targeted block remains anywhere;
- each trimmed file holds exactly its other blocks, unchanged (compare the parsed blocks with
  `git show HEAD:<path>` minus the deleted ones).

Commit only the deleted/trimmed `<Father>/` files, staged by an explicit path list (see
*Concurrent imports*), with the deletion message (never with edits to this skill). That commit
is **BASE** for every audit.

### Phase 3: Pilot

Choose 2–6 pieces that exercise the risky parts:
- Part001 (the prologue and the `<Book> 1_1` placement);
- a piece with half-verse or off headings;
- one with a substantive preface;
- one around a numbering boundary;
- one with a closing note;
- the last piece.

Name the pilot pieces, each with the risk it exercises, and one command per piece, run from the
Commentaries-Database root, e.g.
`python3 .claude/skills/fresh-import/scripts/process_jerome_commentary.py <Work> Part003_Ch02.html`.

**Run them yourself,** in the order given, chained with `&&` in ONE background Bash call
(`run_in_background`), so a failed piece stops the rest. Each piece takes minutes, beyond the
foreground timeout. Send the output to a log in your scratchpad, not into your context. Wait for
the completion notification; don't poll. Then check the tail of that log for an `ABORTING` line
before reviewing. (In checkpoint mode, first ask the user with AskUserQuestion whether they run
it in their own terminal instead; if so, wait until they say it's done.)

**⏸ After the pilot:**
- `audit_jerome_import.py <Work> <BASE> <pilot pieces…>`.
- Read every run summary (prompt 1 and prompt 2) in the `run-*.jsonl` logs.
- Check every PLACEMENT? flag (see [Reviewing](#5-reviewing-a-batch)).
- Fix mechanical problems in place.
- If the pilot is clean (see [Run modes](#run-modes)), go straight on to the rest of the work in
  autonomous mode. Otherwise, or in checkpoint mode, bring the user the judgment calls.

If the notes need changing, the pilot can be rolled back cleanly, because everything of this work
after BASE is pilot output. Restore the pre-existing files that hold this work's url from BASE, and
delete the new files that hold only this work's blocks. Check each file first (see *Concurrent
imports* above).

### Phase 4: Chunks

- **Size:** 20–35 pieces per chunk with `--start-after/--through`, run by you as one background
  Bash call, the same way as the pilot (or by the user, if they choose so in checkpoint mode).
  Chain ranges around the pilot pieces, e.g. `Part002` alone, then
  `--start-after Part003 --through Part028`.
- **⏸ After each chunk:**
  - Audit the chunk's pieces.
  - Have a read-only subagent digest the run logs' summaries. The prompt is in
    [Reviewing](#5-reviewing-a-batch); don't read the `.events.jsonl` files into your own context.
  - Run `import_checks.py <Work> order`.
  - Fix mechanical problems (see [Mechanical fixes](#6-mechanical-fixes)).
  - If the chunk is clean, go on to the next one in autonomous mode; otherwise, or in checkpoint
    mode, bring the user the judgment calls.
- **Once a chunk comes back clean,** the rest can go in one chained command.

Small works (Obadiah, Joel, Haggai: 1–6 pieces) need no chunk loop: a pilot of 2 pieces, then
everything else in one command. A run that ends on the last piece runs `--check` by itself.

### Phase 5: Final review

1. `process_jerome_commentary.py <Work> --check`. Expected failures:
   - the skipped prefaces (start and end probes);
   - the cut closing notes (end probe);
   - the dropped editors' labels like "19 d." (start probe);
   - a preface filed under another book (it's checked only in the book's own files).

   Anything else is a real problem.
2. `audit_jerome_import.py <Work> <BASE> --all`, then:
   - **coverage gaps:** account for every gap (it should only be the intended skips);
   - **flags:** check every PLACEMENT? and OUTSIDE HEADING flag against the KJV wording;
   - **problems list:** confirm there is no NOT VERBATIM, MULTI-MATCH, OVERLAP, LEMMA, LEMMA CUT
     or NOT APPEND-ONLY entry;
   - **prologue:** confirm the `<Book> 1_1` block list is in the right order.
3. `import_checks.py <Work> order`, and spot-check the Psalm cross-references (number and verse
   by wording).
4. Counts for the closing comment: blocks and files in the book; cross-ref blocks and files; new
   vs appended files (`git status --porcelain --untracked-files=all -- <Father>`, and
   `git diff --stat BASE -- <Father>`, which should show only insertions).
5. **⏸ Summarize** for the user and include a draft of the closing comment. In autonomous mode,
   if the review is clean, go straight on to Phase 6 and make this summary part of the final
   report; if it isn't, stop here and ask.

### Phase 6: Finish

Commit the import (in checkpoint mode, only after approval; in either mode, not if the user has
already done it). Stage only this work's files: every new or changed `<Father>/` file since BASE
whose text holds this work's source_url, never another session's (see *Concurrent imports*):
write those paths to a list, check that every other block in each file is unchanged since HEAD,
and `git add --pathspec-from-file=<list>`.
If there is an issue, close it with
`gh issue close N --repo HistoricalChristianFaith/Commentaries-Database --comment "…"`.

The comment is ONE paragraph, in the style of #35, #36 and #37 (read them with `gh issue view N
--comments` as models). It:
- cites both commits;
- gives what was deleted (counts, the out-of-book old blocks, the url-less excerpts);
- gives what was imported (blocks across files, plus cross-references in files, with the notable
  cross-referenced verses and why);
- says where the prologue and kept prefaces went;
- says what was intentionally left out (skipped prefaces, closing notes);
- adds a sentence on lemma handling and heading quirks;
- ends "Blocks from other works in pre-existing files were kept unchanged."

### Phase 7: Record the run

The `WORKS` entry (with its final notes) is the record a later import will model itself on.
Then:

1. **Append the run's entry to `RUNS.md`** (create it from the header described in
   [Run history](#run-history) if this checkout has none). It is gitignored: no commit. Keep it to
   what a later run of a similar work would want (the list is in `RUNS.md`'s header); for a work
   that is just another entry in an existing importer, a short paragraph is enough.
2. **Edit `SKILL.md` only for what is general:** a new or changed standing rule (with the user's
   approval), a tool's changed behaviour (e.g. a new lemma layout in the audit's detector), a new
   row in *Models by layout* for a new importer, or a lesson any future run should check for (one
   to three lines under *Lessons from earlier runs*, with no counts or dates). Nothing about this
   run alone goes here.
3. If `SKILL.md` changed, make the skill commit (rule 12; in checkpoint mode, ask first).
   Otherwise there is nothing to commit. Then send the final report (see
   [Run modes](#run-modes)).

## Run history

`RUNS.md`, next to this file, is the history of the runs done on THIS machine: one entry per work
(source quirks and fixes, the user's decisions, pilot and run, counts, agent slips, old blocks
deleted and kept, the review's additions). It is gitignored so the skill stays short and the
commit log clean, which means a fresh checkout has none. It is reference, not instructions:
read the entries for works like the one at hand (Phase 0), and don't load it whole.

Without a `RUNS.md`, the history up to Ambrosiaster on Philippians is in git:
`git show 084de666:.claude/skills/fresh-import/SKILL.md` (§2, from "Other fathers" to "Gotchas
with the tools"). Start a new `RUNS.md` with a one-paragraph header saying what it is and what an
entry records, then append entries.

## 5. Reviewing a batch

**Reading the audit**
- **PLACEMENT? flags** are hints. In Ezekiel all 85 were correct placements, falling into three
  kinds:
  1. a bare formula verse skipped ("the word of the Lord came to me" → the block starts at the
     next verse);
  2. a part-verse lemma (it opens with the second half of a verse, so it looks like the previous
     one);
  3. rule 2: the first comment addresses a later verse (e.g. a textual note on 33:25-26 →
     `33_25-26`).

  Check each one by reading the lemma and the text after it against the KJV. A real misplacement
  is a lemma filed under a verse it doesn't quote and whose comment it doesn't contain.
- **OUTSIDE HEADING** is expected where you already know a heading is off (e.g. "2:1b" → `1_28`).
- **"wide range"** is fine for whole-passage summaries and sweeping passes (Ezekiel's "Now the
  whole vision is this…" → `1_4-28`). Read the block's opening to confirm.
- **"small block"** is fine when it's coherent. Merge only true fragments, and never across a
  section start.
- **GAP** lines must all be intended skips. A gap inside a verse section is a lost stretch, so
  re-import it as a block (in source order) or report it.

**Digesting the run logs** with a read-only subagent (`general-purpose`), prompt along these lines:

> Read-only. Read every record's full `output` in `<logs>` (JSON lines: unit, sections, prompt
> 1=import/2=double-check, output; or unit+error). Digest per piece only what a reviewer needs:
> errors or aborted pieces; anything prompt 2 found and fixed; every judgment call the agent flagged
> (placements to check, blocks under a verse other than the heading's, fragments, overlapping
> ranges, ordering problems in files); whether each Book preface was skipped or filed (and where);
> text deliberately left out; every cross-book file created or appended; any edit to pre-existing
> blocks of other works; any rename, move or delete of earlier pieces' files. Expected decisions:
> <list>. End with the top issues. Under ~1200 words.

Then verify the digest's top issues yourself before reporting them. In Ezekiel, for example, an
agent skipped an Esther 14:11 parallel "because the KJV lookup has no Esther 14". The reason was
wrong, but the call was right (a passing proof-text).

**Things that are NOT problems** (don't "fix" them):
- formula verses missing from filenames;
- overlapping ranges from sentences crossing verses, or from second passes;
- verses with no file because Jerome never comments on them separately;
- cross-ref excerpts ending at a semicolon where Jerome turns to a new point;
- a cross-ref filed as its own `Psalms 118_9` beside an existing `Psalms 118_8-9`.

## 6. Mechanical fixes

Always edit the file text, never re-serialize. Split a file into blocks at the lines matching
`^\[\[commentary\]\][ \t]*$`, rearrange or cut the block texts, re-join them, then parse the
result and assert it equals the intended list of blocks.

- **Two sections joined in one block:** split the quote at the section start into two blocks with
  identical source fields, both in the same file, in order.
- **Blocks out of source order** (pilot side-effect): reorder the block texts. Do this only in files
  that are new since BASE; in pre-existing files the old blocks must stay first.
- **A lemma-only block at a piece boundary:** merge it with its continuation (the quote texts are
  consecutive in the source, so join them with the source's separator) into the first file, and
  delete the continuation block.
- **A wrong source_url or source_title** on a block of this work: fix the string in place.
- Re-run the audit on the affected pieces after any fix.
