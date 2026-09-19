# Veltrix Loss Report

Analysed 7 games with critical positions, 48 critical plies. Teacher: self-teacher

## Category totals
- **TACTICAL_BLUNDER**: 4
- **MISSED_MATE**: 3
- **EVALUATION_ERROR**: 38
- **UNKNOWN**: 3

## Game 1 — result 1-0 (resign)

### ply 63 (end)
- CRITICAL POSITION: `3r4/4k1pp/R4p2/5P2/8/1b2p2P/1P4P1/2R3K1 w - - 0 33`
- MOVE: `c1c3` (stm: b)
- EVALUATION: own -173 → -272 cp | teacher: best 227 cp, after our move 278 cp
- TEACHER BEST: `a6a7` (depth 18)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-51cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `a6a7 e7f8 g1f1 b3d5 f1e2 d8e8 c1c7 d5b3`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 89 (end)
- CRITICAL POSITION: `8/7p/5Rb1/1Pk5/6P1/7P/3K4/8 w - - 1 46`
- MOVE: `b5b6` (stm: b)
- EVALUATION: own -606 → -708 cp | teacher: best 1187 cp, after our move 1570 cp
- TEACHER BEST: `b5b6` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-383cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `b5b6 g6e4 f6h6 e4c6 g4g5 c5b6 h6h7 b6a5`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 97 (end)
- CRITICAL POSITION: `8/5R1p/2b5/2k3P1/8/4K2P/8/8 w - - 2 50`
- MOVE: `f7h7` (stm: b)
- EVALUATION: own -719 → -934 cp | teacher: best 1120 cp, after our move 1587 cp
- TEACHER BEST: `f7h7` (depth 20)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-467cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `f7h7 c5d5 g5g6 d5e6 h3h4 c6d5 h4h5 e6f6`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 105 (end)
- CRITICAL POSITION: `8/R7/4k1P1/8/3K4/1b5P/8/8 w - - 5 54`
- MOVE: `a7a3` (stm: b)
- EVALUATION: own -1194 → -1445 cp | teacher: best 2023 cp, after our move 2267 cp
- TEACHER BEST: `a7a3` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-244cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `a7a3 e6f5 a3b3 f5g6 b3g3 g6f6 h3h4 f6e6`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

## Game 3 — result 0-1 (resign)

### ply 74 (mid)
- CRITICAL POSITION: `3rk1r1/p4p2/1pb1p3/3pP3/1RB3p1/P1B3P1/2P2P2/4R1K1 b - - 0 38`
- MOVE: `d5c4` (stm: w)
- EVALUATION: own 0 → -268 cp | teacher: best 251 cp, after our move 320 cp
- TEACHER BEST: `d5c4` (depth 22)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-69cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `d5c4 b4c4 c6f3 c4f4 g8h8 f4f3 g4f3 c3b4`
- LIKELY ROOT CAUSE: EVALUATION / NNUE missing feature (high)
- ATTRIBUTION: eval-first (train)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 110 (end)
- CRITICAL POSITION: `8/1k1r1p2/4pB2/1p5r/8/5pP1/5P2/5RK1 b - - 5 56`
- MOVE: `h5d5` (stm: w)
- EVALUATION: own -476 → -627 cp | teacher: best 666 cp, after our move 758 cp
- TEACHER BEST: `h5d5` (depth 22)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-92cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `h5d5 g3g4 d5d1 f1d1 d7d1 g1h2 d1d2 h2g3`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 128 (end)
- CRITICAL POSITION: `8/5p2/2k1p3/8/6P1/4K3/1B1r1P2/8 b - - 0 65`
- MOVE: `d2b2` (stm: w)
- EVALUATION: own -781 → -951 cp | teacher: best 1135 cp, after our move 1190 cp
- TEACHER BEST: `d2b2` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-55cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `d2b2 e3e4 b2f2 e4e3 f2a2 e3f4 a2d2 f4g5`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 130 (end)
- CRITICAL POSITION: `8/5p2/2k1p3/8/6P1/4KP2/1r6/8 b - - 0 66`
- MOVE: `b2b4` (stm: w)
- EVALUATION: own -951 → -1093 cp | teacher: best 2013 cp, after our move 2075 cp
- TEACHER BEST: `c6d5` (depth 23)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-62cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `c6d5 e3f4 b2b3 g4g5 b3b4 f4e3 d5e5 e3d3`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

