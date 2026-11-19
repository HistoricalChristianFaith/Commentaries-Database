# A new importer: other fathers, other layouts

Read this in Phase 0 when no existing importer fits the work: another father with no importer,
or a source layout none of the importers' `load_work` handles. (Another work of a father who
already has an importer, in a layout it handles, is just a new `WORKS` entry: see
`reference/works-keys.md`.) For a selective work read `reference/selective.md` as well.

## Other fathers

`process_jerome_commentary.py` hard-codes `FATHER = "Jerome"` and assumes the `<h2>` layout in
SKILL.md §1. For another father or work, copy the closest existing importer (*Models by layout*
below) to `scripts/process_<father>[_<work>]_commentary.py`, change `FATHER`, the units/logs
folder prefix, the prompt wording and `WORKS`, and keep the two-prompt flow and `--check`. The
audit and `import_checks.py` load every `process_*_commentary.py` and use the one whose `WORKS`
has the work key, so a key must not be in two importers (Ambrosiaster's are `AmbGal` etc.,
because Jerome's importer has `Galatians`). Keep the copy's paths relative to the skill folder,
so it works on any checkout. Another work of a father who already has an importer usually goes
into that importer as a new `WORKS` entry (a `"kind"` can pick work-specific prompt wording);
compare an earlier work's parsed bodies and `--dry-run` prompt before and after any change to
shared code.

**source_url:** `source_url_for()` must reproduce the old blocks' url exactly. A work in a
subfolder keeps `%2F` between segments (Jerome's `source_url_for` would give `%252F`); a father
folder with spaces is double-encoded too (`Cyril%2520of%2520Alexandria`, as
`process_cyril_commentary.py` does). Compare the result with the old blocks' url before deleting.

**`load_work`:** a different source layout is handled in the copy's `load_work`, which returns
one section per lemma or unit: `heading` (its verse label or unit name, an audit hint), `html`
(the raw text the agent sees, labels and notes included as hints) and `body` (the text that is
imported and checked). Then pieces, prompts, `--check`, the audit and `import_checks.py` all
work unchanged.

### Prompt 2 and the per-piece checks

Only `process_jerome_commentary.py` and its copies `process_ambrose_luke_commentary.py` and
`process_ambrose_psalms_commentary.py` run the per-piece checks and the targeted prompt 2 (`piece_review.py`, SKILL.md §2): copy one of those
when you can. Every other importer still sends
the old generic prompt 2, "Double check, was this fully imported properly?": no check records in
its logs, no BASE needed before the pilot, and no abort on HARD problems; review its batches with
the audit and the log digest (SKILL.md §5). To adopt `piece_review.py` in a copy:
`import piece_review` (it needs module-level `FATHER`, `PROJECT_DIR` and a work key the audit
finds); copy `check_piece()`, the new `process_unit`, `log_record(**extra)`, and the `--base` /
`--legacy-prompt2` / `--dry-run` parts of `main()` from Jerome's importer. Selective and homily
works need a different wording for the targeted review's cross-reference step ("verse of another
book" doesn't fit): pass it through `build_prompt2`. A new audit problem code must also be added
to `PROBLEM_CLASSES` in `piece_review.py` (an unknown code counts as SOFT, so it never aborts a
run). Audit hooks for it: `$AUDIT_SCOPE_JSON` (the audit dumps its scope there) and
`$FRESH_IMPORT_SPLIT_CHARS` (the importer's `--split-chars`, so piece names match).

**Prompt hygiene** (copy it from Jerome's prompt 1, TOOLS paragraph): the piece agents read the
piece with the Read tool (`cat` output is cut off at 25-30k chars), write with Write/Edit or a
QUOTED heredoc (`<<'EOF'`; an unquoted one expands `$` and backticks), and leave `SKILL.md` and
`RUNS.md` alone.

## Models by layout

All in `scripts/`; `RUNS.md` has an account of each run, if this checkout has one (SKILL.md,
*Run history*).

| Layout | Importer to copy (keys) |
|---|---|
| Verse sections under `<h2>`, Hebrew lemma then `LXX:` | `process_jerome_commentary.py` |
| Bold verse labels inside chapters; text before the first label is a preface | `process_berengaudus_commentary.py` |
| Verse labels at paragraph starts, `7:36-50. <i>…</i>` / `(1 Cor. 1:1) <i>…</i>` | `process_cyril_commentary.py`; `process_ambrosiaster_commentary.py` (`Amb1Cor` … `AmbPhil`: a new epistle is just a `WORKS` entry) |
| Bare verse numbers mid-sentence | `process_theodoret_commentary.py` (`label_sections`) |
| Numbered propositions with no verse labels (verse guessed as a hint) | `process_augustine_romans_commentary.py` (`intro_lemmas`) |
| Homily series, one file per sermon, no lemmas | `process_augustine_commentary.py` (Tractates, `"homily": True`), `process_jerome_psalms_commentary.py`, `process_basil_psalms_commentary.py` (Douay verse offsets in the notes), `process_basil_hexaemeron_commentary.py` |
| No verse labels at all: numbered paragraphs (the edition's section numbers) under `<h2>` books, imported in full | `process_ambrose_luke_commentary.py` (key `AmbLuke`; a copy of Jerome's, per-piece checks included): one section per paragraph, the number moved into an `<h3>` the agent sees; each section's heading is a GUESSED verse (`1:5 ¶B1.14`: a monotone word-overlap path through the book, `guess_verses`), an audit hint never shown to the agent (WORKS `guessed`); every section `cont` under `homily`, so blocks run across paragraphs and only each book's first needs a START; skipped prefaces/closing notes are WORKS `nonverse`. Pieces pack paragraphs of one book, cutting before an italic lemma. |
| Several psalms explained in ONE file, `<h2>On Psalm 35 (36)</h2>` (Latin, then KJV), numbered paragraphs per psalm, no verse labels | `process_ambrose_psalms_commentary.py` (key `AmbTwelvePs`; a copy of Ambrose's Luke importer): guesses per psalm over that KJV psalm only, START per psalm, footnotes shown as hints after their paragraph, WORKS `own_chapter` so other-psalm blocks count as cross-references. |
| Homily series in ONE file, `<h3>` chapters, one section per chapter (`cont` for a homily's later chapters) | `process_ambrose_hexameron_commentary.py` |
| Treatise expounding a passage in order, `<h2>Chapter N</h2>`, imported in full, titled per chapter ("…, Chapter N" / "Chapters N-M", checked by `--check` and the audit via WORKS `chapter_titles`) | `process_ambrose_hexameron_commentary.py` (`"kind": "chapters"`, key `AmbParadise`; with `<h2>Book One</h2>` books and chapters numbered per book, titled "…, Book N, Chapter M": `"books": True`, key `AmbCain`; each work's prompt wording in `CHAPTERS_WORDING`) |
| One file per psalm, long psalms cut into pieces | `process_augustine_psalms_commentary.py` |
| Selective, chapters under `<h2>` (with or without summary lines) | `process_cassian_commentary.py` (the original), `process_damascene_commentary.py`, `process_novatian_commentary.py`, `process_basil_spirit_commentary.py`, `process_augustine_grace_commentary.py`, `process_isaac_commentary.py` |
| Selective, one file per book, chapters/sections numbered at paragraph starts | `process_salvian_commentary.py`, `process_augustine_harmony_commentary.py`, `process_eusebius_history_commentary.py` |
| Selective, bold chapter headings and a printed apparatus to drop | `process_eusebius_commentary.py` |
| Questions and answers | `process_basil_commentary.py` |
| Letters, one file per letter | `process_athanasius_commentary.py`; many short letters packed into pieces: `process_basil_letters_commentary.py`; sermons packed likewise: `process_leo_commentary.py`; orations with section numerals at paragraph starts: `process_gregory_nazianzus_commentary.py` |
| Several works in one file sharing one url | `process_aphrahat_commentary.py` (`block_is_mine`) |
| A glossary with no verses (names per book), imported as a CURATED selection: the session finds the candidates, the prompt shows them per piece as hints, one entry per block | `process_jerome_names_commentary.py` (`HebNames`; `locate_block` matches a block inside the list its title names, since entries recur verbatim across lists) |

## Making the body match what the agents write

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
- Check NFC handling in the copy's `_norm` (`reference/source-proofreading.md`, *Greek*).

## Pieces

- Pack consecutive units greedily up to the cap (an even split leaves stray tiny pieces); a unit
  over the cap stands alone (very large chapters have imported fine). Use a cap of ~25k where most
  of the text is imported into several files. Truncate very long editors' notes in the hints.

## The audit with a new layout

- The audit's lemma detector knows Jerome's layouts (a Hebrew lemma then an LXX one, introduced
  by "LXX:" or by a phrase, in parentheses, with inline alternatives, or with a half-verse first
  paragraph), a formula before the lemma (`intro_lemmas`, `lemma_formula`) and bold lemma
  paragraphs (`bold_lemmas`). For a new layout, confirm that it finds every lemma before trusting
  LEMMA CUT, and extend it if needed; then make sure the earlier works' results don't change,
  except for improvements.
- The audit's selective mode uses the importer's `locate_block(work, c, q, source, offs)` when it
  has one (to find a block's text where plain search would give a false MULTI-MATCH), and
  `WORKS[…]["small_block"]` as the "small block" threshold (default 250).
- Psalm works (homilies on the psalms, one file per psalm): cross-psalm parallels count as the
  book's own files, so check coverage and duplicates per psalm by its OWN files, and that no
  OUTSIDE HEADING block lies inside the homily's own psalm. One importer key covering several
  psalms needs WORKS `own_chapter`, or every cross-psalm parallel is a HARD OVERLAP that aborts
  the run.
- Source order: many per-father copies (grep `fix-order`; not Jerome's, whose runs use
  `import_checks.py order`) have `--order` / `--fix-order BASE` (only
  this work's appended blocks move; old blocks stay first). The per-book order check can't see a
  file shared by several BOOKS of one work: check (book, chapter) order across the work's urls.
