Each folder in this project is made up of toml files containing commentaries by church fathers on a specific section of scripture (denoted by the filename). We prefer files that cover small verse ranges (or individual verses) to larger ranges - for example, it's better to have three files for John 1_1, John 1_2, and John 1_3 than it is to have one file for John 1_1-3... so long as the commentaries can be split up without losing meaning.

Note that a single .toml file can contain multiple commentaries inside of it, each one having it's own source url / source title. Put another way, a single toml file might have one commentary with a source title / source url properly filled out, and then another commentary in the same file missing that data.

All root folders are church father names in a full form.

Before writing to any file, check if a file with that name already exists. If it does, APPEND the commentary as an additional [[commentary]] section rather than overwriting. Only create a new file if no file exists for that verse.

It's OK (and desired) to use the same quote text in multiple verse files when it serves as commentary on more than one verse. Readers browsing one verse won't also see the other, so duplication helps rather than hurts. When a passage makes a theological argument relevant to multiple verses, include the full passage in each file rather than splitting it artificially.

All filenames are of the format "1 John 1_2" (for 1 John 1:2) or "1 John 1_4-10" (for 1 John 1:4-10). We do not put a/b on verses in filenames (e.g. we do not do "Mark 3_2b"). We don't put anything else in filenames, the filenames are parsed to extract the verse that commentary inside the file is referring to.

A filename is a claim about scope: it must name exactly the verse(s) the commentary inside actually addresses. Use a single-verse filename (e.g. "Romans 4_18") only when the commentary is confined to that one verse; if a passage expounds several verses as one argument, name the file for the full range it covers (e.g. "Romans 4_18-22"). Do not file range-spanning commentary under a single verse — that both mislabels the scope and leaves the other verses with no file at all. "Prefer smaller ranges" means pick the smallest range that is still accurate, never a range narrower than the text it holds.

Source URLs pointing to historicalchristian.faith are also available in your Writings-Database checkout (e.g. ~/Desktop/Writings-Database/), if it's helpful to refer to the source text for any reason. For example https://historicalchristian.faith/by_father.php?file=Cyril%2520of%2520Alexandria%2FFive%2520tomes%2520against%2520Nestorius%2FBook%25201.html maps to ~/Desktop/Writings-Database/Cyril\ of\ Alexandria/Five\ tomes\ against\ Nestorius/Book\ 1.html 

If the user instructs you to "flesh out this context" (or similar) and passes in a father name / verse... find the commentary associated with that father name and verse and read it. Then go to it's source url in your Writings-Database checkout (e.g. ~/Desktop/Writings-Database/) and find the context surrounding it. See if you can enhance the commentary by pulling some of the existing surrounding context around the quote that ties to the same concept/commentary.

Always use KJV verse numberings - deuterocanonical books are valid (they are in the early KJV bibles).

For the list of accepted book names and their exact spellings, refer to book_names.json in the project root. Use only names from that list in filenames.