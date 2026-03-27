"""Adaptive, information-aware player.

Adjusts behavior based on game phase, hand quality, and opponent activity.
Commits at the right time and cuts losses early. Draws from discard piles
when they beat expected deck value, and manages tempo (stall vs. push).

See BROB_POLICY.md for full decision policy.
"""

from classes import *
from utils import *
from players.brob_utils import (
    playable_in_hand,
    expedition_score,
    expedition_projected_score,
    cards_to_bonus,
    suit_potential,
    is_expedition_viable,
    game_phase,
    card_value_for_me,
    best_available_draw,
    deny_draw_value,
    hand_deadwood,
    smart_discard_score,
    discard_danger,
    opponent_committed_suits,
    opponent_needs_from_discard,
    should_stall,
    contract_value,
    remaining_above,
    deck_cards_remaining,
    tempo_advantage,
)


class Brob(Player):
    @classmethod
    def get_name(cls):
        return 'brob'

    def play(self, r):
        me = r.whose_turn
        hand = r.h[me].cards
        flags = r.flags
        phase = game_phase(flags, hand)

        # --- Identify candidates ---
        playable = [c for c in hand if is_playable(c, flags[c[0]].played[me])]
        deadwood = hand_deadwood(hand, flags, me)

        # --- Choose action (play or discard) ---
        best_play = self._choose_play(playable, flags, hand, me, phase)

        if best_play:
            card = best_play
            is_disc = False
        else:
            card = self._choose_discard(hand, deadwood, flags, me)
            is_disc = True

        # --- Choose draw ---
        draw = self._choose_draw(card, is_disc, flags, hand, me, phase)

        return card, is_disc, draw

    # ------------------------------------------------------------------
    # Play selection
    # ------------------------------------------------------------------

    def _choose_play(self, playable, flags, hand, me, phase):
        if not playable:
            return None

        scored = []
        for card in playable:
            score = self._score_play(card, flags, hand, me, phase)
            scored.append((card, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        best_card, best_score = scored[0]

        # In late game, only play if it's actually beneficial
        if phase > 0.7 and best_score < 0:
            return None

        # In early/mid game, still require a minimum threshold
        if best_score < -5:
            return None

        return best_card

    def _score_play(self, card, flags, hand, me, phase):
        suit = card[0]
        played = flags[suit].played[me]
        score = 0.0

        is_new_expedition = len(played) == 0
        is_contract = card[1] == '0'

        # --- Sequential bonus (Priority 1) ---
        if played:
            highest = int(played[-1][1])
            card_val = int(card[1])
            if not is_contract:
                gap = card_val - highest - 1
                if gap == 0:
                    score += 15  # Sequential: very strong
                elif gap == 1:
                    score += 8
                elif gap == 2:
                    score += 3
                else:
                    score -= gap * 2  # Penalize large gaps
            else:
                # Contract on an already-started expedition (must be first cards)
                score += 5

        # --- Face value contribution ---
        if not is_contract:
            face_val = int(card[1]) + 1
            score += face_val * 0.5

        # --- Multiplier bonus for suited expeditions with contracts ---
        n_contracts = sum(1 for c in played if c[1] == '0')
        if n_contracts > 0 and not is_contract:
            score += n_contracts * 3

        # --- Bonus chase (Priority: high) ---
        needed = cards_to_bonus(suit, flags, me)
        hand_in_suit = playable_in_hand(suit, hand, flags, me)
        remaining = remaining_above(suit, flags, hand, me)
        total_available = len(played) + len(hand_in_suit) + len(remaining)

        if 0 < needed <= 3 and total_available >= BONUS_THRESHOLD:
            score += (4 - needed) * 5  # Closer to bonus = bigger boost

        # --- New expedition evaluation (Priority 3) ---
        if is_new_expedition:
            if is_contract:
                cv = contract_value(suit, hand, flags, me)
                if phase < 0.3 and len(hand_in_suit) >= 3:
                    score += max(0, cv * 0.3)
                elif phase < 0.5 and len(hand_in_suit) >= 2:
                    score += max(0, cv * 0.2)
                else:
                    score -= 10  # Too late or too few supporting cards
            else:
                viability = is_expedition_viable(suit, flags, hand, me)
                if phase < 0.4 and viability > 5:
                    score += viability * 0.5
                elif phase < 0.6 and viability > 10:
                    score += viability * 0.3
                else:
                    score -= 8  # Don't open late without strong hand

        # --- Expedition health check ---
        if played:
            projected = expedition_projected_score(suit, flags, hand, me)
            if projected < -15:
                score -= 10  # Expedition is deeply negative, stop investing
            elif projected < 0:
                score -= 3

        # --- Suit potential upside ---
        potential = suit_potential(suit, flags, hand, me)
        if potential > 30:
            score += 3
        if potential > 50:
            score += 3

        return score

    # ------------------------------------------------------------------
    # Discard selection
    # ------------------------------------------------------------------

    def _choose_discard(self, hand, deadwood, flags, me):
        # Prefer deadwood
        if deadwood:
            # Among deadwood, pick least dangerous to discard
            deadwood.sort(key=lambda c: discard_danger(c, flags, me))
            return deadwood[0]

        # Score all cards for discard quality
        scored = [(c, smart_discard_score(c, flags, hand, me)) for c in hand]
        scored.sort(key=lambda x: x[1])  # Lower = better to discard

        # Check if best discard feeds the opponent
        opp_needs = set(c[0] for c in opponent_needs_from_discard(flags, me))
        best = scored[0]
        if best[0][0] in opp_needs and len(scored) > 1:
            # Try second-best if it's in a safer suit
            for card, sc in scored[1:]:
                if card[0] not in opp_needs:
                    return card
                # If danger difference is small, still prefer the safer option
                if sc - best[1] < 3:
                    return card

        return scored[0][0]

    # ------------------------------------------------------------------
    # Draw selection
    # ------------------------------------------------------------------

    def _choose_draw(self, played_card, is_discard, flags, hand, me, phase):
        discard_suit = played_card[0] if is_discard else None

        # Get discard pile draws that beat deck EV
        candidates, deck_ev = best_available_draw(flags, hand, me)

        # Also check denial draws
        opp_committed = opponent_committed_suits(flags, me)
        denial_candidates = []
        for suit in SUITS:
            discards = flags[suit].discards
            if discards:
                top = discards[-1]
                dv = deny_draw_value(top, flags, hand, me)
                if dv > 8 and is_playable(top, flags[suit].played[me]):
                    # Worth denying AND playable for us
                    denial_candidates.append((top, dv))

        # Merge candidates, preferring value draws but including denial
        all_draws = []
        seen = set()
        for card, val in candidates:
            all_draws.append((card, val, 'value'))
            seen.add(card)
        for card, val in denial_candidates:
            if card not in seen:
                all_draws.append((card, val * 0.5, 'denial'))  # Discount denial

        # Filter out the suit we just discarded into
        if discard_suit:
            all_draws = [(c, v, t) for c, v, t in all_draws if c[0] != discard_suit]

        # Tempo consideration: if stalling, lower the bar for discard draws
        stalling = should_stall(flags, hand, me)
        if stalling and not all_draws:
            # Accept any playable discard draw to preserve deck
            for suit in SUITS:
                if suit == discard_suit:
                    continue
                discards = flags[suit].discards
                if discards:
                    top = discards[-1]
                    if is_playable(top, flags[suit].played[me]):
                        all_draws.append((top, 0, 'stall'))

        # If pushing tempo (ahead), prefer deck draws
        advantage = tempo_advantage(flags, hand, me)
        if phase > 0.5 and advantage > 15 and not stalling:
            # Only take discard draws if they're really good
            all_draws = [(c, v, t) for c, v, t in all_draws if v > deck_ev * 1.5]

        if all_draws:
            all_draws.sort(key=lambda x: x[1], reverse=True)
            return all_draws[0][0]

        return 'deck'