## Game 5 — result 1-0 (resign)

### ply 85 (mid)
- CRITICAL POSITION: `6k1/1r1r1pp1/p1q4p/Pbp1P3/3p4/1B1P2RP/1P3QP1/5RK1 w - - 2 44`
- MOVE: `f2f4` (stm: b)
- EVALUATION: own -128 → -223 cp | teacher: best 622 cp, after our move 215 cp
- TEACHER BEST: `e5e6` (depth 18)
- CATEGORY: **TACTICAL_BLUNDER**
- WHY: Teacher refutes the played move outright: its best line leaves us 407cp worse than the alternative. Single-position collapse - our own eval (-128cp) did not foresee it.
- PV: `e5e6 f7e6 f2f8 g8h7 f1f6 d7d8 f8d8 c6e8`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Add position to tests/loss_regression.epd (done automatically) and emit weighted teacher-labelled training row (done). If regression EPD grows on this category, inspect SEE/quiet checks in quiescence before touching eval.

### ply 91 (mid)
- CRITICAL POSITION: `6k1/1r1r1pp1/p6p/P3P3/2qp1Q2/6RP/1P4P1/5RK1 w - - 0 47`
- MOVE: `f4h6` (stm: b)
- EVALUATION: own -372 → -628 cp | teacher: best 658 cp, after our move 748 cp
- TEACHER BEST: `f4h6` (depth 19)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-90cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `f4h6 f7f6 f1c1 c4c1 h6c1 f6e5 c1c4 d7f7`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 105 (end)
- CRITICAL POSITION: `2Q5/4rrpk/p7/P3p3/3p4/5R1P/1P4P1/6K1 w - - 8 54`
- MOVE: `f3f7` (stm: b)
- EVALUATION: own -780 → -900 cp | teacher: best 959 cp, after our move 1011 cp
- TEACHER BEST: `f3f7` (depth 18)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-52cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `f3f7 e7f7 c8a6 f7c7 a6e2 c7c5 b2b4 c5c1`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 113 (end)
- CRITICAL POSITION: `8/r5pk/P1Q5/4p3/8/3p3P/1P4P1/6K1 w - - 0 58`
- MOVE: `c6e4` (stm: b)
- EVALUATION: own -1008 → -1108 cp | teacher: best 1287 cp, after our move 1592 cp
- TEACHER BEST: `c6e4` (depth 20)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-305cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `c6e4 g7g6 e4d3 h7g7 b2b4 g7h7 d3e4 a7g7`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

## Game 6 — result 0-1 (resign)

### ply 29 (mid)
- CRITICAL POSITION: `3rk2r/pp2p1b1/2pqb1pp/7n/2BP4/8/PPPBQPPP/R3R1K1 w k - 0 16`
- MOVE: `c4e6` (stm: b)
- EVALUATION: own -151 → -243 cp | teacher: best 343 cp, after our move 376 cp
- TEACHER BEST: `c4e6` (depth 16)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-33cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `c4e6 h8f8 e2g4 f8f6 e1e4 g7f8 a1d1 f8g7`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 51 (mid)
- CRITICAL POSITION: `3B3r/3R2bk/2p1R1p1/1p1n3p/8/8/P1P2PPP/6K1 w - - 0 27`
- MOVE: `e6c6` (stm: b)
- EVALUATION: own -465 → -575 cp | teacher: best 583 cp, after our move 641 cp
- TEACHER BEST: `h2h4` (depth 19)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-58cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `h2h4 h8g8 e6c6 d5c3 d7g7 g8g7 c6c3 h7g8`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 81 (end)
- CRITICAL POSITION: `8/8/1n4k1/7R/8/P7/2P2PPP/5K2 w - - 1 42`
- MOVE: `h5c5` (stm: b)
- EVALUATION: own -820 → -970 cp | teacher: best 1172 cp, after our move 1335 cp
- TEACHER BEST: `h5c5` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-163cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `h5c5 g6f7 h2h4 f7e7 c5c7 e7d6 c7b7 b6c4`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 83 (end)
- CRITICAL POSITION: `8/3n4/6k1/2R5/8/P7/2P2PPP/5K2 w - - 3 43`
- MOVE: `c5b5` (stm: b)
- EVALUATION: own -970 → -1161 cp | teacher: best 1375 cp, after our move 1548 cp
- TEACHER BEST: `c5b5` (depth 22)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-173cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `c5b5 d7f8 a3a4 f8e6 a4a5 g6f6 a5a6 e6c7`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

