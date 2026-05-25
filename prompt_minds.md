# Prompt Minds — style prompts and the context they demand

> Purpose: brainstorm a wide, deliberately diverse (even silly) set of style
> prompts, then for each ask *"what would a scorer need to be able to see to
> play this well?"*. The point is **demand-driven API design**: the recurring
> capabilities tell us what the read-only board facade
> (`src/chess_mind_ai/readonly_board.py`) and the small set of precomputed
> scalar features must expose. See `docs/scorer-sandbox-design.md` for why we
> chose a read-only board facade (option C) over a fixed scalar list.
>
> Legend for "needs":
> - **prim** = already expressible from `ReadOnlyBoard` primitives + `chess`
>   helpers (square geometry, attackers/attacks, piece_at, history).
> - **scalar** = better served by a precomputed scalar feature (expensive or
>   fuzzy to compute inside a generated hot loop) — candidates for the hybrid
>   layer.
> - **gap** = not yet expressible; needs new capability.

## 1. Piece-fixation styles

1. "Play like a queen-obsessed maniac." → moving_piece_type, is_capture,
   gives_check, attackers near enemy king (**prim**); queen mobility/pressure
   (**scalar**, have analogues).
2. "Never move your queen until move 15." → own_move_count(QUEEN),
   fullmove_number (**prim**).
3. "Win with knights — maneuver them everywhere." → knight squares,
   attacks from knights, knight outposts (**prim** for moves; **scalar** for
   "is this square an outpost" = defended by own pawn, not attackable by enemy
   pawn).
4. "Bishops are sacred — never trade a bishop, keep the bishop pair." →
   piece_count(BISHOP, own), is_capture of own bishop after recapture
   (**prim**), bishop-pair flag (**scalar**, trivial).
5. "Rooks belong on open files — double them." → file occupancy by pawns,
   rook files (**prim**); "open/half-open file" (**scalar**, cheap).
