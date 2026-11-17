# WORKS keys

Read this when writing or changing a `WORKS` entry (Phase 1, step 1) and the work needs more
than the four basic keys. Every importer has its own `WORKS` dict; the audit and
`import_checks.py` load every `process_*_commentary.py` and use the one whose `WORKS` holds the
work key, so a key must not be in two importers. "Reader" says which script acts on the key;
a key set in an importer that its reader doesn't consult does nothing.

| Key | Reader | What it does |
|---|---|---|
| `html` | every importer | The source file, relative to the Writings-Database root (`"Jerome/Commentary on Haggai.html"`). |
| `book` | Jerome's and the verse-commentary copies; audit, `import_checks.py`, `piece_review.py` | The KJV book (a name from `book_names.json`). `None` for a selective work. Jerome's importer also finds BASE by it ("remove old <father> on <book> import"). |
| `source_title` | every importer, audit | The title every block carries (a selective work's blocks add the unit: see `reference/selective.md`). |
| `notes` | every importer; `import_checks.py notes` | Prose injected into every piece's prompt (Phase 1, step 6). |
| `strip` | Jerome, Ambrosiaster, Aphrahat, Athanasius, Basil (Letters), Berengaudus, Cyril, Gregory Nazianzen, Leo, Theodoret | Regexes `load_work` removes from the sections (not the preamble): editorial marks the user wants left out (Migne brackets, edition section numbers, an edition's note). The pieces, `--check`, the audit and `import_checks.py` then all see the same text. Make each rule refuse to run if it matches nothing, and say in the notes that the full source html still has them. |
| `stale_files` | Jerome, Ambrosiaster, Augustine (Romans), Berengaudus, Cyril, Theodoret: `--check` | Old-translation files that must be gone after the run. |
| `pack_chars` | Jerome | Packs whole chapters greedily into pieces up to this size (`Part001_Ch01-03.html`) instead of one piece per chapter: for many short chapters. |
| `attach_next` | Jerome; audit; `piece_review.py` | Headings of lemma-only sections whose exposition is in the next section: each goes into that section's piece, so one agent sees both. Tell the agents in the notes to join the two in one block. The audit still lists `LEMMA [<next heading>]` among its problems; `piece_review.py` reclassifies it as INFO "(expected: joined to the lemma-only section before it)" when a block from the lemma-only section runs past the next lemma. Prefer this to merging blocks by hand after a piece boundary. |
| `lemma_formula` | audit, `import_checks.py boundaries` | A regex for a lead-in before the italic lemma ("Then there follows <i>…</i>"), so the lemma check accepts it. |
| `chapter_re`, `lemma_paragraphs` | Jerome (`chapter_re`); audit and `import_checks.py` (`lemma_paragraphs`) | Chapter-headed works (Matthew, Jeremiah): the `<h2>` headings are chapters and each paragraph opens with its own lemma. Rules 3 and 4 then apply per paragraph, and `audit --headings` lists every paragraph's guessed verse ("LOW" = weak match). A chapter is one section, so it is never cut: a long chapter makes one big piece (fine). The guesses are weak where a lemma quotes a long passage, so expect OUTSIDE HEADING flags there. |
| `bold_lemmas` | audit, `import_checks.py` | The lemma is the whole first paragraph, a bold one (Berengaudus). |
| `intro_lemmas` | audit, `import_checks.py` | A formula before the italic lemma ("When he says:"), and no verse headings (Augustine's Propositions on Romans). |
| `label_sections` | audit | Sections are the translator's bare verse numbers in the running text; a block may run on over one into the next verse (Theodoret). |
| `homily` | audit; Ambrose's Hexameron importer | One section per sermon, no lemma: the audit skips the lemma and placement checks and checks a START per sermon (a `cont` section, a homily's later chapter, needs none). Set in the Augustine (Tractates, Psalms), Basil (Hexaemeron, Psalms), Jerome (Psalms) and Ambrose (Hexameron) importers. |
| `guessed` | audit (`--headings`), `import_checks.py` (`continuity`, `boundaries`) | No verse labels anywhere: the sections' headings are `load_work`'s guesses (`C:V ¶<place>`, with a `score`); `--headings` lists them with weak ones marked, `continuity` reports backward steps, `boundaries` lists only lemma-only paragraphs and piece openings (Ambrose on Luke). |
| `nonverse` | Ambrose's Luke importer | `{(book, section): label}`: paragraphs the user decided to skip (a closing note): non-verse sections, so the audit reports them SKIPPED instead of a HARD GAP. |
| `selective` | audit | The audit branches to `selective_main` (`reference/selective.md`). Set by every selective importer. |
| `small_block` | audit (selective mode) | The "small block" threshold (default 250). |
| `chapter_titles`, `books` | Ambrose's Hexameron importer; audit (`chapter_titles`) | Titles per chapter, "…, Chapter N" / "Chapters N-M", checked by `--check` and the audit; with `books`, "…, Book N, Chapter M" for chapters numbered per book. |
| `kind` | Ambrose's Hexameron, Aphrahat, Athanasius, Augustine (Harmony), Cassian, Damascene, Eusebius (History), Salvian | Picks work-specific parsing or prompt wording inside one importer (e.g. `"chapters"` with `CHAPTERS_WORDING`). |
| others | their importer only | `label`, `latin_psalm`, `number`, `passage(s)`, `work_ref`, `drop_paras`, `cut_from`, `head`, `gaps`, `one_chapter`, `intro_label`, `skip`, `exclude`, `epilogue`, `rubrics`, `candidates`, `split_chars`, `wording`: read that importer's docstring and its existing entries. |

Module-level hooks, not keys: `locate_block(work, c, q, source, offs)` (the audit's selective
mode and `--check` use it to find a block's text where plain search would give a false
MULTI-MATCH; Jerome's *On Hebrew Names*) and `block_is_mine(work, c)` (several works in one file
sharing one url; Aphrahat; `import_checks.py oldranges` uses it too).
