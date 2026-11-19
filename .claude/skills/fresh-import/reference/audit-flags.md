# HARD lines and other audit details

Read this when a HARD line survives into your review (an `error` record in the run log, an
`ABORTING` piece, or a HARD line in the audit of a batch or of `--all`), when the audit prints a
code SKILL.md §5 doesn't explain, or when you need the run log's record format. Prompt 2 asks
the piece agents to fix HARD lines themselves, so in a run of Jerome's importer they rarely
reach you; with an importer that still uses the old prompt 2 they all do.

**The run log** (`work/jerome_<work>_import_logs/run-*.jsonl`): per piece, each prompt's answer
(`unit`, `sections`, `prompt` 1 or 2, `output`; prompt 2 adds `prompt2_kind` fix/review/legacy
and `prompt2_text`) and, after each prompt, a check record `{unit, check: "after prompt N", base,
counts{hard,soft,info}, coverage, hard[], soft[], lemma_unfiled[], xref_openings (a count),
info[], duration_seconds}` (lists capped at 60 lines). An aborted piece adds `{unit, error}`
naming the HARD lines left. A new audit problem code must be added to `PROBLEM_CLASSES` in
`piece_review.py`; until then it counts as SOFT.

**HARD codes**
- **NOT VERBATIM** often means the agent silently mended source debris or dropped an inline
  editorial mark. Diff the block against the body at the divergence: fix the source (or
  `strip`) when the agent was right, the block when it copied a misprint. After any source or
  `load_work` change, re-run `--check` on everything already imported. Greek retyped in another
  Unicode form also shows here (`reference/source-proofreading.md`, *Greek*).
- **LEMMA [x]** (no block starts at the section start) is expected right after an `attach_next`
  section when the lemma-only section's block runs on past x's lemma: the per-piece checks mark
  it INFO "(expected: joined to the lemma-only section before it)", but the audit itself still
  lists it among its problems. Anywhere else it is two sections joined (SKILL.md §6) or a lost start.
- **LEMMA CUT:** the first block ends inside the lemma (rule 3). **START** (homily works): no
  block starts at the sermon's start. **JOINED?** (`label_sections`): a block runs on over a
  verse label into a file whose range doesn't include it.
- **BAD FILENAME:** a file holding this work's blocks isn't a KJV verse (malformed, e.g. an a/b
  suffix; a book not in `book_names.json`, e.g. the agents' `Psalm 69_28`; a verse the KJV lacks;
  a backwards range): rename it with `mv`, since `git mv -k` silently skips untracked files.
  Zero-padded numbers (`02_01`) count as malformed. Greek Esther (10:4-16:24, KJV Apocrypha
  numbering), Susanna (Daniel 13, up to verse 65) and Bel (Daniel 14, up to 42) are checked
  against `kjv.sqlite`'s own tables; an "unverifiable filename" line is a hint: check by hand.
- **PSALM NEIGHBOUR:** a nearby place matches the block's wording clearly better (margin 0.2)
  than the filed psalm: the psalm one number up or down, with the verse shifted by up to 2 (a
  shifted verse must also score at least 0.4), or the Hebrew place of a joined/split Latin psalm
  (9-10, 113-116, 146-147): almost always Latin numbering; rename. It skips cross-chapter ranges.
  An Old Latin text far from the KJV's wording can lose to a short neighbour verse sharing only
  "Lord" or "David" (Vg 130:2 "If I was not humbly minded" = KJV 131:2, flagged as 132:1): check
  by the Latin, and list a false positive in WORKS `psalm_neighbour_ok` rather than move it.
- **STRAY:** a block added since BASE, in ANY father's folder, holding this work's text under the
  wrong url: a missing or unknown url and 60+ shared characters (outside this father's folder also
  at least 60% of the block); another known work's url and at least max(250 characters, 60%); or
  this work's url in another father's folder (shown as `STRAY <Father>/<file>#k`). In the
  commented book's own files a stray also shows as a GAP or LEMMA; in cross-ref files only STRAY
  sees it. Fix the url or move the block. A block under ~60 characters is too short to detect.
- **NOT APPEND-ONLY:** a pre-existing file lost or changed old text (rule 9); a "-1 line" diff
  whose old text is still a prefix is only a missing final newline.
- **TOML PARSE ERROR / DELETED / CHECK CRASHED:** (the audit reports an unparseable file as
  `TOML PARSE ERROR <file>` instead of dropping it) repair the file's syntax; restore a file that
  existed before the piece; run the `piece_review.py` command to see why the checks failed.

**Not checked by Jerome's importer**
- A new file opening with a blank line: only some per-father importers' `--check` flags it
  (grep "starts with a blank line" in `scripts/`). List them with
  `awk 'FNR==1 && /^$/ {print FILENAME}' <Father>/*.toml` and remove the line.

**Limits of the hints**
- LEMMA VERSES UNFILED looks within ±3 verses of the heading (the whole chapter for paragraph
  lemmas: Matthew, Jeremiah) and gives a few wrong matches on very short lemmas.
- XREF CONTEXT? is a word test: about one in twenty is a false alarm (a "this sense" pointing
  forward; "the prophet says" meaning another book's author). XREF OPENINGS lists every
  cross-ref, so it is long for a big work.
- `oldranges` reads the old import as `BASE^` vs `BASE` (works for a merge commit too): every
  deletion must be in the one BASE commit.
