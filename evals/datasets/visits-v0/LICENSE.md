# visits-v0 licence

Everything committed here is synthetic. The five visit scripts (`synth/visits/`), the truth
JSON files (`visit_N.json`: transcript and medicine list) and `manifest.json` are written for
this project. The people in them are fictional. The medicine names are real generic or common
Indian brand names on purpose, because the spike tests whether a transcriber gets them right;
no patient data is involved. The committed text is released under CC0 1.0 (public domain
dedication): https://creativecommons.org/publicdomain/zero/1.0/

## The audio is not committed

The recordings are made with the macOS `say` command and three system voices (Rishi, Aman and
Tara), then mixed with noise generated in code. They live in `audio/`, which is git-ignored,
and `make visits` regenerates them on a Mac from the committed scripts.

The reason is Apple's licence. The macOS Tahoe 26 Software License Agreement, section 2F
("Voices; Live Captions"), allows the system voices for personal, non-commercial use and rules
out redistribution of their output, naming a "public sharing" context. This is a public repo,
so committing the audio could break that term. The scripts, the truth and the render settings
are enough to rebuild it. Check the agreement for your own macOS version before sharing audio
you render yourself.
