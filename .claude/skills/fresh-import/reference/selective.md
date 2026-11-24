# Selective works

Read this when Phase 0 finds a work with no verse sections (a treatise, dialogue, sermons,
letters, a history, a heresiology), first done for John Cassian's *Conferences*. With the user's
approval (ask in Phase 0) such a work is imported **selectively**: the agents read every section
and file only the stretches that comment on a verse, under rule 13; everything else is left out
on purpose. All selective importers are per-father copies, so read `reference/new-importer.md`
too when a new one is needed.

**Rule 13 in full** (SKILL.md §3 states it in short; the user chose this threshold for Cassian's
*Conferences*). Import a stretch when the father quotes or plainly refers to a specific verse AND
DOES SOMETHING WITH IT: says what it means, interprets its words (literally, morally or
spiritually), resolves a difficulty in it, applies a figure in it, builds the argument on its
wording, or APPLIES it to the spiritual or monastic life in a way that shows how he reads it (a
verse brought in to describe a stage of prayer, a vice or its remedy, and then drawn out). Leave
out a verse quoted in passing, a bare proof-text, a chain of proof-texts without comment, and
narrative or teaching that merely mentions Scripture. The test: would a reader studying this
verse learn something about how the father understood or used it? Each block is one continuous
verbatim stretch, from sentence boundary to sentence boundary, able to stand alone (with the
question it answers, in a dialogue, when needed), under the smallest verse range its exposition
addresses. The same stretch may be filed under two verses when it really expounds both (the
project `CLAUDE.md` welcomes this), but never two overlapping blocks of the work in one file.

**Hybrid works.** A treatise can mix parts that follow a book verse by verse (import in full) with parts that don't (selective): ask the user part by part in Phase 0. Ambrose's importer supports this with WORKS `parts` (`reference/new-importer.md`, *Models by layout*).

**Phase 0 questions** for the user, beyond "selective?": which parts to skip (letters written TO
the father, untranslated or duplicate parts, an editor's introduction), the title form, and, for
a history or anthology, whether documents the father quotes are imported.

**Setting up**
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
  Phase 1 (`reference/source-proofreading.md`, *Footnotes*), and fix misalignments in the source,
  not by mapping in the importer.

**Prompts**
- A heresiology or a refutation reports the heretics' own exegesis: tell the agents in the prompt
  that a reported reading is never the father's (README FAQ), with examples from the work, and
  read every block for whose voice it is in.
- A collection can reuse a passage in two of its works (sermons, orations): survey every pair of
  sections by loose word overlap, not only shared n-grams (a looser translation of the same text
  hides from n-grams), and ask the user which work files it before the pilot.
- The prompt asks each agent to end with a list of the blocks it wrote and of the expositions it
  considered and left out, with the reason: read those lists when reviewing, since no GAP check
  can tell you what was missed. Most misses in the old-excerpt comparison turn out to be on those
  lists (chains of proof-texts, a verse used as one instance within the exposition of another).
- The selective importers still use the old generic prompt 2 ("Double check…"); if one adopts
  `piece_review.py`, its targeted review needs a selective wording for step (b), since "a verse
  of another book" doesn't fit (`reference/new-importer.md`, *Prompt 2*).

**Checks:** there is no coverage, lemma or placement check. `--check` and `audit … <BASE>
<pieces>|--all` (which branches to `selective_main` for these works) test that every block is
one verbatim stretch found once, its source_title, no two overlapping blocks of the work in one
file, append-only, and print the same text filed under several verses (allowed, rule 13),
overlapping texts in different files, wide ranges, small blocks (`small_block`) and a per-chapter
LAYOUT. The cross-reference and filename checks (BAD FILENAME, PSALM NEIGHBOUR, STRAY,
XREF CONTEXT?) run in selective mode too. `audit … --headings` lists the chapters with their
sizes and footnoted references. Where plain search gives a false MULTI-MATCH (an entry that
recurs verbatim), give the importer a `locate_block` hook (`reference/works-keys.md`).

**Reviewing:** the agents are generous (one stretch under several verses, thin one-sentence
blocks); that has been kept unless the user decided otherwise. One exposition copied whole under
each verse of one passage is a scope slip: merge it into a range file.
