# Preparing and proofreading the source

Read this in Phase 1 when the source isn't a clean, already-proofread file: an OCR'd text, a
fresh translation not yet checked against its original, footnotes or Greek to verify, an
unconverted page, or a work split over several Writings-Database files. Fix source errors in
the Writings-Database only with the user's OK, and commit there only when the user approves.

**Before proofreading**
- A work split over many Writings-Database files: with the user's OK, merge it into one
  standard-format file first (renumber the footnotes 1..k, check the visible text is the inputs
  joined), so the import has one url and one `WORKS` entry.
- An unconverted Pearse page: the Writings-Database's `standardization/pearse_transform.py --file …
  --dry-run` says why it failed closed.

**Against an authoritative copy**
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
- A transcription can move a paragraph's last words into a footnote at a page break: look for
  stray text at the end of notes and for paragraphs ending without punctuation.

**Footnotes**
- Check that markers and notes pair 1..n, and that each note's reference matches the words
  before its marker (score at shift 0 and ±1..6, per file and per run of ten markers; a one-note
  swap doesn't move the score, so compare with an authoritative copy as well). CCEL swaps notes
  too: read the text before a marker before moving its note. The low scorers are often the
  editor's misprinted references; name each in the notes.
- Repeated note references carry their own ids (`id="r18-2"`): make sure the marker regex catches
  them, and compare the body with the visible text using a LOOSER regex than the importer's (the
  reassembly check uses the importer's own and can't see this).

**Greek**
- Check `unicodedata.is_normalized`. Oxia forms (U+1F73) get retyped as tonos (U+03AD) by the
  agents. The verbatim checks (`--check`, the audit, `piece_review.py`) compare through the
  importer's `_norm`: in the newer copies (those that `import unicodedata`: Ambrose's Hexameron,
  Aphrahat, Athanasius, Augustine's Grace/Harmony/Psalms, Basil's Rules/Hexaemeron/Letters/Spirit,
  Damascene, Eusebius's History, Gregory, Isaac, Jerome's *Hebrew Names*, Leo, Novatian, Salvian)
  it NFC-normalizes both sides; in Jerome's commentary importer and the older copies it does not,
  so a non-NFC source there shows up as NOT VERBATIM wherever an agent retypes the Greek:
  normalize the source (with the user's OK) or teach that importer's `_norm` to.