## Game 7 — result 1-0 (resign)

### ply 57 (mid)
- CRITICAL POSITION: `6k1/1prq1b1p/5Qp1/3B1p2/p1P5/8/PP3PPP/4R1K1 w - - 2 30`
- MOVE: `h2h3` (stm: b)
- EVALUATION: own -186 → -283 cp | teacher: best 267 cp, after our move 257 cp
- TEACHER BEST: `g2g3` (depth 16)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (10cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `g2g3 f7d5 c4d5 d7c8 d5d6 c7c1 e1c1 c8c1`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 107 (end)
- CRITICAL POSITION: `8/7p/6p1/6P1/P1k5/6K1/5P2/8 w - - 0 55`
- MOVE: `g3f4` (stm: b)
- EVALUATION: own -341 → -714 cp | teacher: best 1423 cp, after our move 1583 cp
- TEACHER BEST: `g3f4` (depth 24)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-160cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `g3f4 c4d4 a4a5 d4d5 f4e3 d5c6 e3e4 c6b5`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 109 (end)
- CRITICAL POSITION: `8/7p/6p1/3k2P1/P4K2/8/5P2/8 w - - 2 56`
- MOVE: `f4e3` (stm: b)
- EVALUATION: own -714 → -1045 cp | teacher: best 1542 cp, after our move 1089 cp
- TEACHER BEST: `a4a5` (depth 25)
- CATEGORY: **TACTICAL_BLUNDER**
- WHY: Teacher refutes the played move outright: its best line leaves us 453cp worse than the alternative. Single-position collapse - our own eval (-714cp) did not foresee it.
- PV: `a4a5 d5c5 f4e5 c5b5 e5f6 b5a5 f6g7 a5b4`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Add position to tests/loss_regression.epd (done automatically) and emit weighted teacher-labelled training row (done). If regression EPD grows on this category, inspect SEE/quiet checks in quiescence before touching eval.

### ply 115 (end)
- CRITICAL POSITION: `8/7p/2k3p1/P5P1/3K4/8/5P2/8 w - - 1 59`
- MOVE: `d4c4` (stm: b)
- EVALUATION: own -1071 → -1180 cp | teacher: best 1590 cp, after our move 1645 cp
- TEACHER BEST: `d4c4` (depth 25)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-55cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `d4c4 c6d6 c4b5 d6e5 a5a6 e5f5 a6a7 f5g5`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

## Game 12 — result 0-1 (resign)

### ply 78 (end)
- CRITICAL POSITION: `6k1/5pp1/1p5p/4P3/6b1/1N6/3r4/5B1K b - - 0 40`
- MOVE: `d2d1` (stm: w)
- EVALUATION: own -865 → -988 cp | teacher: best 974 cp, after our move 1082 cp
- TEACHER BEST: `d2d1` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-108cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `d2d1 h1g2 g4e6 f1e2 e6b3 g2f3 b3d5 f3e3`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 88 (end)
- CRITICAL POSITION: `6k1/5p2/1p5p/4P1p1/8/1b6/4BK2/r7 b - - 1 45`
- MOVE: `a1a3` (stm: w)
- EVALUATION: own -1052 → -1214 cp | teacher: best 1319 cp, after our move 1779 cp
- TEACHER BEST: `a1a5` (depth 19)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-460cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `a1a5 e2d3 a5e5 d3f1 b3d5 f2g3 f7f5 f1a6`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 90 (end)
- CRITICAL POSITION: `6k1/5p2/1p5p/4P1p1/8/rb6/4B1K1/8 b - - 3 46`
- MOVE: `b3e6` (stm: w)
- EVALUATION: own -1214 → -1305 cp | teacher: best 1984 cp, after our move 1851 cp
- TEACHER BEST: `b3d5` (depth 22)
- CATEGORY: **UNKNOWN**
- WHY: Teacher prefers b3d5 by 133cp over the played b3e6; our scoring underestimated the reply.
- PV: `b3d5 g2f2 d5e6 e2f3 g5g4 f3b7 g4g3 f2e2`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Row emitted with moderate weight; monitor category counts.

### ply 92 (end)
- CRITICAL POSITION: `6k1/5p2/1p2b2p/4P1p1/8/r4B2/6K1/8 b - - 5 47`
- MOVE: `g5g4` (stm: w)
- EVALUATION: own -1305 → -1729 cp | teacher: best 2111 cp, after our move 1596 cp
- TEACHER BEST: `e6h3` (depth 23)
- CATEGORY: **TACTICAL_BLUNDER**
- WHY: Teacher refutes the played move outright: its best line leaves us 515cp worse than the alternative. Single-position collapse - our own eval (-1305cp) did not foresee it.
- PV: `e6h3 g2f2 g5g4 f3d5 g4g3 f2e2 a3a5 d5h1`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Add position to tests/loss_regression.epd (done automatically) and emit weighted teacher-labelled training row (done). If regression EPD grows on this category, inspect SEE/quiet checks in quiescence before touching eval.

## Game 13 — result 0-1 (resign)

### ply 38 (mid)
- CRITICAL POSITION: `1r3rk1/7p/p1n1p1p1/qBp5/P1PpP3/8/1KQ2PPP/3R3R b - - 0 20`
- MOVE: `c6b4` (stm: w)
- EVALUATION: own -471 → -571 cp | teacher: best 853 cp, after our move 711 cp
- TEACHER BEST: `d4d3` (depth 17)
- CATEGORY: **UNKNOWN**
- WHY: Teacher prefers d4d3 by 142cp over the played c6b4; our scoring underestimated the reply.
- PV: `d4d3 c2d3 a6b5 b2c1 a5a4 d3c2 a4a3 c2b2`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Row emitted with moderate weight; monitor category counts.

### ply 50 (mid)
- CRITICAL POSITION: `1r4k1/2q4p/p3p1p1/1Bp5/P1PpP3/1Qn2R2/6rP/2K2R2 b - - 1 26`
- MOVE: `c7e5` (stm: w)
- EVALUATION: own -686 → -869 cp | teacher: best 926 cp, after our move 1054 cp
- TEACHER BEST: `c7e5` (depth 17)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-128cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `c7e5 f3f2 g2f2 f1f2 e5e4 f2d2 a6b5 c4b5`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.

### ply 58 (mid)
- CRITICAL POSITION: `1r4k1/7p/4p1p1/1Pp5/P2pq3/1Qn5/3R3P/2K5 b - - 1 30`
- MOVE: `e4e1` (stm: w)
- EVALUATION: own -991 → -1088 cp | teacher: best 1990 cp, after our move 1262 cp
- TEACHER BEST: `b8f8` (depth 19)
- CATEGORY: **TACTICAL_BLUNDER**
- WHY: Teacher refutes the played move outright: its best line leaves us 728cp worse than the alternative. Single-position collapse - our own eval (-991cp) did not foresee it.
- PV: `b8f8 a4a5 f8f1 c1b2 f1b1 b2a3 b1b3 a3b3`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Add position to tests/loss_regression.epd (done automatically) and emit weighted teacher-labelled training row (done). If regression EPD grows on this category, inspect SEE/quiet checks in quiescence before touching eval.

### ply 64 (end)
- CRITICAL POSITION: `1r4k1/7p/4p1p1/1Pp5/P2p4/4q3/2K4P/3Q4 b - - 2 33`
- MOVE: `e3c3` (stm: w)
- EVALUATION: own -1104 → -1361 cp | teacher: best 2438 cp, after our move 99990 cp
- TEACHER BEST: `e3c3` (depth 21)
- CATEGORY: **EVALUATION_ERROR**
- WHY: Disagreement is small (-97552cp) but the game still collapsed from here; likely cumulative pressure or a search artifact.
- PV: `e3c3 c2b1 b8f8 d1g1 c3b3 b1a1 b3a4 a1b1`
- LIKELY ROOT CAUSE: unknown - needs manual review (low)
- ATTRIBUTION: search-time-first (diagnose search before training heavily)
- LEARNING ACTION: Emit teacher-labelled row with high weight (done). These rows steer the NNUE toward the missed static feature without hardcoding the move.
