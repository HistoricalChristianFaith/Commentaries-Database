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
- `scripts/`: the importer, the audit, the deletion tool, the extra checks and a KJV lookup.
  The importer's `WORKS` entries record every work imported so far, with the notes that
  described its quirks; they are the models for a new run.
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
  the judgment calls to the user. The user runs the long import commands in their own terminal.

## 2. Tools

All are in `scripts/`. Read them before using them.

| Tool | Use |
|---|---|
| `process_jerome_commentary.py <Work> …` | The importer. Splits the html on `<h2>` into pieces (one per chapter; a chapter over 30k chars is cut at section boundaries, and an oversized section stands alone). For each piece it runs `claude -p` twice in one conversation: the import prompt, then "Double check, was this fully imported properly?". Options: `--dry-run`, `--split-only`, a single piece name, `--start-after NAME`, `--through NAME`, `--check`. Per-work settings are in `WORKS` (html path, book, source_title, `notes` injected into every piece's prompt). Logs go to `work/jerome_<work>_import_logs/run-*.jsonl` (summaries) and `run-*.events.jsonl` (full event stream). |
| `delete_commentaries.py <Father> <source_url> [--title-prefix P] [--dry-run]` | Deletes blocks whose source_url matches exactly (and whose title starts with P, if given). It cuts blocks out of the file text, so the other blocks keep their exact bytes, and it refuses an empty url without a prefix. **Never run it with an empty url and no prefix.** |
| `audit_jerome_import.py <Work> --headings` | Before importing: heading formats, headings not in the KJV, "lemma opens like KJV x:y" hints, sections not opening with italics, lemma-only sections. |
| `audit_jerome_import.py <Work> <BASE> <pieces…>` / `--all` | After importing: verbatim + unique match of every block, overlaps, coverage gaps (with opening words), append-only status of pre-existing files, LEMMA/LEMMA CUT checks, PLACEMENT? and OUTSIDE HEADING hints, wide ranges, small blocks, where each non-verse section went, and a per-section LAYOUT. `BASE` is the deletion commit. |
| `import_checks.py <Work> continuity\|boundaries\|pieces\|notes\|order` | Heading continuity, lemma-only sections and piece openings, reassembly of the pieces, verification of every quotation in the notes, and the source-order check after out-of-sequence runs. |
| `kjv_lookup.py "<Book> <C>:<V>[-<V>]"` | KJV text of a verse or range (e.g. `"Psalms 118:8-9"`). The data is `kjv.sqlite` (table `bible_kjv`, `book` lowercase without spaces, `txt_location = chapter*1000000 + verse`), which the audit also reads. The import prompt tells the piece agents to use this lookup. |

**Chapter-headed works:** when the `<h2>` headings are chapters and each paragraph opens with its
own lemma (Matthew), set `chapter_re` and `lemma_paragraphs` in `WORKS`. Rules 3 and 4 then apply
per paragraph, and `audit --headings` lists every paragraph's guessed verse ("LOW" = weak match).

**Other fathers:** `process_jerome_commentary.py` hard-codes `FATHER = "Jerome"` and assumes the
`<h2>` layout above. For another father, copy it to `scripts/process_<father>_commentary.py`,
change `FATHER` and the prompt wording, and keep the same two-prompt flow and `--check`. The audit
and `import_checks.py` import from the Jerome module, so point them at the copy. The process below
stays the same. Keep the copy's paths the same way as the original's (relative to the skill
folder), so it works on any checkout.

**Gotchas with the tools**
- Every run deletes the units folder at the end (even a single piece). Only a run that reaches the
  LAST piece runs `--check` by itself; otherwise run `--check` yourself.
- `--start-after A --through B` runs everything between A and B. If pilot pieces sit in that
  range, chain several ranges with `&&` so they aren't run twice.
- The audit's "files added or changed since BASE" counts only tracked (pre-existing) files. New
  files are untracked and don't appear there.
- In zsh an unquoted `$VAR` holding several piece names is passed as ONE argument. Write the names
  out, or use `${=VAR}`.
- The audit's lemma detector knows Isaiah/Obadiah's `LXX: <i>…</i>`, Ezekiel's `(LXX: "…")` (to its
  matching parenthesis, which can run on with remarks about the Origenian signs), inline
  alternatives `(or <i>…</i>)`, Joel's dashed gloss inside an LXX run, and a Hebrew lemma whose
  first paragraph holds only a half-verse and runs on in the next paragraph before the LXX
  (Habakkuk 1:3b-4, 3:3b-4; Obadiah 1:13b-14). For a new layout,
  confirm that it finds every lemma before trusting LEMMA CUT, and extend it if needed. Then make
  sure the earlier works' results don't change, except for improvements.
- Editorial marks the user wants left out of the import (e.g. Zechariah's ⟦ ⟧ Migne brackets and
  notes) go in `WORKS[…]["strip"]`: a list of regexes that `load_work` removes from the sections
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
    - one commit for this skill's changes from the run (the `WORKS` entry and any tool or rule
      changes): `fresh-import: record <father> on <book> (#N)`.
    - With no issue, leave out ` (#N)` / `, #N`.
    - Ask before making the import commit and the record commit, because the user sometimes makes
      them (and pushes) themselves. Never commit in the Writings-Database.

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

Commit only the deleted/trimmed `<Father>/` files, with the deletion message (not the skill's
`WORKS` edit, which goes in the record commit). That commit is **BASE** for every audit.

### Phase 3: Pilot

Choose 2–6 pieces that exercise the risky parts:
- Part001 (the prologue and the `<Book> 1_1` placement);
- a piece with half-verse or off headings;
- one with a substantive preface;
- one around a numbering boundary;
- one with a closing note;
- the last piece.

Give the user one command per piece, to run one at a time from the Commentaries-Database root, e.g.
`python3 .claude/skills/fresh-import/scripts/process_jerome_commentary.py <Work> Part003_Ch02.html`.

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
the `WORKS` entry, the tool changes and these edits.

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
