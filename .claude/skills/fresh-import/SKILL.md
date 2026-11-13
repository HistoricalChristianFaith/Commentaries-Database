---
name: fresh-import
description: Replace an old import of a church father's commentary with a fresh public-domain translation (resolve the work, survey, delete the old blocks, pilot, chunks, final review, close the issue). Takes a Writings-Database html path, or a historicalchristian.faith / GitHub url of one.
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
  orchestrating agent, prepare the notes, review each batch, fix mechanical problems, and bring
  the judgment calls to the user. The user runs the long import commands in their own terminal,
  except for the pilot, which you run yourself if the user asks you to (Phase 3).

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

**Chapter-headed works:** when the `<h2>` headings are chapters and each paragraph opens with its
own lemma (Matthew, Jeremiah), set `chapter_re` and `lemma_paragraphs` in `WORKS`. Rules 3 and 4 then
apply per paragraph, and `audit --headings` lists every paragraph's guessed verse ("LOW" = weak match).
A chapter is one section, so it is never cut: a long chapter makes one big piece (Jeremiah 31, 53k
chars, imported cleanly). The guesses are weak where a lemma quotes a long passage, so expect OUTSIDE
HEADING flags there.

**Other fathers:** `process_jerome_commentary.py` hard-codes `FATHER = "Jerome"` and assumes the
`<h2>` layout above. For another father, copy it to `scripts/process_<father>_commentary.py`,
change `FATHER`, the units/logs folder prefix and the prompt wording, give it its own `WORKS`, and
keep the same two-prompt flow and `--check`. `process_berengaudus_commentary.py` (Berengaudus on
Revelation) is the model. The audit and `import_checks.py` find the right module themselves: they
load every `process_*_commentary.py` and use the one whose `WORKS` has the work key, so a key must
not be in two importers. The process below stays the same. Keep the copy's paths the same way as
the original's (relative to the skill folder), so it works on any checkout.
- **A different source layout** is handled in the copy's `load_work`, which should still return
  one section per lemma (heading = its verse label, `html` = the raw source text the agent sees,
  `body` = the text that is imported and checked). Then pieces, prompts, `--check`, the audit and
  `import_checks.py` all work unchanged. Berengaudus's chapters hold bold lemmas labelled
  `<b>Revelation 1:1a <i>…</i></b>`: `load_work` cuts a section at each label, keeps the label in
  `html` as a hint, and drops it from `body`. The text before a chapter's first lemma (a vision
  preface) is its own non-verse section.
- **A work in a subfolder** (`Berengaudus/Commentary on Revelation/English.html`): the Jerome
  `source_url_for` would encode the inner `/` as `%252F`; the copy keeps `%2F` between segments,
  as the existing urls do. Compare the result with the old blocks' url before deleting.
- A translator's introduction or essay before the work goes in `strip` (as a `(?s)` regex), so
  it is neither sent to the agents nor checked.
- **A father folder with spaces** (`Cyril of Alexandria`): the existing urls double-encode the
  father segment too (`file=Cyril%2520of%2520Alexandria%2F…`, as the project `CLAUDE.md` example
  shows); `process_cyril_commentary.py`'s `source_url_for` does this. Jerome's and Berengaudus's
  never needed it.
- **A work split over many files** in the Writings-Database (Cyril on Luke: 14 sermon files of
  Pearse's scanning batches, with parenthesised names that had produced 23 url spellings in the
  old blocks): with the user's approval, merge it into one standard-format file in the
  Writings-Database first (renumber the footnotes 1..k, state per-page boilerplate once in the
  source note, check the visible text is the inputs joined), so the import has one url and one
  `WORKS` entry. Fix source errors found on the way (wrong verse labels) there too, with the
  user's OK; commit in the Writings-Database only when the user approves.
- **Labels in the running text** (Cyril on Luke: `7:36-50. <i>lemma</i>` at a paragraph start
  under `<h2>` sermon headings): `load_work` cuts at each label as Berengaudus's does at each
  bold one; text under a heading before its first label (a sermon continuing the last one's
  passage, label-less catena fragments) is a non-verse section the notes describe. Editorial
  matter inside the sermons (provenance notes `[From Mai.]`, notes on lost text, standalone
  lacuna lines, manuscript rubrics and colophons) goes in `strip`; the translator's bracketed
  supplements stay. Unlinked note marks (`turn<sup>2</sup> away`) are dropped in `load_work`,
  or agents silently "correct" them and the check fails.
- **Bare verse numbers mid-sentence** (Theodoret on Romans: `<h2>Chapter IX.</h2>` and
  `…his proposed design; 6. <i>Not as though…</i>`, the lemma sometimes in plain text):
  `process_theodoret_commentary.py` is the model. `load_work` cuts a section at each number
  that follows on from the last one in its chapter (prev < v <= prev+5, so references like
  "(John i. 29, 36.)" aren't cut), joins a number holding only its lemma to the next one
  ("15:1-2"), drops every number from the body, opens a chapter's first section with its
  lead-in words, and carries the chapter across `<h2>Book N</h2>` tome headings that fall
  mid-chapter (their text before the first number is a non-verse preface). The notes tell the
  agents that a block starts where the number stood, even mid-sentence. Since a comment often
  rightly covers two numbered verses, `WORKS` sets `label_sections`, and the audit then reports
  a section covered by a block from the section before as "joined" (or JOINED? if the block's
  file doesn't include that verse) instead of LEMMA. Survey the numbers' sequence per chapter
  first: misprints ("39." for 29) and numbers run into the word before them ("eternal.18.")
  are fixed in the source.
- **OCR'd sources** (Theodoret's Romans, scanned from an 1839 magazine): the pilot agents'
  "kept as printed" lists showed many misreads (he/be, "bom", "the (rod of all", "thou shall"
  in KJV lemmas). A dictionary scan finds almost none of them; two read-only subagents
  proofreading half the text each (exact unique snippet, correction, confidence) found 60+.
  Do this after the pilot, before the chunks; check each finding in context; fix the source
  with the user's OK and apply the same fixes to the pilot blocks (whitespace-tolerant
  replacement of the plain-text forms), then re-audit the pilot.
  - **If an authoritative transcription exists** (CCEL's NPNF pages), diff against it instead,
    in Phase 1, before anything is imported: Augustine's Tractates on John (OCR'd) gave 606
    word-level differences across 124 files. Tokenise both texts into words (ignoring case,
    punctuation and quote style), `difflib` them, and map each difference back to an html offset
    in the local file so the fix keeps the file's own markup and punctuation. The diff found
    misreads (shall/shalt ×46, test/lest ×15, cloth/doth, horn/born, layer/laver), ~210 glued
    words, beta-code Greek, 17 lost lines (Tractates 1, 2, 6, 7) and a duplicated passage
    (Tractate 6, whose extra footnote marker shifted the notes). Strip CCEL's page-number spans
    (`<span class="pb">`) first, and reject the differences where CCEL is the odd one out: its
    page-break word splits ("con cealed", "be cause"; a local whole word in the dictionary or used
    elsewhere in the work is right) and its own typos. Review every remaining difference, stage
    the fixed files in the scratchpad, re-diff (only the rejects should remain), then write them
    with the user's OK. The same CCEL pages give the footnotes, so compare markers by the words
    before them too (lost markers shifted the notes in five tractates; 79 notes had lost their
    Hebrew/Greek and were truncated).
  - A word diff can't see punctuation: some missing paragraph breaks stay (Tractate 104's
    `Thee."3. The glorification`, a lost break, failed `--check` after the import and was fixed
    in the source; the agent had already put the break in its block).
- **A homily series, one file per sermon** (Augustine's Tractates on John: 124 files, each its
  own url, numbered paragraphs, no lemmas): `process_augustine_commentary.py` is the model. Its
  `WORKS` is generated, one entry per file (`JohnTr001` … `JohnTr124`, `"homily": True`), each
  one section and one piece (6–47k chars; a sermon is never cut), headed by the passage read
  from the italic line under the title (with `PASSAGES` overrides where it says "On the same
  passage"). The NPNF paragraph numbers are stripped (the user's choice); the notes are inline
  `[note: …]` hints. The command line takes ranges (`JohnTr031-JohnTr056 JohnTr058-JohnTr072`)
  and runs `--check` after each tractate. With `homily`, the audit skips the lemma and
  placement checks and only asks that a block starts at the sermon's start (START). Agents file
  a sermon's recap of earlier verses under those verses (OUTSIDE HEADING): correct by rule 2.
  The pilot's tractates run ahead of their neighbours, so files shared by several tractates end
  up out of tractate order: `--order` finds them and `--fix-order BASE` reorders only the
  appended blocks. Blocks were large where Augustine dwells on one verse (a 37k block for
  Tractate 5, all on 1:33; 18.5k of Tractate 1 on 1:1): check the opening of each big block
  against the next verse's first quotation before calling it under-split.
- **Homilies on the Psalms** (Jerome's 73, two series, `process_jerome_psalms_commentary.py`,
  keys `PsHom001` … `PsHom073`): the same homily layout, with the psalm numbered as in the
  Septuagint/Vulgate. `kjv_heading` turns it into the KJV range used as the hint heading (most
  psalms +1; Latin 9 = KJV 9-10, 114/115 = 116:1-9/10-19, 146/147 = 147:1-11/12-20), and the
  notes tell the agents to place by the verse's WORDING (the Latin counts titles as verses, and
  the psalter is translated from the Greek: "Let the just feast" is KJV 68:3). A psalm's title
  goes under its verse 1. The second series preaches again on psalms of the first, so many
  files hold both; run the first series first and fix the pilot's leftovers with
  `--fix-order BASE`. The pilot used six homilies, then the rest went in one run. In the
  "re-import" case the old blocks were of the SAME translation (a weak earlier import: 94%
  coverage, 39 blocks not verbatim); the url-less ACCS excerpts (FC's Ewald translation,
  115 title spellings, FC numbers 1-73 = ours, 75+ = the Mark and other homilies) were matched
  by title and confirmed by distinctive phrases, since a word-overlap score barely separates
  homilies across translations.
  - **Cross-psalm parallels look like own-book blocks:** `--check` and the audit count every
    `Psalms` file as the book's own, so a homily's parallel under ANOTHER psalm shows as
    OVERLAP + OUTSIDE HEADING (45, all genuine), and a stretch filed ONLY under another psalm
    would still pass the coverage checks. So check coverage by each homily's own psalm's files
    alone as well (it was complete), and confirm that no OUTSIDE HEADING block lies inside
    the homily's own psalm. A heuristic scoring each block's opening against the psalm's KJV
    verses flags possible verse slips; nearly all 76 flags were titles, Latin lemmas or the
    Greek wording, and every one checked out.
  - **Old vs new comparison** (asked for after the import; worth doing whenever the old
    blocks are of the same translation): map every old block's text to the new blocks
    covering it, and back. Here the placements agreed almost entirely (739 same file, 60
    overlapping, 3 real disagreements, all decided for the new import). The useful output was
    the old cross-references the new import lacks: of 114 (23 same-translation, 91 ACCS),
    subagents judging each by rule 8 found 13 genuine expositions the agents had missed,
    mostly a SECOND verse expounded inside a stretch already cross-filed for one verse, plus
    a psalm title's history (1 Samuel 24:3). They were added from the source paragraphs
    (check each end for a closing quotation mark), followed by `--fix-order`. The rest were
    passing proof-texts, thematic tags or wrong verses in the old files.
