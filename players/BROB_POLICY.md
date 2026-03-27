# Brob Player — Decision Policy

## Philosophy

Brob is an **adaptive, information-aware** player. Rather than following a single rigid
strategy, brob adjusts behavior based on game phase, hand quality, and opponent activity.
The core tension in Lost Cities is **commitment vs. flexibility**: every card you play
locks you into an expedition that might go negative, but waiting too long means you miss
the cards you need. Brob tries to commit at the right time and cut losses early.

---

## Turn Structure

Each turn has two decisions:
1. **Action**: Play a card to an expedition, OR discard a card
2. **Draw**: Draw from the deck, OR pick up from a discard pile

These are evaluated together since the draw choice can depend on what you played/discarded
(you can't draw from the suit you just discarded into).

---

## Phase Definitions

- **Early game** (phase 0.0–0.3): ~20+ cards in deck. Gathering information, making
  commitments cautiously.
- **Mid game** (phase 0.3–0.7): Expeditions are established. Playing to extend them,
  discarding abandoned suits.
- **Late game** (phase 0.7–1.0): Few draws left. Maximize what you have, minimize
  negative expeditions, chase bonuses if close.

---

## Action Policy (Play vs. Discard)

### Priority 1: Extend existing expeditions (all phases)

If you have a card that is **sequential** (exactly 1 above your highest played card in
a started expedition), play it. This is almost always correct because:
- No gap means no skipped opportunity
- Extends card count toward the 8-card bonus
- Keeps the expedition's momentum

If multiple sequential plays exist, prefer the suit with:
- More contracts played (higher multiplier)
- Closer to the 8-card bonus
- Higher suit_potential

### Priority 2: Play small-gap cards in committed suits (all phases)

If no sequential play exists but you have playable cards in started expeditions with a
small gap (1–2 cards skipped), play them. Prefer smaller gaps. In early/mid game this
is fine; in late game, be more cautious about gaps since you have fewer draws to fill them.

### Priority 3: Open new expeditions (early/mid game only)

Open a new expedition when ALL of:
- You hold a contract + at least 2 numbered cards in the suit, OR you hold 3+ numbered
  cards with a clear path to breakeven
- `is_expedition_viable()` returns positive
- The opponent hasn't already built a strong position in this suit that would make your
  investment pointless (check `opponent_suit_potential`)
- It's early enough that you can realistically draw into it

**Contract timing**: Play contracts early when you have strong supporting cards. A contract
in the first third of the game with 3+ supporting cards is a strong play. A contract in
the last third is almost never worth it unless the expedition is already started.

### Priority 4: Play any viable card (mid/late game)

If you have playable cards in started expeditions, play the best one even with a larger
gap, as long as the expedition stays profitable or near-profitable. In the late game,
playing a card that keeps you above breakeven is better than discarding.

### Priority 5: Discard (fallback)

When nothing is worth playing:

1. **Discard deadwood first** — cards below your played threshold that can never be played.
2. **Then discard by `smart_discard_score`** — balancing:
   - Low danger to opponent (they can't play it, or it's worth little to them)
   - Low information leak (doesn't reveal your strategy)
   - Low value to you (you've abandoned this suit)
3. **Avoid discarding into suits the opponent needs** — check
   `opponent_needs_from_discard()`. If your best discard feeds the opponent, consider
   whether a suboptimal discard in a safer suit is better.
4. **Avoid discarding contracts** — contracts in the discard pile are gold for the
   opponent. Discard numbered cards before contracts unless the suit is truly dead.

---

## Draw Policy

### Rule 1: Compare discard draws against deck EV

Use `best_available_draw()` to find discard pile cards that beat the expected value of a
random deck draw. If any exist, draw the best one.

### Rule 2: Consider denial draws

Even if a discard pile card isn't great for you, check `deny_draw_value()`. If the
opponent desperately needs it (high value, sequential for them, they have contracts),
consider drawing it to block them — but only if it's at least marginally useful to you
(playable, not pure deadwood).

### Rule 3: Tempo-aware deck draws

- If `should_stall()` is true, prefer drawing from discard piles (even marginal ones)
  to preserve the deck.
- If you're ahead and want to end the game, prefer drawing from the deck to deplete it.

### Rule 4: Don't draw from the suit you just discarded into

This is a game rule, but it also means: when choosing what to discard, consider whether
you want to draw from that suit's discard pile. If so, discard something else.

### Rule 5: Stall/acceleration integration

In the late game:
- **Ahead**: Draw from deck aggressively. You want the game to end.
- **Behind**: Draw from discard piles whenever remotely useful. Buy more turns.
- **Chasing bonus**: Draw from discard piles to preserve deck, giving you more turns
  to find the cards you need for the 8-card threshold.

---

## Special Situations

### The 8-card bonus chase

The +20 bonus for 8+ cards in a suit is massive, especially with contracts (a 2x
multiplied expedition going from 7 to 8 cards gains +20 bonus on top of the card's
own value). Brob should:

- Track `cards_to_bonus()` actively
- When within 2–3 cards of bonus in a suit, prioritize that suit heavily
- Consider stalling to draw more cards for that suit
- Be willing to make slightly suboptimal plays elsewhere to chase the bonus

### Opponent blocking

When the opponent has committed heavily to a suit (3+ cards, especially with contracts):
- Avoid discarding playable cards in that suit
- Consider denial draws from that suit's discard pile
- In extreme cases (opponent has 2 contracts + several cards), actively holding cards
  they need is valuable even if those cards are mediocre for you

### Abandoning an expedition

If you've started an expedition but it's going negative and you can't realistically
reach breakeven:
- Stop playing into it — the multiplier amplifies losses
- Accept the sunk cost; don't throw good cards after bad
- The exception: if you're at 5-6 cards and the bonus would flip you positive, chase it

### Contract decisions

Contracts are the highest-variance decision in the game:
- **Play early** if: you hold 3+ cards in the suit, suit_potential is high,
  game_phase < 0.3
- **Hold for later** if: you have 1-2 supporting cards but lots of remaining_above
  cards — you might draw into it
- **Discard (reluctantly)** if: game_phase > 0.6, you have no supporting cards, and
  the suit is clearly dead for you
- **Never discard** if: the opponent could use it (always check discard_danger)

---

## Decision Flow Summary

```
On each turn:
  1. Identify all playable cards and all deadwood
  2. Score each playable card by: gap size, expedition viability, bonus proximity
  3. Score each discard candidate by: smart_discard_score
  4. Pick the best action (play or discard)
  5. Evaluate draw options:
     a. Get best_available_draw (discard draws beating deck EV)
     b. Check deny_draw_value for opponent-blocking draws
     c. Factor in tempo (stall vs. push)
     d. Respect the "can't draw from discarded suit" constraint
  6. Return (card, is_discard, draw_source)
```

---

## Known Limitations of Current Utils

These are approximations we may need to tune:

- `card_value_for_me` uses fixed weights for gap bonuses and multiplier scaling;
  these should probably be phase-dependent
- `expected_value_deck_draw` treats all unseen cards equally (can't distinguish deck
  from opponent's hand) — this is inherent to imperfect info but means the EV is an
  average over both pools
- `is_expedition_viable` weights are arbitrary (0.6/0.2/0.2) and need tuning
- `contract_value` uses a 30% discount for remaining cards, which is a rough estimate
  of draw probability
- `should_stall` has hardcoded thresholds (-10 point deficit, 5+ cards for bonus chase)
  that may need adjustment
- Information leak scoring is rudimentary — a real model would track what the opponent
  can infer from your discard pattern over multiple turns
