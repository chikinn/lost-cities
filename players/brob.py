"""Adaptive, information-aware player.

Core play logic: minimize gap (proven by Committer to be the strongest
single heuristic). On top of that, adds smart draw selection (EV comparison
against deck), opponent-aware discarding, and tempo management.

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


def minimize_gap_scored(cards, flags, me):
    """Return cards sorted by gap size (ascending), with gap info.
    Like Committer's minimize_gap but returns all candidates scored."""
    results = []
    for c in cards:
        baseline = -1
        played = flags[c[0]].played[me]
        if played:
            baseline = int(played[-1][1])

        values_left = [x for x in CARDS if int(x) >= baseline]
        if baseline == 0:
            values_left = values_left[1:]

        opponent_played = flags[c[0]].played[1 - me]
        discards = flags[c[0]].discards[:-1]

        for other_c in opponent_played + discards:
            v = other_c[1]
            if v in values_left:
                values_left.remove(v)

        gap = values_left.index(c[1]) if c[1] in values_left else len(values_left)
        results.append((c, gap))

    results.sort(key=lambda x: x[1])
    return results


class Brob(Player):
    @classmethod
    def get_name(cls):
        return 'brob'

    def play(self, r):
        me = r.whose_turn
        hand = r.h[me].cards
        flags = r.flags
        phase = game_phase(flags, hand)

        playable = [c for c in hand if is_playable(c, flags[c[0]].played[me])]

        draw = 'deck'

        if playable:
            # --- Core: pick play by gap, with tiebreakers ---
            card = self._choose_play(playable, flags, hand, me, phase)

            # --- Draw: check if a discard draw improves our hand ---
            # Compare the second-best play's gap against available discard draws
            draw = self._choose_draw_after_play(card, flags, hand, me, phase)

            return card, False, draw
        else:
            # --- Forced discard ---
            card = self._choose_discard(hand, flags, me)

            # --- Draw: pick best available, avoiding discarded suit ---
            draw = self._choose_draw_after_discard(card, flags, hand, me, phase)

            return card, True, draw

    def _choose_play(self, playable, flags, hand, me, phase):
        """Pick the best card to play using gap minimization + tiebreakers."""
        scored = minimize_gap_scored(playable, flags, me)

        if len(scored) == 1:
            return scored[0][0]

        best_gap = scored[0][1]
        # Collect all cards tied at the best gap
        tied = [c for c, g in scored if g == best_gap]

        if len(tied) == 1:
            return tied[0]

        # Tiebreakers among cards with equal gap:
        best_card = tied[0]
        best_tb = -999
        for card in tied:
            tb = self._tiebreak_score(card, flags, hand, me, phase)
            if tb > best_tb:
                best_tb = tb
                best_card = card

        return best_card

    def _tiebreak_score(self, card, flags, hand, me, phase):
        """Score for breaking ties when multiple cards have the same gap."""
        suit = card[0]
        played = flags[suit].played[me]
        score = 0.0

        # Prefer extending existing expeditions
        if played:
            score += 5

        # Prefer suits with contracts (higher multiplier)
        n_contracts = sum(1 for c in played if c[1] == '0')
        score += n_contracts * 3

        # Prefer suits closer to 8-card bonus
        needed = cards_to_bonus(suit, flags, me)
        if 0 < needed <= 3:
            hand_in_suit = playable_in_hand(suit, hand, flags, me)
            remaining = remaining_above(suit, flags, hand, me)
            total_available = len(played) + len(hand_in_suit) + len(remaining)
            if total_available >= BONUS_THRESHOLD:
                score += (4 - needed) * 3

        # Prefer suits with more supporting cards in hand
        hand_in_suit = [c for c in hand if c[0] == suit]
        score += len(hand_in_suit) * 1.5

        # Slight preference for higher face value (more points)
        if card[1] != '0':
            score += (int(card[1]) + 1) * 0.1

        # Early game: prefer contracts with support
        if card[1] == '0' and not played and phase < 0.3:
            supporting = len([c for c in hand if c[0] == suit and c[1] != '0'])
            if supporting >= 2:
                score += 5
            else:
                score -= 3

        return score

    def _choose_discard(self, hand, flags, me):
        """Pick the best card to discard."""
        deadwood = hand_deadwood(hand, flags, me)

        if deadwood:
            # Among deadwood, pick least dangerous
            deadwood.sort(key=lambda c: discard_danger(c, flags, me))
            return deadwood[0]

        # Score all cards
        scored = [(c, smart_discard_score(c, flags, hand, me)) for c in hand]
        scored.sort(key=lambda x: x[1])

        # Avoid feeding the opponent if possible
        opp_needs = set(c[0] for c in opponent_needs_from_discard(flags, me))
        best_card, best_score = scored[0]
        if best_card[0] in opp_needs and len(scored) > 1:
            for card, sc in scored[1:]:
                if card[0] not in opp_needs:
                    return card
                if sc - best_score < 3:
                    return card

        return best_card

    def _choose_draw_after_play(self, played_card, flags, hand, me, phase):
        """Choose draw source after playing a card.
        Uses Committer-style logic: draw from discard if it improves hand
        more than the second-best play option."""
        candidates, deck_ev = best_available_draw(flags, hand, me)

        # Also consider denial draws
        denial = self._get_denial_draws(flags, hand, me)

        all_draws = [(c, v) for c, v in candidates]
        seen = set(c for c, v in candidates)
        for c, v in denial:
            if c not in seen:
                all_draws.append((c, v * 0.5))

        # Tempo: if ahead and want to push, prefer deck
        advantage = tempo_advantage(flags, hand, me)
        stalling = should_stall(flags, hand, me)

        if phase > 0.5 and advantage > 20 and not stalling:
            all_draws = [(c, v) for c, v in all_draws if v > deck_ev * 1.5]

        # If stalling, accept any playable discard draw
        if stalling and not all_draws:
            for suit in SUITS:
                discards = flags[suit].discards
                if discards:
                    top = discards[-1]
                    if is_playable(top, flags[suit].played[me]):
                        all_draws.append((top, 0.1))

        if all_draws:
            all_draws.sort(key=lambda x: x[1], reverse=True)
            return all_draws[0][0]

        return 'deck'

    def _choose_draw_after_discard(self, discarded, flags, hand, me, phase):
        """Choose draw source after discarding. Can't draw from discarded suit."""
        discard_suit = discarded[0]

        candidates, deck_ev = best_available_draw(flags, hand, me)
        denial = self._get_denial_draws(flags, hand, me)

        all_draws = [(c, v) for c, v in candidates]
        seen = set(c for c, v in candidates)
        for c, v in denial:
            if c not in seen:
                all_draws.append((c, v * 0.5))

        # Filter out discarded suit
        all_draws = [(c, v) for c, v in all_draws if c[0] != discard_suit]

        stalling = should_stall(flags, hand, me)
        if stalling and not all_draws:
            for suit in SUITS:
                if suit == discard_suit:
                    continue
                discards = flags[suit].discards
                if discards:
                    top = discards[-1]
                    if is_playable(top, flags[suit].played[me]):
                        all_draws.append((top, 0.1))

        if all_draws:
            all_draws.sort(key=lambda x: x[1], reverse=True)
            return all_draws[0][0]

        return 'deck'

    def _get_denial_draws(self, flags, hand, me):
        """Find discard pile cards worth drawing to deny the opponent."""
        denial = []
        for suit in SUITS:
            discards = flags[suit].discards
            if discards:
                top = discards[-1]
                if is_playable(top, flags[suit].played[me]):
                    dv = deny_draw_value(top, flags, hand, me)
                    if dv > 5:
                        denial.append((top, dv))
        return denial