- **An apologetic treatise, selective, one file per book** (Eusebius's *Proof of the Gospel*,
  Ferrar 1920, Pearse's transcription; `process_eusebius_commentary.py`, keys `DE01` …
  `DE10`): a copy of the Cassian importer. Chapters are `<b>CHAPTER N</b>` (not `<h2>`);
  the text before Chapter 1 is the book's introduction (section 0, "…, Book N,
  Introduction"/"Preface"), and the fragment of Book 15 printed at the end of Book 10 is its
  own section (99, "The Proof of the Gospel, Book 15 (Fragment)", Book 10's url). Ferrar's
  apparatus is dropped from the body by paragraph: bold headings, source lines ("From Micah.",
  "(46) 3. From the same.", "Psalm xix."; matched on plain text) and every wholly italic
  paragraph (chapter and sub-section summaries); his "[Passage quoted, Isa. xxxv. 3.]"
  placeholders stay and open the block whose exposition follows. Fabricius's page marks
  ("(144)", "(b)", Book 1's "{2}"; only 2-3 digit numbers, since Book 5 has Eusebius's own
  "(1) … (2) … (3)"), Pearse's `[[ref]]` margin references and his notes on the
  transcription are in `STRIP`. 582 blocks in 503 files from 45 pieces (five unsplittable
  chapters of 42-67k imported fine).
  - **No authoritative transcription, so diff against scans of the print edition**:
    archive.org has OCR text of Ferrar's volumes (two independent scans of vol. 1, one of
    vol. 2). Word-diff each book, drop the scan's running headers and hyphenated line ends,
    treat scan-only runs over 12 words as footnotes (check them for lost prose: none was
    lost), and flag a Pearse word only where it disagrees with the scan(s). Four read-only
    reviewers judged ~830 items (fix with an exact unique html replacement, or reject).
    Then a second pass against the CLEANER scan alone: the noisier scan often shares
    Pearse's misreads (same print), so "disagrees with every scan" had let some through
    ("thou shall tithe", "when them earnest"). A dictionary scan of rare words and a pattern
    sweep (shall/shalt, hut, arc, clay, "1" for "I", line-break hyphens in names) found
    the rest. Where both scans agree with Pearse (e.g. "Ephiatha"), it is Ferrar's own
    misprint: keep it. ~180 fixes, committed in the Writings-Database with the user's OK.
  - **An unconverted Pearse page** (Book 2 was still raw tertullian.org html): the
    Writings-Database's `standardization/pearse_transform.py --file … --dry-run` said why it
    had failed closed (a note list with notes 6-7 printed twice and note 49 lost; the scan
    gave note 49). After repairing the notes in a scratch copy it converted with all its
    gates passing; run it on the real file only after applying the word fixes to the raw
    file.
  - **Spacing around removed marks matters for `--check`**: a mark stripped beside a quote,
    dash or hyphen leaves a space the agents (rightly) don't copy (`&quot;{6a}&nbsp;Go`,
    `rejoice&quot; [[John xvi. 20]]—the`, `Only- (232) begotten`), and a footnote mark
    with no space after it glues words (`Christ.<sup>39</sup>And`). `make_body` replaces
    every removed mark with a placeholder and `_settle` decides: nothing after an opening
    quote or paragraph start, before closing punctuation or a dash, or after a hyphen; a
    space after a footnote mark between words; otherwise one space if there was one. Strip
    unlinked `<sup>` marks case-insensitively (`<SUP>3</SUP>`), keeping a space for empty
    ones (`commands,<SUP> </SUP>and`).
  - **Source debris surfaces as NOT VERBATIM**: the agents silently mend stray characters
    ("( But" = a lost "(237)", "name 8. is" = a margin ref, "('-')" = "(c)", "Barak<br><br>
    (d).of"). Diff each failing block against the body at the divergence; check the scan;
    fix the source (not the block) when the agent was right, and fix blocks that copied an
    old misprint. Re-run `--check` on every book after each source or `make_body` change.
  - **Old excerpts** were 7 url'd blocks and 117 url-less ones (ACCS, many paraphrased, one
    the Book 15 fragment on Daniel 2:31). A rarity-weighted word overlap against every
    chapter confirmed each was this work even when the text barely matched. After the
    import, comparing old verse ranges with new ones found 30 old excerpts with no new
    block in an overlapping range; a subagent judged each by rule 13: 13 were
    already filed under a nearby or parallel verse, 11 were passing proof-texts or tags, and
    6 genuine expositions were added from the body text (Colossians 2:16-17, Isaiah 29:11,
    John 4:10, Judges 1:1-2, Mark 1:2, Romans 5:12), mostly the NT verse of a fulfilment.
  - A scope slip to watch in a selective run: one exposition of Zech 11:7-14 was copied
    whole into `11_7`, `11_10` and `11_14`; merged into `Zechariah 11_7-14`. (One stretch
    expounding two SEPARATE quoted passages, e.g. Isa 19:1-3 with 19:19-21, rightly goes under
    each.)
