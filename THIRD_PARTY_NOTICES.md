# Third-Party Notices

Veltrix 1.0 is written from scratch for this project. It contains **no code
copied from Stockfish** (or from any other engine). The items below are the
only third-party material referenced, together with their licenses.

## 1. Polyglot opening-book format constants
**File:** `engine/src/polyglot_random.h`
**Contents:** the 781-entry table of 64-bit random numbers that defines the
Polyglot/Zobrist key convention used by the Polyglot opening-book format
(the binary `.bin` books such as our `books/veltrix.bin`).

**Origin / license:** the constant table dates from the original Polyglot
program by Fonzy Huiskens and was popularized by Fabien Letouzey's *Fruit*
family (GPL). The same table is re-published, under the GPL-3.0, by many
projects, including the `python-chess` library by Niklas Fiekas
(GPL-3.0-or-later), from which this header was cross-checked
(https://github.com/niklasf/python-chess).

Veltrix itself is licensed GPL-3.0-or-later (see `LICENSE`), so incorporation
of the table is license-compatible and attribution is preserved here.

**Chess rule:** the hash convention (piece/turn/castle/en-passant rules) is a
public interoperability convention, not copyrightable per se.

## 2. PeSTO-style tapered piece-square tables
**File:** `engine/src/psqt.h`
**Contents:** middlegame/endgame piece-square values following the scheme
popularized by Róbert Csordás's *PeSTO* (Pawel's simplified evaluation
tables, tuned from Fruit-derived values).

**Origin / license:** The PeSTO tables are widely published (e.g. on the
Chess Programming Wiki) and explicitly released into the **public domain /
CC0** by their author. Veltrix's tables were re-derived and re-scaled for
this engine (values are scaled to centipawns with our own taper); credit is
given as a courtesy.

## 3. General engine techniques
The search and evaluation techniques implemented (alpha-beta, principal
variation search, iterative deepening, aspiration windows, transposition
table with Zobrist hashing, null-move pruning, late move reductions,
futility/reverse-futility pruning, static-exchange evaluation, quiescence
search, killer/history/counter-move move ordering, singular extensions,
lazy-SMP multithreading, Polyglot books) are long-standing public-domain
algorithms described by the Chess Programming Wiki community. No source
code from any engine was used.

## 4. Python standard library / tkinter
The GUI and tools use only the Python 3 standard library (including tkinter,
which ships with CPython under the PSF License). No third-party Python
packages are required.

---

If you redistribute Veltrix, you must keep this file and `LICENSE` intact.
