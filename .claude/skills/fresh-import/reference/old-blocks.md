# Old blocks: surveying, identifying, deleting, comparing

Read this in Phase 1 (step 5) when the old blocks are more than this work's url (url-less
excerpts, `#anchor` or other-site urls, titles that don't name the work, blocks of uncertain
origin), and in Phase 5 when `import_checks.py oldranges` lists misses to judge.

**Surveying**
- Old blocks come as this url, `#anchor` variants, newadvent urls (often the same translation),
  Google Books urls, and url-less ACCS excerpts under many title spellings (titled e.g.
  "COMMENTARY ON EZEKIEL 11:34.1-31"), some untitled, some OCR-garbled, some under the work's
  volume title (FC's *Exegetic Homilies* for the Hexaemeron), plus strays by other authors
  misfiled under the father. Survey every title form, and search the url-less text for the
  work's name.

**Identifying**
- Identify each excerpt by its text, not its title: a rarity-weighted word overlap (windowed for
  long works) against every section of the father's works, then read the low scorers and every
  title/text disagreement. Different translations score low, and unrelated passages 0.3–0.5, so for
  loose paraphrases let the filing book or read-only judges decide. For an abridged edition, judge
  SAME / PARTIAL / ABSENT and keep excerpts of passages the edition lacks; keep excerpts of
  untranslated parts and of other works.

**Deleting**
- Delete by url, `--title-prefix`, `--titles-file` (exact titles: one may be a prefix of
  another; check no excerpt of another work shares one) or `--file-prefix` (a title shared by two
  works); an untitled block by hand, after checking the file. Bring every stray to the user.
- Make every deletion part of the ONE deletion commit (BASE): `import_checks.py oldranges` reads
  the old import as the blocks deleted in BASE (parsed at `BASE^`), so a block deleted in another
  commit is invisible to it.

**Comparing after the import** (Phase 5)
- `import_checks.py <Work> oldranges <BASE>` compares the old verse RANGES with the new blocks'
  parsed ranges (not filenames). It prints the verses only the old import covered (per old file
  in the book or in a new cross-ref file), the old blocks in other files (old cross-references
  the new import didn't make, or strays deleted with it), and old filenames that aren't KJV
  verses (read those by hand). Paste its output into the review.
- Judge every miss: genuine (a real exposition of that verse the import left out, or a range
  narrowed too far), covered (at a neighbouring verse, under the right number where the old
  file was misnumbered), or passing (a proof-text). With many misses, have read-only subagents
  judge them. Bring the genuine ones to the user, add them from the source (check the end
  punctuation), then restore source order (`import_checks.py <Work> order`; `--fix-order BASE`
  in the importers that have it).
- In a selective work, most misses turn out to be on the agents' left-out lists (chains of
  proof-texts, a verse used as one instance within the exposition of another).