- **A dogmatic treatise from a clean CCEL source, selective, one file per book** (John of
  Damascus's *Exact Exposition of the Orthodox Faith*, Salmond, NPNF2 vol. 9;
  `process_damascene_commentary.py`, keys `OF01` … `OF04`, `"kind": "exposition"`): a copy of
  the Cassian importer, the easiest selective run so far. The books had just been rebuilt from
  CCEL with corrections from the 1899 print, so no proofreading pass was needed; the marker/note
  offset score (shift 0 clearly best in every book) and a read of the low scorers confirmed the
  notes. All 100 chapters open with a summary line made only of italic runs, note marks, spaces
  and a period, so one generic `SUMMARY_RE` replaced Cassian's list of irregular cases, and
  `load_work` refuses a chapter without one. Salmond's Psalm numbers are the English ones.
  - **Greek in non-NFC code points**: Salmond's accented Greek uses oxia forms (U+1F73 "έ"),
    which agents retype as the identical-looking tonos form (U+03AD); `_norm` NFC-normalizes
    both sides, so the check never fails on an invisible difference. Check `unicodedata.
    is_normalized` on a new source's Greek before the pilot.
  - Pilot of 6 pieces (one per risk: Book 1's first piece and its 35k Trinity chapter, Paradise,
    the descent into Hades, the cross/eucharist chapters, the last piece), then the other 18 in
    one chained background run: 292 blocks, all checks clean; the pilots left 6 files out of
    source order (fixed by cutting the file text; across books too, Book 1 → 4). The agents were
    generous rather than strict (short glosses of a verse inside a doctrinal argument, a type
    of the cross filed under each of its nine verses), and corrected several wrong footnote
    references themselves.
  - **Old excerpts**: 5 url'd, 5 newadvent (III.29, IV.14) and 80 url-less ACCS blocks (52
    title spellings, all containing "Orthodox Faith"; deleted by `--titles-file`). The 65
    untitled url-less blocks were the father's Pauline commentary (no text match) and stayed.
    Comparing old verse ranges with the new blocks' chapters left 34 misses; a subagent judged
    them: 4 genuine expositions added (1 Peter 3:19 for the descent into Hades, Psalms 68:32-33
    and Malachi 4:2 for worshipping toward the East, Romans 11:36 marked by Salmond's note),
    7 already covered (several under the right verse where the old one was wrong), 23 passing.
- **A fresh translation from the Latin, numbered propositions with no verse labels**
  (Augustine's *Exposition of Certain Propositions from the Epistle to the Romans*, PL 35 via
  augustinus.it; `process_augustine_romans_commentary.py`, key `PropRomans`, since `Romans` is
  Theodoret's; a second Augustine importer, as Jerome's Psalms has its own): a copy of the
  Theodoret importer. No `<h2>`: 76 paragraphs `<b>N.</b> [M.] When he says: <i>lemma</i> …`, the
  bracket being the standard numbering 1-84 (joined "[13.-18.]", split "[29. 1.]"). `load_work`
  cuts one section per proposition, plus the opening sentences as the prologue (→ `Romans 1_1`
  after the existing block), keeps the numbers in the pieces and shows the footnotes inline as
  `[note: …]`. Each section's heading is a GUESS of its lemma's verse (`guess_verses`: KJV word
  overlap on a path that pays for steps back and for long jumps forward), written `3:20 ¶13-18`;
  it is an audit hint only, and the prompt lists the proposition labels instead (rule 1). Three
  guesses stay wrong (KJV wording too far from the Latin-based lemma: [5.] 1:24, [7.-8.] 1:32,
  [81.] 14:22) and show as expected OUTSIDE HEADING flags; check the rest with `audit --headings`.
  The work's `intro_lemmas` flag makes the audit and `import_checks.py` skip the opening formula
  before the lemma. Pieces are runs of whole propositions (5 of ~16k); pilot of the first and
  last, then the other three in one run: 99 blocks (91 in 88 Romans files, 8 cross-references),
  every check clean, nothing to fix.
  - **Check a fresh translation against its Latin before importing.** Split both texts at the
    proposition labels and compare per section: note markers (same ones, same places), length
    ratio (English/Latin 1.0-1.4 throughout here, so nothing dropped) and the notes'
    references. Then two read-only subagents proofread half each against the Latin (exact
    unique snippet, Latin, drop-in correction, confidence; substantive errors only). Of their
    10 findings, 9 were real (a fact turned into a possibility, wrong referents, garbled
    clauses, an invented second group, a misquoted Rom 7:13) and were fixed in the source with the user's OK; one was a defensible
    rendering. The standardization had also dropped the file's provenance comments, so a
    one-line source note was restored after the `<h1>`.
  - The old blocks were 89 url-less ACCS excerpts titled `AUGUSTINE ON ROMANS N` (Landes's
    numbers = the brackets), deleted by `--title-prefix` after matching each one's text to its
    proposition; two untitled, url-less duplicates (digits stripped, one with a Pelagius sentence
    glued on that already had its own Pelagius block) were removed by hand.
- **Expositions on the Psalms, one file per psalm, the biggest run so far** (Augustine, NPNF
  1-08, the abridged Oxford translation; `process_augustine_psalms_commentary.py`, keys
  `PsExp001` … `PsExp150`, a copy of the Tractates importer): 150 files named by the English
  psalm number, 3.5M chars of text, 6,017 notes, rebuilt from CCEL and proofread against the
  1886 print just before (Writings-Database 938841f3). The translators' "(ver. N)" marks give
  KJV verse numbers in order, so placement was easy; they are off in ~50 places (Ps 37 "ver.
  20" = KJV 21; Pss 48, 53, 57, 63 one off throughout), and the agents placed by wording as
  told. A psalm over 36k chars of html (inline notes included) is cut into balanced pieces at
  the editors' headings (Ps 119's Hebrew letters; the "Second Part" headings of 37, 49, 59)
  or else at paragraph boundaries: 188 pieces, each its own section (`Ps037a.html` …), headed
  by the KJV range its marks span (an audit hint), and the prompt tells piece 2+ not to touch
  the earlier pieces' blocks. The psalm's italic title line (Augustine's Latin inscription)
  is text and opens the first block under verse 1 (the user's choice); a wholly italic
  paragraph anywhere else, and Ps 41's opening rubric, is an editors' heading (`<h2>` in the
  piece, dropped from the body). Paragraph numbers are dropped; Coxe's notes quoting
  sentences of Augustine the edition omits (Ps 119's preface) are notes, not imported.
  - Pilot of 7 pieces (Pss 1, 6, 37 in three pieces, 108, 150), then the other 181 pieces in
    one background run (~9.5 hours): 3,065 blocks (2,249 in 2,214 own-psalm files, 152
    cross-psalm parallels in 120 files, 664 cross-references in 535 files of 45 books), every
    psalm 100% covered by its own psalm's files, no duplicate within a psalm. The audit's
    144 OVERLAP and 152 OUTSIDE HEADING entries were all cross-psalm parallels (check
    coverage and duplicates per psalm by its OWN files, as for Jerome's Psalms). Six files
    were left out of psalm order by the pilot: `--fix-order BASE`.
  - **Old blocks in four forms:** 974 url'd to this work, 1,307 newadvent
    (`fathers/1801NNN.htm`, the same translation, modernized "You"), 83 url-less ACCS
    excerpts (WSA wording, Latin psalm numbers, mostly under other books). NPNF is ABRIDGED
    ("…"), so the different-translation excerpts were judged by two read-only subagents
    against the NPNF text (old excerpt + the best word-overlap windows of the claimed psalm
    and its Latin→KJV conversion; verdict SAME / PARTIAL / ABSENT): 18 whose passage NPNF
    lacks (or keeps under half of) were kept, the rest deleted by url and `--titles-file`;
    one shared title meant one block (Wisdom 8_1) was cut by hand. Two url'd excerpts with
    ACCS text of passages NPNF lacks had their url cleared instead (the user's choice). The
    word-overlap score alone can't decide: unrelated passages score 0.3-0.5.
- **A collection of letters, selective, one file per letter** (Athanasius's Festal and
  Personal Letters, NPNF2-04, rebuilt from CCEL and proofread just before, Writings-Database
  724bc3bc; `process_athanasius_commentary.py`, keys `AthLet01` … `AthLet64` by letter number,
  46 files; the editor's introduction file with the two chronicles gets no entry): a copy of
  the Damascene importer with the Tractates' multi-work command line (ranges of keys, every
  piece of each letter, `--check` after each, `--order`/`--fix-order BASE` across letters).
  Sections are NPNF's numbers at paragraph starts ("2." → the text before it is Section 1;
  Letter 52's doubled "1.", Letter 39's "…1."), the fragments of Letters 28-29 ("Another
  Fragment."), or the whole letter; the numbers are dropped from the body and shown as `<h2>`
  (an unnumbered letter gets `<h2>The letter.</h2>` so the agent sees where the text starts).
  The `WORKS` entry's `label` ("Section" / "Fragment" / None) drives the source_title
  ("Festal Letter 1 (for 329), Section 2"; "Letter 48, To Amun"). Editorial matter is
  dropped per letter: `head` (heading paragraphs kept as background: Letter 1's Syriac title,
  the Pachomian narrative framing 57-58), `drop_paras` / `cut_from` (plain-text paragraph
  starts: the Syriac "Here endeth…" rubrics, Jovian's letter and the Arian petitions with 56,
  the Memorandum after 64) and `strip`; each must match or `load_work` refuses. Check that
  nothing else was lost by listing every source paragraph absent from the bodies.
  - Pilot of 6 letters, then the other 40 in one background run (~1 hour): 366 blocks from
    36 letters in 313 files (303 new; 10 pre-existing, appended only). Ten letters rightly
    gave nothing (church business, the creed, borrowed phrasing). The agents were generous
    rather than strict (one stretch filed under up to five verses), as with the Damascene.
  - Agent slips: "Psalm 50_16" etc. (four files; one merged into an existing `Psalms 50_16`
    by appending; NB `git mv -k` silently skips untracked files, so rename with `mv`), and 42
    new files opening with a blank line (stripped; `run_check` now flags it).
  - **Old blocks** were 3 url'd, 31 newadvent `fathers/2806NNN.htm` (same translation) and 76
    url-less ACCS excerpts (`FESTAL LETTER(S) …`, `LETTERS TO MONKS 1:2`, `LETTER TO EPICTETAS
    59:6`, …; ACCS's Festal numbering is not NPNF's), each confirmed by a rarity-weighted word
    overlap against every section; the `LETTER TO SERAPION` excerpts are another work and
    stayed. Comparing old verse ranges with the new blocks' left 51 misses; two read-only
    subagents judged them: 6 genuine expositions added (Esther 9:21-22, John 7:46, Luke 14:15,
    Psalms 34:1, Psalms 57:4, Titus 1:15; the Esther sentence also now opens the
    `Exodus 12_7-8` block, whose "Now as those days…" referred back to it), 13 covered, 32
    passing.
- **Several works in one file, sharing one url, plus separate files** (Aphrahat's
  Demonstrations: Johnston's NPNF2-13 file holds Dem. I, V, VI, VIII, X, XVII, XXI, XXII under
  `<h2>`s with `§N.` sections; Hallock's Dem. 2 and 7 are their own files with "N." paragraphs;
  rebuilt and proofread just before, Writings-Database 71e9922e;
  `process_aphrahat_commentary.py`, keys `AphDem01` … `AphDem22` by Demonstration number, a
  copy of the Athanasius importer). Each Demonstration is its own `WORKS` entry (`h2` selects
  it in the shared file), so a block belongs to a work by url AND title prefix: the importer's
  `block_is_mine(work, c)`, which `--check`, `--order` and the audit's `selective_main` use
  (the audit falls back to the url when an importer lacks it). `--check` also flags a block
  with a shared url whose title matches no Demonstration. Titles: "Demonstration 5 (Of Wars),
  Section 3", as the old newadvent block had it.
  - Phase 0 decisions (the user's): import selectively; Dem. 1 exists twice (Budge's partial
    "On Faith.html" too): Johnston's only; the "Letter of an Inquirer" (written TO Aphrahat)
    is skipped (no entry); delete only the old excerpts of Demonstrations with new text.
  - Pilot of 4 Demonstrations (1, 7, 17, 22: 6 pieces), then the other 6 in one background
    run: 353 blocks in 333 files, all new. The agents were generous (one stretch often under
    2-6 verses; the persecution typology lists of Dem. 21 filed item by item where Aphrahat
    draws out a type), and corrected many misprinted notes themselves. Johnston's Psalm
    notes count the title as verse 1 ("Ps. xxii. 17–19" = KJV 22:16-18): the notes said so,
    and every Psalm file came out in KJV numbering.
  - Dem. 1's first two attempts died on "API Error: Output blocked by content filtering
    policy" and the driver's retry restarted the prompt; the second attempt had already
    written 10 files, which the third found, verified and kept rather than duplicating.
    `--check` would have caught a duplicate as an overlap in one file.
  - Agent slips: Hallock's inline translator's remark "(N.B. this whole passage is obscure
    …)" dropped from two Dem. 2 blocks (NOT VERBATIM; restored, since it is printed text and
    useful to a reader; his inline references "(S. John 16: 33)" were kept throughout); 20
    files opening with a blank line (stripped); 5 files left out of work order by the pilot
    (`--fix-order BASE`).
  - **Old blocks**: 1 url'd, 1 newadvent (`370117.htm`), 51 url-less ACCS excerpts deleted
    (by `--titles-file`, after a word-overlap match against every section: 0.67-1.00 for
    this work's, 0.17-0.35 for the 14 excerpts of Dem. 4 "On Prayer", 14 and 18, which have
    no new text and stayed; one titled `DEMONSTRATIONS 9.25` was really Dem. 8 §25). Old
    verse ranges vs the new blocks left 26 misses; two read-only subagents judged them:
    2 added (1 Kings 15:13, Isaiah 23:15-17), 13 covered, 11 passing or wrongly tagged.
- **A monastic rule in questions and answers, one file** (Basil of Caesarea's *Longer Rules*,
  Clarke 1925, converted and its 447 footnotes transcribed from the page images just before,
  Writings-Database 57ea5de9; `process_basil_commentary.py`, key `LongRules`, a copy of the
  Damascene importer). `<h2>Preface</h2>` is section 0 ("The Longer Rules, Preface"), each
  `<h2>VII. — title (R. 3)</h2>` one Question ("…, Question 7" / "Questions 7-8", the user's
  choice); the title is in the heading, so there is no summary line to cut. The brethren's
  question opens many answers with no marker (sometimes run into the answer's paragraph): the
  prompt says a block may include it. Markers in the `<h1>`/`<h2>` are hinted too.
  - The text had been word-diffed against scans in the conversion, so no proofreading pass;
    the note offset score (shift 0 clearly best) confirmed the notes. Clarke's misprinted
    references, kept as printed (Ps 42:2 as "xli. 2", 2 Cor 6:17 as "vi. 7", Gal 5:10 as
    "v. 20", Matt 25:26 as "xxv. 36", Ps 77:3 as "xxvii. 3"), and his non-Scripture
    abbreviations (F. = Longer Rule, B. = Shorter Rule, R. = Rufinus, Garnier's pages) went
    in the notes; the agents placed every one by wording.
  - Pilot of 4 pieces (Preface, Q2-6, Q35-37, Q46-55), then the other 5 in one background run:
    227 blocks in 207 files, all checks clean; the pilot left 4 files out of source order
    (fixed by cutting the file text). The agents were generous (one stretch under up to four
    verses; light "rule grounded in a verse" blocks), as with the Damascene and Athanasius.
  - **Old blocks**: no url'd ones; 64 url-less ACCS excerpts (`THE LONG RULES 7`, `…, Q.37.R`,
    39 spellings, one with a leading space) deleted by `--titles-file`, and 3 UNTITLED ones
    found because their text ends "The Long Rules, q…" (two OCR-garbled with every "r"
    missing, so a word-overlap match scores them near zero: also scan url-less text for the
    work's name and for garbling). Old verse ranges vs the new blocks left 24 misses; a
    subagent judged them: 5 added (1 Corinthians 10:32, 1 Samuel 3:13, 2 Corinthians 1:9,
    2 Corinthians 6:1, Proverbs 4:23), 9 covered, 9 passing or wrongly tagged, 1 weak and left out.
- **A big letter collection, many small letters PACKED into each piece** (Basil of Caesarea's
  Letters, Jackson, NPNF2-08, rebuilt from CCEL and proofread just before, Writings-Database
  1d8fa325; `process_basil_letters_commentary.py`, keys `BasLet001` … `BasLet366`, a second
  Basil importer copied from the Athanasius one). 357 files, most letters 1-4k chars, so (the
  user's choice) `make_batches` packs consecutive letters, in number order over the WHOLE
  collection, into 56 pieces of up to 25k (`B007_L041-046`); a longer letter gets pieces of its
  own at section boundaries (`B003_L008_S01-06`). The packing is global, so piece names don't
  depend on the selection; the command line runs pieces (`B002 B004-B027`), `--list` shows
  them, and `--check`/`--order` take letter keys. Each letter keeps its own url and title: the
  prompt's SOURCE FIELDS list every letter of the piece, and a block given another letter's url
  would fail that letter's verbatim check. The driver checks each letter after its last piece.
  - `WORKS` is built by scanning the folder. No entry (the user's choices): letters written TO
    Basil (Julian 39-40, Antipater 187, Libanius ×14), files with no letter text (an address
    only, or the editor's bracketed summary "[A salutation.]": 30 letters), the Introduction
    and the two editor's-note files. Sections are NPNF's "2." numbers (text before "2." is
    Section 1; Letter 203's "[3." keeps its bracket; Letter 99 has no "2.", a `gaps` entry;
    Letter 233's "I." is stripped); the canonical letters 188/199/217 are cut at Roman canon
    numerals continuing across the letters (I-XVI, XVII-L, LI-LXXXIV), titled "Letter 188,
    Canon 12" with the text before the first canon as "…, Introduction". Titles are "Letter 8,
    Section 2" / plain "Letter 13" (the user's choice). Letter 199 had lost canon XXXII's
    numeral and paragraph break (run into XXXI); restored in the source with the user's OK.
  - Pilot of 6 pieces (the first, a split letter's first half, 15 packed short letters, a
    canonical letter, the most exegetical letter 260, the last), then two chunks of 25 run in
    the background (~40 min each; 1-4 min per piece): 286 blocks from 81 letters, every check
    clean; the pilot left 2 files out of letter order (`--fix-order BASE`). The agents were
    generous, as with Athanasius (one stretch under up to six verses), and corrected Jackson's
    misprinted references themselves (Ps "xix. 91" = 119:91, "Jer. 4:5" = 5:4-5).
  - **Old blocks**: 13 url'd, 57 url-less ACCS excerpts (`LETTER 46:5`, `AN APOLOGY TO THE
    CAESAREANS, LETTER 8`, 42 spellings; each matched its letter by word overlap, deleted by
    `--titles-file`). Old verse ranges vs the new blocks left 42 misses, more than earlier runs
    (Letter 44 to a fallen monk gave nothing at all); two read-only judges: 4 added (Amos 2:7
    from Letter 160, Leviticus 25:8-10 from 260, Jeremiah 2:13 from 8, and Letter 44 §2 under
    Amos 3:12, Jeremiah 8:4 and Ezekiel 33:11), 21 covered (often the old verse was wrong), 14
    passing or the translator's "cf.". Final: 292 blocks in 255 files.
- **Ascetical chapters from the Syriac, one file, selective** (Isaac of Nineveh's *Mystic
  Treatises*, Wensinck 1923, rebuilt from the print and its 421 notes transcribed from the page
  images just before, Writings-Database 5968c9bb; `process_isaac_commentary.py`, key
  `MysticTreatises`, a copy of the Basil importer). 82 `<h2>` chapters ("VII. On …"; II-VI
  bare numerals), one section each, titled "Mystic Treatises, Chapter 7" (the user's choice);
  Chapter XVIII's one `<h3>` is dropped from the body. Wensinck's notes give ~190 Scripture
  references ("Matth. 6, 10.", "Jes."), the rest Bedjan pages, Syriac readings and parallels.
  - The note offset score was best at shift 0 and every low scorer, read in context, was
    Wensinck's own slip: misprints (1 Cor 12 = 2 Cor 12:2-4, "Ps. 37, 35" = Isaiah 37:35,
    "Romans 9, 16" = 1 Cor 9:16, "Exodus 20, 29" = 20:19) and Hebrew Psalm verses (55:23 =
    KJV 55:22, 84:11 = 84:10, 34:16 = 34:15), all named in the notes. Isaac quotes the
    Peshitta, so the agents matched by sense (Sirach 18:9-10 and 3:19 for Wensinck's "Cf." Psalms).
  - **Pieces are packed greedily** (consecutive chapters up to 30k): `split_evenly` gave 44
    pieces, several tiny, because five oversized chapters pushed its count up; packing gave
    35. Chapter XXXV (68k) stood alone and imported fine.
  - **Repeated note references have their own ids** (`<sup><a href="#fn18" id="r18-2">`), which
    the inherited `FOOTNOTE_REF_RE` missed: their numbers stayed in the body ("part18") and six
    blocks failed `--check` after the run (the agents had rightly dropped them). Check a new
    source's markers for `id="rN-M"` before the pilot, and compare the body against the visible
    text with the importer's OWN regex replaced by a looser one (the reassembly check uses the
    same regex, so it can't see this).
  - Pilot of 6 pieces, then the other 29 in one chained background run (~1.5 hours): 203
    blocks in 188 new files, all checks clean after the regex fix; the pilot left 2 files out
    of chapter order. The agents were generous (one stretch under up to four verses).
  - **Old blocks**: 64 url-less ACCS excerpts in the Holy Transfiguration Monastery translation
    (`ASCETICAL HOMILIES N`, HTM's numbering, plus `DISCOURSE 3`/`22` and `ON ASCETICAL LIFE
    5:14`, which proved to be Wensinck III, XXII and V). Two read-only judges compared each with
    its best Wensinck windows: 59 were this work and were deleted (57 by `--titles-file`, the 2
    untitled ones by hand; a judge missed one, Wensinck's wording being far from HTM's, so read
    the ABSENT ones yourself); 5 stayed (Epistle to Abba Symeon ×2, "Instructions for Monks,
    Second Part", "Book of Grace", and a Makarios epistle misfiled under Isaac). Old verse
    ranges vs the new blocks left 28 misses; two judges: 8 added (Chapter X's chain of
    punishments, Eli/David/Samson, matched to the Noah and Belshazzar blocks the agents had
    filed; Sirach 1:28, Psalms 49:14, Jeremiah 2:18, Exodus 25:22, and Galatians 3:27 from the
    log digest), 10 covered, the rest passing or wrongly tagged; 3 borderline ones were left out
    (the user's choice). One 2-sentence block was extended back to the sentence that carries its
    point. Final: 211 blocks in 196 files.
- **A sermon collection, one file per sermon, packed into pieces** (Leo the Great's Sermons,
  Feltoe, NPNF2-12, the 48-sermon selection, rebuilt from CCEL and proofread against the 1895
  print just before, Writings-Database 04e17253; `process_leo_commentary.py`, keys `LeoSer001`
  … `LeoSer095` by sermon number, a copy of the Basil Letters importer). Each `<h2>` ("IV. The
  blessedness of mourning discussed.") is one chapter section, shown to the agents as
  `<h2>Chapter 4: summary</h2>` (the summaries are the editor's); Sermon 1 has no chapters and
  its italic summary line under the `<h1>` is heading matter (`head: 1`). Titles "Sermon 95,
  Chapter 2" / "Chapters 2-3", plain "Sermon 1" (the user's choice). 26 pieces of up to 25k.
  - The source was clean: markers paired 1..n, note offset best at shift 0 everywhere, NFC, the
    bodies equal the visible text. Feltoe's Psalm numbers are mostly English, but some are the
    Latin (Sermon 1's cxliv/cxxxv, 28's cix. 1 = 110:1, 24's lxxxiv. 12 = 85:11, 36's vi. 6 =
    6:5) and some misprinted (59's vii. 4 = 57:4, 24's xxxi. 14 = 132:11): all named in the
    prompt, and every Psalm block came out under the right KJV verse.
  - Pilot of 5 pieces, then the other 21 in one background run (~1 hour): 366 blocks from 45
    sermons (1, 2 and 85 gave none), all checks clean apart from 8 new files opening with a
    blank line (stripped) and 6 files left out of sermon order by the pilot (`--fix-order`).
    Agents were generous (an S46.2 list of Gospel miracles filed under 10 ranges; light
    one-sentence blocks), as in the other selective runs.
  - **Old blocks**: 20 url'd + 2 newadvent (`3603NN.htm`) + 53 url-less ACCS excerpts that two
    judges confirmed as text of these 48 (ACCS's Gospel-sermon numbers run 13 low: "SERMON
    38.5" = 51.5, "41.5.2" = 54.6, "46.5" = 59.5; "8.4" = 59.4, "25.6" = 24.6); 35 excerpts of
    sermons NPNF lacks stayed, and one PARTIAL (Psalms 17_8, its Psalm exposition not in NPNF).
    Five strays filed under Leo were deleted with the user's OK: three Bede on Acts (Acts 3:7,
    3:23, 3:24), the KJV text of Mark 15:15 (Acts 3:14), and Vincent of Lérins' "keep the
    deposit" (1 Timothy 6:20, titled "SERMONS 85.3"). Old verse ranges vs the new blocks left
    33 misses; two judges: 3 added by copying an existing new block to the verse it also
    expounds (2 Peter 1:4 from Sermon 21.3, Hebrews 7:11-12 from 3.1, Psalms 27:1 from 26.4),
    the rest covered or passing; a weaker one (Psalms 145:14 from 36.4) was left out (the
    user's choice). Final: 369 blocks in 308 files.
- **A short homily series on Genesis 1, one file per homily** (Basil of Caesarea's Hexaemeron,
  Jackson, NPNF2-08, rebuilt from CCEL and proofread against the 1895 print just before,
  Writings-Database fe650214/012c3a8c; `process_basil_hexaemeron_commentary.py`, keys `Hex01` …
  `Hex09`, a copy of the Tractates importer, since Basil's other importers are selective).
  Numbered paragraphs, no lemmas and no passage line, so `PASSAGES` gives each homily's range as
  an audit hint ("1:20-25" for Homily 8, which opens on 1:24 and then turns back to the birds).
  Titles "The Hexaemeron, Homily 6: The Creation of Luminous Bodies", as most url'd blocks had
  them. The source was clean (markers paired 1..n, NFC, English Psalm numbers); Homilies 2, 7 and
  8 have a note marker in the `<h1>`, hinted too. Basil quotes the LXX, so the notes say to place
  by sense (LXX 1:8's "God saw that it was good" went under `Genesis 1_8`).
  - Pilot of 2 homilies (1, 8), then the other 7 in one background run (~20 min): 58 blocks,
    31 in 22 Genesis files and 27 cross-references in 26 files, every check clean; the pilot left
    2 files out of homily order (`--fix-order`). Blocks are big where Basil dwells on one verse:
    Homily 1 is one 27k block in `Genesis 1_1` (he never gets past 1:1), Homily 5 one 26k block
    in `Genesis 1_11`.
  - **Old blocks in four forms:** 53 url'd, 16 url-less ACCS excerpts (`HEXAEMERON 5.1`,
    `HOMILIES ON THE HEXAMERON 3:6`, `HOMILY ONE, CREATION OF THE HEAVENS AND EARTH 1.6`, …;
    `--titles-file`), 42 UNTITLED url-less blocks of Jackson's own text with the paragraph
    numbers left in (word overlap 0.98-1.0; they filled `Genesis 1_2`, `1_10`, `1_11`, `1_16`,
    `1_20`, so those files were removed by hand), and two found only after the import, from an
    agent's remark: `EXEGETIC HOMILIES 1.1` and `3.8`. FC 46 (Way), *Exegetic Homilies*,
    numbers the Hexaemeron as its Homilies 1-9 and the Psalm homilies from 10, so search for
    the work's volume title too. They went in a second deletion commit (a file holding only an
    old block plus new ones: `git rm --cached`, so the new file stays untracked).
  - Old verse ranges vs the new blocks: all misses were passing proof-texts (Joel 2:11,
    2:30-31, Colossians 1:15, Psalms 68:6, Exodus 2:12) or translation differences (the ACCS
    "Your knowledge is become wonderful" = Ps 139:6 is Jackson's "fearfully and wonderfully
    made", rightly under 139:14); Acts 28:3 (Paul's viper, one sentence inside the Ps 91:13
    exposition) was borderline and left out (the user's choice).
- **A treatise in books, chapters numbered at paragraph starts, selective** (Salvian's *On the
  Government of God*, Sanford 1930, Pearse's transcription, fixed against the print just before,
  Writings-Database 1313eabc; `process_salvian_commentary.py`, keys `GG01` … `GG08`, a copy of
  the Damascene importer). Each book is its own file and url; under `<h2>THE FOURTH BOOK</h2>`
  every chapter opens a paragraph with `N.&nbsp;`, so `load_work` cuts there, drops the number
  and shows `<h2>Chapter N.</h2>` to the agent. Book 1's `<h2>PREFACE</h2>` (to Salonius) is
  chapter 0, titled "On the Government of God, Book 1, Preface"; blocks are "…, Book 4,
  Chapter 3" / "Chapters 2-3", as the one url'd old block had it. No summaries to cut. 18
  pieces of 16-28k.
  - Source checks: markers and notes paired 1..n, note offset best at shift 0 in every book,
    NFC, no Greek; Sanford's Psalm numbers are English, but his "Ecclesiasticus" uses the
    Latin verse numbers ("39.10" = KJV Sirach 39:7, named in the prompt). Pearse's markup
    left empty `<sup> </sup>` (→ a space) and Book 6's `devil<sup>.<sup>…23…</sup> </sup>`
    (→ ". "): `FIXUPS`, applied before anything else. Three note marks glue words
    ("Peoples<sup>…</sup>had"): `GLUED_REF_RE` turns a mark between text and a letter into a
    space in the body. One of them (Book 7 `destroy it.' "<sup>32</sup>And`) the agent ran
    together anyway, failing `--check` in two files; the blocks were fixed to the body's space.
  - Pilot of 6 pieces (Book 1's first and last, all of Book 2, Book 4's last, Book 7's first,
    Book 8), then the other 12 in one background run (~1 hour): 185 blocks in 176 new files,
    every check clean after that fix. The per-book `order` check can't see files shared by
    several BOOKS: four (`1 John 3_15`, `Isaiah 50_11`, `Jeremiah 5_8`, `Luke 6_25`) had a
    later book's pilot block first and were reordered by (book, chapter). The agents filed
    Salvian's retellings of Scripture narratives as proofs of God's judgment (Flood, Sodom,
    Abraham, the wilderness, David) under wide ranges (`Genesis 12_1-22_19`, `2 Samuel
    13_1-16_22`), as the prompt allowed, and were generous with cross-filing as in the other
    selective runs; three weak cross-filings were deleted at the review (the user's choice:
    `Genesis 15_16`, an allusion inside a 1 Samuel 26:12 exposition; `Psalms 82_4`, the
    objector's quotation; `Luke 9_24`, with Matthew 16:25's wording). Final: 182 blocks in 173
    files.
  - **Old blocks**: 1 url'd (Book 4) and 50 url-less ACCS excerpts (`THE GOVERNANCE OF GOD
    7.8`, `ON THE GOVERNANCE OF GOD 4.19`, `GOVERNANCE OF GOD 1.6`; 41 spellings, ACCS's
    chapter numbers = Sanford's, each confirmed by word overlap), deleted by url and
    `--titles-file`; the 14 excerpts of *To the Church against Avarice* ("FOUR BOOKS OF
    TIMOTHY TO THE CHURCH") and Letter 4 stayed. Old ranges vs new blocks: 41 of 51 covered;
    the 10 misses were covered at a neighbouring verse (James 2:6-7, Jeremiah 5:3, Matthew
    5:28-30, Zechariah 7:13, Genesis 19:12-13) or passing list items (1 Kings 20, Judges 4,
    Achan and David's census, Sirach 39:7 in a chain).
- **A short dogmatic treatise, one file, selective** (Novatian's *On the Trinity*, Wallis, ANF 5;
  `process_novatian_commentary.py`, key `NovTrinity`, a copy of the Basil *Longer Rules*
  importer). 31 `<h2>` chapters ("Chapter IX. Argument.—…"; XI has no "Argument"; XV-XXVII carry
  a note "According to Pamelius, ch. xxiii." in the heading, a different numbering the notes
  warn about), one section each, titled "On the Trinity, Chapter 9" (the user's choice); the
  ANF editor's `<h2>Preface.</h2>` (a summary of the treatise) is dropped in `load_work`.
  8 pieces of 19-26k.
  - **Dashes lost as single hyphens**: the source had no em dashes at all (116 dashes typed as
    `-`: `all things-Lord`, `form,-a`, `"<sup>16</sup> -so`), which the Writings-Database's
    four-hyphen dash conversion had missed, and 27 closing/opening quotes on the wrong side of
    their space (`"Come; "and then`, `it is said," of Him`). Both were settled against CCEL's
    ANF 5 pages by alignment: for each local `-` or `"`, the letters on either side were
    looked up in CCEL's text to see whether it prints `—` / `-` and `“` / `”` there (a word
    diff can't see punctuation). Real hyphens and the notes' verse ranges stayed. Fixed in the
    source with the user's OK before anything else; the word diff against CCEL was otherwise
    clean. For a CCEL-derived file, check `—` and quote spacing this way in Phase 1.
  - The note offset score was clearly best at shift 0; the low scorers were the American
    editor's bracketed remarks, Novatian's Old Latin/LXX wording and 14 misprinted references
    (`Heb. iii. 3` = Habakkuk 3:3, `Isa. xiii. 2, 3` = 42:2-3, `Ps. lxviii. 18` = 68:17,
    Chapter III's notes one quotation late, as CCEL prints them too), all named in the notes.
  - Pilot of 3 pieces (Part001, Part005, Part008), then the other 5 in one background run
    (~15 min): 107 blocks, every check clean; the pilot left 2 files out of order (fixed by
    cutting the file text). Generous, like the other selective runs: Chapter VI whole under the
    7 anthropomorphisms it explains, a Chapter XXVIII stretch under 6 prophecies (kept, the
    user's choice); Chapters II, V, XI, XXIII and XXVI (chains of "If Christ is only man…"
    premises or of proof-texts) gave nothing.
  - **Old blocks**: 49 url-less ACCS excerpts (`ON THE TRINITY 18:15–17`, `THE TRINITY 29.16`,
    46 spellings), all this work by word overlap, deleted by `--titles-file`; the 13 excerpts of
    his other works (Jewish Foods, In Praise of Purity, On the Spectacles, Letter One) stayed.
    Old verse ranges vs new blocks left 16 misses; 4 added (the user's choice): Deuteronomy
    32:8 (the Babel argument, copy of `Genesis 11_5-7`), Matthew 1:23 (the Emmanuel block quotes
    Matthew's wording), and Chapter IX whole, the agent's left-out catalogue of prophecies,
    under Exodus 4:13 and Deuteronomy 28:66 for its unusual readings. Final: 111 blocks in 105
    files, all new.
- **A Gospel harmony, selective but mostly imported, one file per book** (Augustine's *Harmony
  of the Gospels*, Salmond/Riddle, NPNF1-06, collated against the 1888 print just before,
  Writings-Database 39d15d66; `process_augustine_harmony_commentary.py`, keys `Harmony1` …
  `Harmony4`, a copy of the Salvian importer). `<h2>Chapter XII.—title</h2>` chapters (the
  editors' long titles stay in the pieces as hints), Books 2-4's `<h2>(The )Prologue.</h2>` as
  chapter 0; the NPNF section numbers opening paragraphs (`25. `, also after `</h2>\n `) are
  dropped from pieces AND body (the user's choice; `load_work` requires 1..n per book). Titles
  "The Harmony of the Gospels, Book 2, Chapter 30" (the user's choice). 45 pieces of up to 25k
  (not 30k: most of Books 2-4 is imported, often into three or four Gospel files).
  - Phase 0 decisions (the user's): selective under rule 13, all four books; a harmonizing
    stretch goes under EVERY Gospel's verse it actually quotes or discusses (not one merely
    named, "Mark also records this"); a Gospel passage quoted with only "the others agree, no
    question arises" is left out. The prompt adds: a discussion of where a passage stands in
    the ORDER of the narrative goes under each Gospel's opening verse(s) of it (Matt 9:35, Mark
    6:6-7, Luke 9:1 for the mission discourse), a detail under its own verses (the staff: Matt
    10:9-10, Mark 6:8-9, Luke 9:3); the "… and so on, down to where we read …" quotations
    never widen a range. The Prologues gave nothing (stated in the notes).
  - The source was clean (NFC, standard markers, note offset best at shift 0 in every book,
    English Psalm numbers); two NPNF misprints went in the notes (Book 3 n.57 "Matt. xxvi. 53"
    = 26:55, Book 4 n.2 "Mark iv. 31" = 1:21); the agents corrected several more themselves.
    Three note marks stand before " )" (`them<sup>…</sup> ),`): `_body` drops the space with
    the mark (`MARK_BEFORE_PAREN_RE`), as the agents write it; found by the pilot's `--check`.
  - Pilot of 6 pieces (~15 min), then the other 39 in one chained background run (~2 hours):
    631 blocks in 586 files (593 in 550 Gospel files: Matthew 198, Luke 162, Mark 143, John
    90; 38 cross-references in 36 files, e.g. Jeremiah 32:6-15 and Zechariah 11:12-13 for
    "Jeremiah" in Matt 27:9, Isaiah 52-54, Genesis 29:16 for Leah and Rachel), every check
    clean. Book 1 (the apologetic) gave 24 blocks from 14 of 35 chapters. Fixes: 11 new files
    opening with a blank line; 4 files shared across BOOKS had a later book's pilot block
    first (the per-book `order` check can't see that: check (book, chapter) order across the
    work's urls). The agents were generous (thin one-sentence copies, a reconciliation filed
    under a Gospel whose wording is barely discussed), kept, as in the other selective runs;
    blocks are large where Augustine reconstructs a whole sequence (Peter's denials under
    `John 18_17-25`, 9.5k; the resurrection morning under `John 20_1-18`/`Luke 24_1-11`, 10.5k).
  - **Old blocks**: 12 url'd and 38 url-less ACCS excerpts (`HARMONY OF THE GOSPELS 2.79.154`,
    `… 1:6.9`; 37 titles, each matched to its chapter by word overlap), deleted by url and
    `--titles-file`. `Mark 6_22`'s "HARMONY OF THE GOSPELS 2.33" ("A girl dances, a mother
    rages…") is not in the Harmony (an Augustine sermon, misattributed by ACCS) and stayed (the
    user's choice). The Catena Aurea blocks quoting "De Cons. Evang." (Newman's translation)
    are another source and were left alone; the prompt says so. Old verse ranges vs new blocks
    left 2 misses of 49: `Mark 12_37` (covered by `Mark 12_35`) and Isaiah 7:14 (Book 1 ch. 26's
    Emmanuel fulfilment), added by hand (the user's choice). Final: 632 blocks in 587 files.
- **A short anti-Pelagian treatise with its covering letters, one file, selective** (Augustine's
  *On Grace and Free Will*, Holmes/Wallis/Warfield, NPNF1-05, collated against the print just
  before, Writings-Database 631e2746/bf75ae93; `process_augustine_grace_commentary.py`, key
  `GraceFreeWill`, a copy of the Novatian importer). The `<h2>`s read "Chapter 41 [XX.]—title":
  the Arabic number is NPNF's section (1-46) and is what the titles use ("On Grace and Free
  Will, Chapter 41" / "Chapters 41-42", the user's choice); the bracketed Roman chapter is
  ignored, and the old division's one inline mark (" [III.]" mid-section 5, which the agents
  rightly dropped and so failed `--check`) is stripped. The file also prints Augustine's two
  letters to Valentinus (Ep. 214, 215), imported too and cut at NPNF's "N." paragraph numbers
  ("…, Letter 2, Section 5"; the salutation opens Section 1; the "[The 214th of Augustin's
  Epistles.]" line is heading matter); the Retractations extract (the user's choice), the
  empty `<h2>`s and the editor's italic summary at the end of Letter II are dropped. Section
  keys are 1-46 for the chapters and 1000·letter + section for the letters (`chapter_title`
  decodes them; a block crossing a letter and the treatise gets an impossible title, so the
  check fails). The letters form `Part001_Letters`, then 6 pieces of chapters (25k cap).
  - Source checks: markers paired 1..321, NFC, note offset clearly best at shift 0; five
    misprinted references (Matt 16:17 = 16:27, Rom 12:1 = 12:21, Ps 69:6 = 79:6, Ps 51:12 =
    51:10, John 1:5 = Eph 6:23) and the Old Latin/LXX wordings (Prov 8:35, 3:16, Ps 84:6, Song
    8:5) named in the notes; the Greek Esther addition in Chapter 42 is `Esther 15_7-8` (KJV
    Apocrypha numbering; `kjv.sqlite`'s `esther,greek` numbers it 15:10-11).
  - Pilot of 3 pieces (letters, Ch 1-7, Ch 42-46), then the other 4 in one background run
    (~15 min): 135 blocks, every check clean but for a pre-existing blank line at the top of
    `Psalms 32_9` (an agent's fix of it was reverted, to stay append-only); the pilot left 1
    file out of order. The agents were generous, as in the other selective runs; Chapters 35-36
    (chains of love texts) and 27 gave nothing.
  - **Old blocks**: 4 url'd, 36 url-less ACCS excerpts (`ON GRACE AND FREE WILL 20.41`, `GRACE
    AND FREE WILL 12.24`, `On Grace and Free Will 1.18.38`; 28 titles, `--titles-file`) and a
    `LETTER TO VALENTINE` url'd to Letters.html (a paraphrase of Ep. 214 §3, which Letters.html
    lacks; `--title-prefix` with that url). The `ON FREE WILL …` excerpts are *De libero
    arbitrio* and stayed. Old verse ranges vs new blocks left 7 misses of 41: 2 covered at a
    parallel (2 Kings 14:10 → `2 Chronicles 25_19-20`, 2 Samuel 15:31 → `17_14`), 4 chain items
    or tags, and Isaiah 1:18, added as a copy of the Chapter 13 `Song of Solomon 8_5` block (the
    user's choice). Final: 136 blocks in 129 files.
- **A dogmatic treatise with summary lines and NPNF section numbers, one file, selective**
  (Basil of Caesarea's *On the Spirit*, Jackson, NPNF2-08, its 656 notes rebuilt against CCEL
  and the print just before, Writings-Database 4622138d; `process_basil_spirit_commentary.py`,
  key `OnSpirit`, a copy of the Novatian importer, since Basil's other importers are built for
  Questions, Letters and Homilies). An empty title `<h2>` ("De Spiritu Sancto.") is skipped;
  each `<h2>Chapter XII</h2>` is one section, its editor's summary (the first paragraph,
  whatever its italics) moved into the `<h2>` the agent sees and cut from the body; the NPNF
  section numbers 1-79 opening paragraphs are dropped from pieces and body (the user's choice;
  `load_work` requires 1..79). Titles "On the Spirit, Chapter 12" / "Chapters 12-13" (the
  user's choice). 15 pieces of 9-28k.
  - Source checks: markers and notes paired 1..656, Greek not NFC (oxia forms; `_norm`
    handles it), note offset clearly best at shift 0 (0.41 vs ≤0.22). 15 misprinted
    references named in the notes with their quoted wording (Rom 11:38 = 11:36, Ezek 23:5 =
    Exodus 23:5, Gal 6:4 = 4:6, Ps 14:4 = 104:4, Ps 107:13 = 108:13, the Prayer Book's 139:7 =
    KJV 139:8, ...). Two source defects were fixed in the Writings-Database first, with the
    user's OK (51a6f696): Chapter XII's summary `<i>` was never closed (all of §28 rendered
    italic), and five note marks stood before " )" / " ;" (the space dropped).
  - Pilot of 5 pieces (Ch 1-3, 8, 11-14, 23-25, 30), then the other 10 in one chained
    background run (~30 min): 136 blocks in 118 files, every check clean; the pilot left 3
    pre-existing files out of order (only this work's appended blocks were reordered, the old
    ones staying first). Chapters I, III, IV, XXIII and XXX gave nothing. Generous, as in the
    other selective runs: whole chapters filed where Basil answers an objection from one verse
    (XIV under `1 Corinthians 10_2`, XIII under `1 Timothy 5_21`, XXII under `John 14_17`),
    one stretch under up to four verses, a few Septuagint-based filings (`Numbers 11_25-26`,
    `Isaiah 42_5`) kept. The agents' borderline offers (Isaiah 6:3, John 1:33, Ps 143:10 and
    51:10, Matt 5:18, John 10:30, John 11:25, Daniel 3) were left out (the user's choice).
  - **Old blocks**: 20 url'd and 28 url-less ACCS excerpts (`ON THE HOLY SPIRIT 8.18`, `OF THE
    HOLY SPIRIT 9.23-10.24`; 21 title spellings, chapter.section = NPNF's; each confirmed by a
    windowed word overlap against every Basil text, one by reading), deleted by url and
    `--titles-file`. Old verse ranges vs new blocks left 25 misses of 48, mostly ACCS tags and
    passing proof-texts; one genuine: Chapter XII's reading of the anointing (God anointing,
    Son anointed, Spirit the unction) on Acts 10:38, Isaiah 61:1 and Psalms 45:7, added as
    copies of the new Chapter XII block (the user's choice). Final: 139 blocks in 121 files.
- **A history, selective, Eusebius's own words only, one file per book** (Eusebius of Caesarea's
  *Church History*, McGiffert, NPNF2-01, collated against the print just before,
  Writings-Database 18010805 … 5398ee31; `process_eusebius_history_commentary.py`, keys `HE01` …
  `HE10`, a copy of the Augustine *Harmony* importer, since `process_eusebius_commentary.py` is
  built for the Proof of the Gospel). `<h2>Chapter XII. <i>title</i></h2>` chapters (some with a
  note mark in the `<h2>`), Books 2, 5, 7, 8's `<h2>Introduction.</h2>` as chapter 0; the NPNF
  section numbers ("2 text", no period) are dropped from pieces and body (`NUMBERING_OK` lists
  the five chapters whose printed numbers aren't 1..n). Book 8's file also prints the Martyrs of
  Palestine (included, the user's choice: keys 1001-1013, "Church History, Book 8, Martyrs of
  Palestine, Chapter 11"; a piece never crosses into it); Book 10's colophon `<h2>` is dropped.
  Titles "Church History, Book 3, Chapter 24" / "Chapters 8-9" (the user's choice).
  - Phase 0 decisions (the user's): selective; **Eusebius's own words only**: the documents he
    quotes (Africanus on the genealogies, Josephus, Philo, Hegesippus, Papias, Irenaeus, Clement,
    Origen, Dionysius on the Apocalypse, the Vienne-Lyons letter, synodal letters, edicts) are
    not imported even where they expound Scripture; several are filed under their own authors'
    folders already. A read-only subagent mapped every quoted document per book (exact opening
    and closing words; the hard ones with no quote marks: 1.7's Africanus running on past the
    letter's close, 3.20 Hegesippus in indirect speech, 6.14 Clement's *Hypotyposes*, 6.25
    Origen's never-closed quotation, 6.41-42 Dionysius across the chapter break, 7.30's synodal
    "we"); a second drafted the per-book notes from it. Fixed skips: Book 8 Ch. XVII's scribe's
    appendix ("That which follows is found in Some Copies…", numbered 1-6 again) and the
    Martyrs of Palestine's prelude (a near-copy of 8.2). The Tyre oration (10.4), printed in
    quote marks, is Eusebius's own.
  - McGiffert's 2,978 notes are 1.8M chars (twice the text), many of them essays: the hints are
    cut to `NOTE_HINT_CHARS` (300). Pieces are packed greedily up to 30k (`pack_greedily`; the
    even split gave stray tiny pieces): 59 in all; 10.4 (46k) stood alone and imported fine.
  - Pilot of 6 pieces, then the other 53 in one chained background run (~2.5 hours): 120 blocks
    in 116 files (90 new, 26 appended), every check clean after one `_body` fix: a note mark
    right after an opening quote (`"<sup>98</sup> Now about that time`, 2.9) left a space the
    agent rightly didn't copy (`MARK_AFTER_OPEN_QUOTE_RE`). Books 4, 5 and 7 gave nothing (quoted
    documents and narrative), Book 6 one block (Origen and Matthew 19:12). One block opening
    "They did this…" (`Acts 4_34-35`) was extended back two sentences to its referent. The
    agents were generous, as in the other selective runs (one 3.24 stretch on the order of the
    Gospels under six verses, the oration's bridal passage under five Isaiah ranges, thin
    "Luke in the Acts … Josephus" juxtapositions); kept.
  - `import_checks.py … notes` reads every text between two `"` as a quotation, prose between
    quotes included, so its misses on notes with many quotations are noise: check the PAIRED
    quotations (`re.findall(r'"([^"]+)"', notes)`) against the body instead.
  - **Old blocks**: 15 url'd and 45 url-less ACCS excerpts (`ECCLESIASTICAL HISTORY 3.24.8-12`,
    `HISTORY OF THE CHURCH 3.32`, `Ecclesiastical History 10:4`; 39 titles, each confirmed by a
    windowed word overlap against every chapter and the other Eusebius works), deleted by url
    and `--titles-file` (match exactly: `…1.2` is a prefix of `…1.2.2-3`, and Theodoret's own
    *Ecclesiastical History* excerpts share the wording). Old verse ranges vs new blocks: 25 of
    60 covered; of the 35 misses, 21 were quoted documents (excluded by the user's rule), 7
    passing or narrative, 7 covered at a nearby or parallel verse; none was a missing
    exposition by Eusebius. Added at the review (the user's choice): the 2.22 block copied to
    `2 Timothy 4_6` (it reads 4:6 as foretelling Paul's martyrdom), 7.18 whole (the statue at
    Paneas of the woman with an issue of blood) under `Matthew 9_20-22`, and 6.3's two
    paragraphs on Origen keeping "not two coats nor shoes" literally under `Matthew 10_9-10`.
    Final: 123 blocks in 118 files.
- **A Pauline commentary from a fresh translation, labels at paragraph starts** (Ambrosiaster's
  *Commentary on 1 Corinthians*, translated from PL 17 just before, Writings-Database d49a9075;
  `process_ambrosiaster_commentary.py`, key `Amb1Cor`, a copy of the Cyril on Luke importer).
  Keys are "Amb" + the book, since Jerome's importer already has `Galatians`, `Titus` and
  `Philemon`; the work's `label` ("1 Cor.") drives `label_re`, so the other epistles can be added
  as entries. `<h2>Prologue</h2>` and 16 `<h2>Chapter I</h2>` groups; every paragraph opening
  with `(1 Cor. 14:24–25) <i>lemma</i>` starts a section (the label is dropped from the body;
  the same form inside a paragraph is the translator's citation and stays), and `load_work`
  refuses a label whose chapter doesn't match its `<h2>`. 365 sections, 18 pieces.
  - The source was clean (no notes, NFC, one Greek phrase). The labels follow the Latin verse
    division: six sections open with the second half of the verse before (Sosthenes = KJV 1:1
    under "1:2"; "1:25" opens with 1:24 and there is no 1:24 label; 1:19, 1:31, 5:13,
    15:27-28), and the 14:10 lemma sits inside "14:9"; all named in the notes, and the agents
    filed each by wording. The translator's Psalm references keep the Latin numbers (8 of them,
    mapped in the notes), as do "Jon. 2:1" (= KJV 1:17) and "Sir. 10:28" (= KJV 10:25).
  - `audit_jerome_import.py`'s KJV loader didn't strip spaces from the book name ("1
    corinthians" vs the table's "1corinthians"): fixed; the first numbered book through it.
  - Pilot of 5 pieces, then the other 13 in one chained background run (~45 min): 429 blocks,
    404 in 394 1 Corinthians files (384 new, 10 appended after *Questions on the Old and New
    Testaments* blocks) and 25 cross-references (Isaiah 28:11-12 and Matthew 13:10-11 for the
    tongues of 14:21, Deuteronomy 25:4 with Jonah 4:11 and Psalms 36:6 for the ox of 9:9,
    Exodus 24:8 and Leviticus 17:11 for the cup of 11:25-26, 1 Thessalonians 4:16-17 for the
    catching up in 15:51-53, ...); 100% coverage, every check clean. The chapter 6 agent left 19
    new files opening with a blank line (stripped). Agents were careful with half-verse
    openings (rule 2) and left a few one-sentence blocks on single verses (`7_6`, `10_6`,
    `12_29`, `15_47`), kept as coherent.
  - **Old blocks**: 6 url'd (one under John 14:30), a Google Books "CSEL 81.175" excerpt
    (deleted by its url), a url-less ACCS excerpt under Sirach 10:25, and 249 url-less ACCS
    paraphrases titled just `COMMENTARY ON PAUL'S EPISTLES`, a title shared with the 182
    excerpts of the 2 Corinthians commentary: deleted with `--file-prefix "1 Corinthians "`
    (word overlap barely separates ACCS's loose paraphrases from a new translation, so the
    filing book decided, checked by reading the outliers).
  - **The next epistle is just a `WORKS` entry** (*Commentary on 2 Corinthians*, translated
    just before, Writings-Database e199c893; key `Amb2Cor`, `label` "2 Cor."): 218 labels, 14
    pieces, no code changes. The notes list every section opening with the previous verse's
    end (3:3, 5:19-21, 6:14, 6:17-18, 9:12-13, 10:15, 11:10, 12:2; the pilot agents found
    1:14 and 12:12 too, added before the rest) and the verses with no label (1:23-24, 4:14,
    9:14-15, 12:5, 13:12-14); Latin-numbered references Ps. 115:1 = 116:10, Ps. 81:6 = 82:6,
    Bar. 3:38/3:36 = KJV 3:37/3:35, Sir. 3:13 = 3:11. The "11:32-33" section is its lemma
    alone, Ambrosiaster explaining the Damascus escape under the "12:1" lemma in the next
    piece: both went whole, as two blocks, into `2 Corinthians 11_32-12_1` (the user's choice;
    a fixed instruction in the notes).
  - Pilot of 5 pieces, then the other 9 in one chained background run (~25 min): 255 blocks,
    242 in 236 2 Corinthians files (4 appended after *Questions* blocks) and 13
    cross-references (Psalms 116:10, 112:9, Leviticus 26:12, Isaiah 49:8, John 14:9-11, 14:27,
    21:17, Galatians 1:9, 2:4, Romans 13:3, Luke 21:3-4, Matthew 14:26-28, Revelation 14:4);
    100% coverage, every check clean, nothing out of order, nothing to fix.
  - **Old blocks**: 13 url'd (two under John 14:10 and 14:27) and the other 182 `COMMENTARY ON
    PAUL'S EPISTLES` excerpts (`--file-prefix "2 Corinthians "`); 190 files removed.
- **Old excerpts under several titles:** survey url-less blocks by every title form of the work
  (Cyril on Luke had both `COMMENTARY ON LUKE, HOMILY n` and `HOMILIES ON THE GOSPEL OF LUKE n`;
  the second was found only after the import, by the log digest), and match their text against
  the source to confirm they are this work. When the titles are ambiguous (Cassian's
  `CONFERENCE 1:13` is Conference 1 ch. 13, but `CONFERENCE 2:17.25` is Conference 17), identify
  each excerpt by its text instead: match it against every chapter of the father's works
  (word overlap weighted by rarity finds even a different translation's excerpt), settle the
  cases where title and text disagree by reading them, and delete the result by exact title with
  `delete_commentaries.py --titles-file`, after checking that no excerpt of another work shares
  one of those titles.
  - Include the url-less blocks with an EMPTY title in the text match, and expect strays: the
    Cassian Part III survey found an earlier Part's excerpt that the earlier deletion had missed
    (Conference 14 ch. 17 under Proverbs 31:6), and a Byzantine Nativity sticheron (Kassia's)
    filed under Cassian because the names look alike. Bring each one to the user; both were
    deleted with the user's OK (the title file can name another Part's excerpt; an untitled
    block, which `--titles-file` can't name, is removed by hand after checking it is the file's
    only block).

**Selective works** (not a verse-by-verse commentary; first done for John Cassian's
*Conferences*, Part I). Some works worth importing are treatises, dialogues or sermons that quote
and expound Scripture throughout, with no verse sections or lemmas. With the user's approval
(ask in Phase 0) they are imported **selectively**: the agents read every section and file only
the stretches that comment on a verse, under rule 13; everything else is left out on purpose.
- Mark the work's `WORKS` entry `"selective": True`, `"book": None`. The importer's `load_work`
  returns one section per chapter (or whatever unit the source has), with `chapter` None and a
  `chapter_no`, and `make_units` packs runs of whole chapters into pieces up to `SPLIT_CHARS`.
  `process_cassian_commentary.py` is the model: copy it for another father or work. For
  another work of the same father, add its entries to that importer instead, with a `"kind"`
  that picks the prompt's work-specific wording from `KIND_WORDING` (Cassian's *Institutes*,
  `Inst01` … `Inst12`, a treatise in his own voice, uses `"institutes"`: no dialogue sentences,
  and "this Institutes book" rather than "this book", which an agent could read as a book of
  Scripture). Compare the *Conferences*' parsed bodies and `--dry-run` prompt before and after
  any change to that file.
- A work whose parts are separate files with their own urls (Cassian's ten conferences) gets one
  `WORKS` entry per file (`Conf01` … `Conf10`); a dedicatory preface file gets none (rule 6),
  nor does an untranslated one (the *Institutes*' Book 6: "WE have thought best to omit
  altogether the translation of this book.").
- **source_title** carries the chapter: `"<work title>, Chapter N"`, or `"Chapters N-M"` for a
  block crossing chapters, as the url'd Cassian blocks already had it. `--check` and the audit
  check it against the chapter(s) the text really comes from.
- **Editors' footnotes** that give Scripture references (Gibson's "S. Matt. vi. 19.") are the
  best placement hints there are: `load_work` puts them inline in the pieces as
  `<sup>[note: …]</sup>` and drops them from the body, so a block that copies one fails the check.
  **Check, in Phase 1, that the notes line up with their markers before trusting them.** In
  Cassian's Part I they were out of step by four from late in Conference 7 to the end of the
  Part: four notes lost around one marker run, each file ending with the next file's first four
  notes, Conference 10's last three belonging to the Part II preface (which had no markers),
  and a one-note swap at the Conference 6/7 boundary. It was found only by the pilot agents.
  - Measure it: match each note's KJV text against the words before its marker, at offset 0 and
    at shifts of ±1..6, per file and per run of ten markers. A swap of one note at a file
    boundary doesn't move these scores, so also compare every note with an authoritative copy.
  - Fix it in the Writings-Database source, with the user's OK. CCEL's NPNF pages
    (`ccel.org/ccel/cassian/conferences.ii.<conference+1>.<page>.html`, roman numerals, page
    numbers one ahead of the chapters) carry every footnote in order with its text. Align them with
    the file's markers by the text before each one, move or insert the notes (keeping Gibson's
    printed wording and the file's markup; copy CCEL's only for lost notes), and add any lost
    marker. Then check that the visible text is unchanged, markers and notes pair 1..n, and
    every note matches CCEL's apart from "Ib."/"Ibid." expansions and CCEL's silent corrections
    of Gibson's references (keep Gibson's).
  - CCEL can be wrong too: in Conference 17 it swaps two notes (its "Increase and multiply" note
    is "Ps. 5:7; …"). Before moving a note, read the text before its marker and confirm the
    note's reference really is the quotation there.
  - Survey every file of the father's works at once (heading sequence, glued headings like
    `Chapter. XII.The answer …` or `Chapter Xiof …`, markers vs notes, offset alignment): for
    Cassian the same defects ran through Parts II and III (Conferences 19, 20, 21, 24, the two
    Part prefaces), and the scan also found shifts in the Institutes and On the Incarnation.
    Conferences 12 and 22 are untranslated in NPNF ("Not translated."), so they have nothing to
    import, and get no `WORKS` entry. Keep their old url-less excerpts (Part II kept
    `CONFERENCE 12:7.4–5` under Hosea 2_19-20): there is no new text to replace them.
  - Fix the source before the import if you can: this run first mended the mapping in the importer
    instead (since removed), which moved piece boundaries mid-run (next bullet).
- **Changing `load_work` after the pilot can move the piece boundaries** (the split follows the
  pieces' html sizes, hints included): after the hint mapping changed, Conference 9's pieces were renamed and
  the chained `--through Part001_Ch01-14.html` stopped with "No piece named". Re-run `--dry-run`
  for every work after such a change, and run the stretches the pilot didn't cover with the
  Cassian importer's `--chapters A-B` (one ad-hoc piece of exactly those chapters).
- **Chapter summaries** (the italic line under each heading) are cut from the body as well as
  left out by the agents, or every block crossing a chapter fails the check. Some summaries are
  irregular (run straight into the text, split over several italic runs, missing, an italic run
  broken off with the rest on one or more lines of its own, printed without italics, or running
  on into Cassian's text that is itself printed in italics, as in 19.VI and 24.VI; in the
  *Institutes*, a note marker splitting the summary into two italic runs, 2.XV, 4.XXVII, 10.XIV,
  10.XXIV, a last word outside the italics, 2.IX "</i>Eiders<i>.</i>", and a summary running into
  italic text whose opening quote mark belongs to the text, 10.VIII); list the chapters whose
  opening doesn't fit the usual pattern (the body should start with the dialogue's first
  capital), handle each in the summary regex, re-run `--check` on the works already imported,
  and tell the agents about each one in that conference's notes.
- **Checks:** there is no coverage, lemma or placement check. `--check` and `audit … <BASE>
  <pieces>|--all` (which branches to `selective_main` for these works) test that every block is
  one verbatim stretch found once, its source_title, no two overlapping blocks of the work in one
  file, append-only, and print the same text filed under several verses (allowed, rule 13),
  overlapping texts in different files, wide ranges, small blocks and a per-chapter LAYOUT.
  `audit … --headings` lists the chapters with their sizes and footnoted references.
- The prompt asks each agent to end with a list of the blocks it wrote and of the expositions it
  considered and left out, with the reason: read those lists when reviewing, since a GAP check
  can't tell you what was missed. The old excerpts (e.g. the ACCS selection) are a useful
  cross-check at the final review: for each deleted excerpt's chapter and verse, see whether the
  new import filed that chapter under that verse, and bring the misses to the user. (In Part II
  most misses were deliberate rule-13 omissions the agents had listed: verses inside a chain of
  paired proof-texts, or a verse used as one instance within the exposition of another; in
  Part III 21 of 47, all on the agents' left-out lists; in the *Institutes* 6 of 27, all
  listed: chains of proof-texts, the paired "the one says… the other…" texts of 12.8.) Match by verse RANGE, not filename: a
  verse may already be covered by a range file (`Proverbs 31_6-7` for an old `Proverbs 31_6`),
  so script the comparison over parsed ranges rather than looking for the exact file.
- Agents sometimes name a Psalm file `Psalm 69_28` (the KJV lookup accepts "Psalm"); `--check`
  flags any filename whose book isn't in `book_names.json`.
- Source defects show up as chapters out of sequence (`load_work` refuses chapters not numbered
  1..n): Cassian's Conference 2 had lost its `Chapter IV.` heading and Conference 8 had
  `Chapter VI` as plain text. With the user's OK fix them in the Writings-Database (CCEL's NPNF
  pages give the missing summaries); commit there only when the user approves.

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
- The audit's lemma detector knows Isaiah/Obadiah's `LXX: <i>…</i>`, Ezekiel's `(LXX: "…")` (to its
  matching parenthesis, which can run on with remarks about the Origenian signs), inline
  alternatives `(or <i>…</i>)`, Joel's dashed gloss inside an LXX run, and a Hebrew lemma whose
  first paragraph holds only a half-verse and runs on in the next paragraph before the LXX
  (Habakkuk 1:3b-4, 3:3b-4; Obadiah 1:13b-14), and LXX runs introduced by a phrase instead of
  "LXX:" (Micah 1:1 "Or according to the Seventy:", Hosea 13:4 "In place of which one reads in
  the LXX:", Amos 1:1 "But the Seventy, intending I know not what, translated:"). With the work's `intro_lemmas` set
  (Augustine's Propositions on Romans), a formula ("When he says:", "When he says of Abraham:")
  before the italic lemma is skipped. With the work's
  `bold_lemmas` set (Berengaudus), the lemma is the whole first paragraph, a bold one with its
  verse label already dropped by `load_work`, including asides between the bold stretches
  ("The seven stars, he says, are …"). For a new layout,
  confirm that it finds every lemma before trusting LEMMA CUT, and extend it if needed. Then make
  sure the earlier works' results don't change, except for improvements.
- Editorial marks the user wants left out of the import (e.g. Zechariah's ⟦ ⟧ Migne brackets and
  notes, Jeremiah's edition section numbers: a Roman numeral opening every paragraph, sometimes as
  a paragraph of its own, and Arabic sub-section numbers "2." mid-text) go in `WORKS[…]["strip"]`: a list of regexes that `load_work` removes from the sections
  (not the preamble), so the pieces, `--check`, the audit and `import_checks.py` all see the same
  text. Say in the notes that the full source html still has them.
- Never re-serialize TOML files with rtoml or tomlkit. Edit the text and verify by re-parsing.
- **Concurrent imports:** another session may be importing a different work into the same father
  folder at the same time. Then `git status`, the audit's changed-file list, and a pilot rollback
  will include that session's files too. Scope everything by this work's source_url, and never
  roll back with a blanket checkout or delete of untracked files without checking which work each
  file belongs to. Both sessions also edit `WORKS` in the same importer file, so edit only your
  own entry and don't revert the other's.

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
    - one commit for this skill's changes from the run (this file's record of the run and any
      rule changes): `fresh-import: record <father> on <book> (#N)`. The `WORKS` entry and
      tool changes in `scripts/` are gitignored and stay local.
    - With no issue, leave out ` (#N)` / `, #N`.
    - Ask before making the import commit and the record commit, because the user sometimes makes
      them (and pushes) themselves. Never commit in the Writings-Database.
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

Stop and wait for the user at every ⏸. At each stop, start your message with where you are and
what comes next, e.g. "**Phase 2 (deletion) done, BASE = abc1234. Next: Phase 3 (pilot).**", so
the run can resume cleanly after a pause or a context summary.

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
   (similar size and structure), which are the models for the notes. For those works,
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
   the old cross-references outside the book.

### Phase 2: Deletion

Run the deletion(s) for real, then verify:
- every file still parses;
- no targeted block remains anywhere;
- each trimmed file holds exactly its other blocks, unchanged (compare the parsed blocks with
  `git show HEAD:<path>` minus the deleted ones).

Commit only the deleted/trimmed `<Father>/` files, with the deletion message (not this file's
edits, which go in the record commit). That commit is **BASE** for every audit.

### Phase 3: Pilot

Choose 2–6 pieces that exercise the risky parts:
- Part001 (the prologue and the `<Book> 1_1` placement);
- a piece with half-verse or off headings;
- one with a substantive preface;
- one around a numbering boundary;
- one with a closing note;
- the last piece.

Propose the pilot pieces, each with the risk it exercises, and one command per piece, to run one
at a time from the Commentaries-Database root, e.g.
`python3 .claude/skills/fresh-import/scripts/process_jerome_commentary.py <Work> Part003_Ch02.html`.

Then ask the user (with AskUserQuestion) who runs the pilot:
- **The user runs it** in their own terminal and tells you when it's done. Wait for that.
- **You run it.** Run the commands yourself, in the order given, chained with `&&` in ONE
  background Bash call (`run_in_background`), so a failed piece stops the rest. Each piece
  takes minutes, beyond the foreground timeout. Send the output to a log in your scratchpad,
  not into your context. Wait for the completion notification; don't poll. Then check the tail
  of that log for an `ABORTING` line before reviewing.

**⏸ After the pilot:**
- `audit_jerome_import.py <Work> <BASE> <pilot pieces…>`.
- Read every run summary (prompt 1 and prompt 2) in the `run-*.jsonl` logs.
- Check every PLACEMENT? flag (see [Reviewing](#5-reviewing-a-batch)).
- Fix mechanical problems in place.
- Bring the user the judgment calls.

If the notes need changing, the pilot can be rolled back cleanly, because everything of this work
after BASE is pilot output. Restore the pre-existing files that hold this work's url from BASE, and
delete the new files that hold only this work's blocks. Check each file first (see *Concurrent
imports* above).

### Phase 4: Chunks

- **Size:** 20–35 pieces per chunk with `--start-after/--through`, run by the user. Chain ranges
  around the pilot pieces, e.g. `Part002` alone, then `--start-after Part003 --through Part028`.
- **⏸ After each chunk:**
  - Audit the chunk's pieces.
  - Have a read-only subagent digest the run logs' summaries. The prompt is in
    [Reviewing](#5-reviewing-a-batch); don't read the `.events.jsonl` files into your own context.
  - Run `import_checks.py <Work> order`.
  - Fix mechanical problems (see [Mechanical fixes](#6-mechanical-fixes)).
  - Bring the user the judgment calls.
- **Once a chunk comes back clean,** the rest can go in one chained command.

Small works (Obadiah, Joel, Haggai: 1–6 pieces) need no chunk loop: a pilot of 2 pieces, then
everything else in one command.

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
5. **⏸ Summarize** for the user and include a draft of the closing comment.

### Phase 6: Finish

After approval, commit the import (unless the user did it). If there is an issue, close it with
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

The `WORKS` entry (with its final notes) is the record a later import will model itself on. If
the run changed or added a standing rule, or extended a tool (e.g. a new lemma layout in the
audit's detector), update this file's text for that too, e.g. the detector's list of known
layouts under *Gotchas with the tools*. Then, after asking, make the record commit (rule 12) with
these edits (the `WORKS` entry and tool changes are in the gitignored `scripts/`, so they stay
local).

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