6. "Promote a pawn to a knight whenever you can, for fun." → move.promotion
   (**gap**: facade doesn't surface promotion yet — add `promotion_piece(move)`).

## 2. Pawn play

7. "Advance your pawns aggressively (pawn storm)." → pawn squares + ranks via
   square_rank, pushes (**prim**); **pawn-advancement scalar** = sum of
   (rank advanced) over own pawns — the motivating example for option C.
8. "Build and keep a solid pawn chain; never create weaknesses." → pawn
   adjacency / defenders (**prim**); **isolated/doubled/backward pawn counts**
   (**scalar**).
9. "Only use your pawns to win if at all possible." → moving_piece_type==PAWN
   (**prim**).
10. "Race a passed pawn to promotion." → **passed-pawn detection scalar** (no
    enemy pawn on same/adjacent files ahead).
11. "Play the Stonewall: lock the center with pawns." → specific pawn squares
    (**prim**); center-lock heuristic (**scalar**).

## 3. King hunt / attacking

12. "Hunt the enemy king relentlessly." → king(enemy), attackers into the king
    zone, square_distance to king (**prim**); **king-zone attacker count
    scalar**.
13. "Sacrifice material for a mating attack." → material delta after move
    (**scalar**: material_balance), attackers near king (**prim**); relies on
    engine score + budget to keep it sane.
14. "Give checks at every opportunity (annoying)." → gives_check (**prim**).
15. "Castle early and keep your king behind a pawn shield." → is_castling,
    king square, pawns in front of king (**prim**); **king-safety scalar**.
16. "Open lines toward the enemy king even at a cost." → open files/diagonals
    toward king (**scalar**).

## 4. Territory / side control

17. "Only play on the queenside (files a–d)." → square_file of from/to,
    own piece distribution by file (**prim**).
18. "Dominate the center." → center squares occupancy/attacks (**prim**);
    **center-control scalar** (attacks on d4/e4/d5/e5).
19. "Play a hypermodern game: control the center from afar with pieces." →
    attacks into center without occupying it (**prim** + **scalar**).
20. "Cramp the opponent — take space, deny them squares." → count of squares
    attacked/occupied in enemy half (**scalar**: space metric).

## 5. Material / trades / sacrifice

21. "Trade everything, simplify to a won endgame." → total piece count, trade
    detection (**prim**); **material_balance scalar**.
22. "Avoid all trades for as long as possible." → is_capture, recapture
    likelihood (**prim**).
23. "Sacrifice the exchange for activity." → piece values of moved/captured,
    resulting activity (**scalar**).
24. "Be a gambit player: give a pawn for a lead in development." →
    **development scalar** (minor pieces off back rank), material delta.

## 6. Tempo / development / structure

25. "Develop every piece before move 10; no piece moves twice in the opening."
    → own_move_count per piece type, back-rank occupancy (**prim**);
    **development scalar**.
26. "Fianchetto both bishops and build a fortress." → specific bishop squares,
    pawn structure around them (**prim**).
27. "Play hyper-solid; minimize your weaknesses." → weakness counts (**scalar**:
    isolated/backward/hanging pieces).
28. "Always keep maximum piece mobility." → legal move counts by piece
    (**prim**, somewhat expensive) → **mobility scalar** preferred.

## 7. Psychological / meta / bizarre

29. "Play the most surprising reasonable move (anti-engine)." → relies on
    engine candidate ranking + style noise; needs candidate rank (**gap**:
    expose engine rank to scorer? or selector-level).
30. "Mirror the opponent's last move when legal." → move_history (**prim**).
31. "Always move toward the center of the board." → square geometry of to-square
    (**prim**).
32. "Keep the position as symmetric as possible." → board symmetry metric
    (**scalar/gap**).
33. "Shuffle pieces; avoid committing (waiting style)." → reversible moves,
    halfmove_clock (**prim**).
34. "Play for stalemate tricks when losing." → is_stalemate, near-stalemate
    (**prim** + engine score).
35. "Hoard your pieces in one corner like a dragon." → centralization /
    clustering metric for own pieces (**scalar**).

## 8. Endgame / phase-aware

36. "Rush to an endgame and use your king actively." → phase detection (piece
    count), king centralization (**scalar**: game_phase, king_activity).
37. "In the endgame, push passed pawns; in the middlegame, attack." →
    game_phase scalar + passed-pawn scalar.
38. "Keep the king safe in the middlegame, active in the endgame." →
    game_phase + king-safety + king-activity (**scalar**).

## 9. Opening-flavored

39. "Always fianchetto and play g3/Catalan-like setups." → specific squares,
    pawn on g3 (**prim**).
40. "Open with a wing gambit and attack on the flank you opened." → file/side
    tracking from history (**prim**).

---

## Derived capability summary

**Already covered by `ReadOnlyBoard` primitives + `chess` helpers** (most
prompts): piece location & type, color, king location, attackers/attacks/
defence, captures/checks/castling/en-passant, legality, square geometry
(file/rank/distance/name), move history, own-move counts by piece type,
fullmove/halfmove clocks, game-over states.

**Missing primitive to add (small):**
- `promotion_piece(move)` — surface `move.promotion` (prompts 6).

**High-value precomputed scalars for the hybrid layer** (expensive or fuzzy to
recompute per candidate; sorted by how many prompts want them):
1. `material_balance(color)` — own minus enemy material in pawns (13, 21, 23, 24).
2. `pawn_advancement(color)` — summed rank progress of own pawns (7, 10).
3. `king_safety(color)` — shelter/attacker-zone metric (12, 15, 27, 38).
4. `game_phase()` — opening/middlegame/endgame from material (36, 37, 38).
5. `mobility(color)` / `piece_mobility(type, color)` — legal-move volume (28, 16).
6. `center_control(color)` — attacks/occupancy of d4/e4/d5/e5 (18, 19).
7. `passed_pawns(color)`, `isolated_pawns`, `doubled_pawns`, `backward_pawns`
   (8, 10, 27).
8. `open_files()` / `half_open_files(color)` (5, 16).
9. `development(color)` — minors+queen developed off the back rank (24, 25).
10. `king_centralization(color)` — for endgame king activity (36, 38).
11. `space(color)` — squares controlled in enemy half (20).
12. `bishop_pair(color)` (4).

**Genuine gaps (need a design decision):**
- Engine candidate rank exposed to the scorer (29) — probably belongs at the
  selector level, not the context.
- Board-symmetry metric (32) — niche; defer.
- Clustering/"pieces in one corner" metric (35) — could be a generic
  `piece_centroid(color)` + spread; defer until a real prompt needs it.

### Convergence note

The diversity above collapses onto a **small** set: the primitives we already
have plus ~12 precomputed scalars cover the vast majority of prompts. This
validates option C — we are not adding one method per prompt; we are adding a
handful of general, composable features. The scalars (1–12) are the concrete
to-do for the hybrid layer; everything else composes from primitives.
