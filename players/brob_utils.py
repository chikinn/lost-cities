"""Utility functions for the brob player.

Card format: 2-char string, suit letter + face value digit (e.g., 'b5', 'r0').
Each suit has 3 contracts ('0') and numbered cards '1'-'9' (scored as face+1).
Total deck: 72 cards (6 suits x 12 cards).
"""

from classes import SUITS, CARDS, BREAKEVEN, BONUS_THRESHOLD, BONUS_POINTS, HAND_SIZE
from utils import is_playable, sum_cards


# ---------------------------------------------------------------------------
# Card tracking & information
# ---------------------------------------------------------------------------

def all_cards_in_suit(suit):
    """Return the full multiset of cards in a suit as a list."""
    return [suit + c for c in CARDS]


def visible_cards(flags, hand):
    """All cards visible to the current player: hand + all played + all discards."""
    seen = list(hand)
    for s in SUITS:
        seen.extend(flags[s].played[0])
        seen.extend(flags[s].played[1])
        seen.extend(flags[s].discards)
    return seen


def unseen_cards(flags, hand):
    """Cards not visible: in deck or opponent's hand."""
    seen = visible_cards(flags, hand)
    all_cards = [s + c for s in SUITS for c in CARDS]
    remaining = list(all_cards)
    for card in seen:
        remaining.remove(card)
    return remaining


def remaining_in_suit(suit, flags, hand):
    """Unseen cards in a specific suit."""
    return [c for c in unseen_cards(flags, hand) if c[0] == suit]


def remaining_above(suit, flags, hand, me):
    """Unseen cards in a suit that are above the highest card played by me.
    These are cards I could still potentially play."""
    played = flags[suit].played[me]
    if played:
        highest = played[-1][1]
    else:
        highest = None  # Haven't started; everything is playable

    remaining = remaining_in_suit(suit, flags, hand)
    if highest is None:
        return remaining
    return [c for c in remaining if c[1] > highest]


def remaining_below(suit, flags, hand, me):
    """Unseen cards in a suit that are at or below my highest played card.
    Dead to me, but may matter to the opponent."""
    played = flags[suit].played[me]
    if not played:
        return []
    highest = played[-1][1]
    remaining = remaining_in_suit(suit, flags, hand)
    return [c for c in remaining if c[1] <= highest]


def playable_in_hand(suit, hand, flags, me):
    """Cards in hand for this suit that are playable on my expedition."""
    played = flags[suit].played[me]
    return [c for c in hand if c[0] == suit and is_playable(c, played)]


# ---------------------------------------------------------------------------
# Expedition evaluation
# ---------------------------------------------------------------------------

def expedition_score(cards):
    """Current score of a single expedition (same logic as Round.get_winner)."""
    if not cards:
        return 0
    mult = 1
    total = 0
    for c in cards:
        if c[1] == '0':
            mult += 1
        else:
            total += int(c[1]) + 1
    score = mult * (total - BREAKEVEN)
    if len(cards) >= BONUS_THRESHOLD:
        score += BONUS_POINTS
    return score


def expedition_projected_score(suit, flags, hand, me):
    """Score if I play all playable cards from my hand in this suit (no future draws)."""
    played = list(flags[suit].played[me])
    hand_cards = playable_in_hand(suit, hand, flags, me)
    # Sort to simulate playing in order
    hand_cards.sort(key=lambda c: c[1])
    projected = played + hand_cards
    return expedition_score(projected)


def expedition_breakeven_distance(suit, flags, hand, me):
    """How many more face-value points needed to reach breakeven.
    Negative means already profitable. Accounts for multiplier."""
    played = flags[suit].played[me]
    hand_cards = playable_in_hand(suit, hand, flags, me)
    all_cards = played + sorted(hand_cards, key=lambda c: c[1])

    if not all_cards:
        return BREAKEVEN  # Would need 20 points to break even

    mult = 1
    total = 0
    for c in all_cards:
        if c[1] == '0':
            mult += 1
        else:
            total += int(c[1]) + 1

    # Need mult * (total - BREAKEVEN) >= 0, i.e., total >= BREAKEVEN
    return BREAKEVEN - total


def cards_to_bonus(suit, flags, me):
    """How many more cards needed to reach the 8-card bonus."""
    played = flags[suit].played[me]
    return max(0, BONUS_THRESHOLD - len(played))


def suit_potential(suit, flags, hand, me):
    """Maximum possible score if I drew and played every remaining playable card.
    The ceiling on what this expedition could become."""
    played = list(flags[suit].played[me])
    hand_cards = playable_in_hand(suit, hand, flags, me)
    future_cards = remaining_above(suit, flags, hand, me)

    # Combine played + hand + future, sorted
    all_available = hand_cards + future_cards
    all_available.sort(key=lambda c: c[1])
    projected = played + all_available
    return expedition_score(projected)


def is_expedition_viable(suit, flags, hand, me):
    """Heuristic score for whether to invest in this suit.
    Returns a float: positive means worth pursuing, negative means abandon.
    Considers: projected score with hand only, potential with future draws,
    and how many cards remain to draw."""
    projected = expedition_projected_score(suit, flags, hand, me)
    potential = suit_potential(suit, flags, hand, me)
    remaining = len(remaining_above(suit, flags, hand, me))

    # Weight: mostly care about what we have, with some credit for potential
    return projected * 0.6 + potential * 0.2 + remaining * 0.2


# ---------------------------------------------------------------------------
# Game phase & tempo
# ---------------------------------------------------------------------------

def deck_cards_remaining(flags, hand):
    """Count cards remaining in the deck (unseen minus opponent's hand of 8)."""
    n_unseen = len(unseen_cards(flags, hand))
    # Opponent holds HAND_SIZE cards from the unseen pool
    return max(0, n_unseen - HAND_SIZE)


def game_phase(flags, hand):
    """Returns 0.0 (start) to 1.0 (end) based on deck depletion.
    Total deck starts at 72 - 16 = 56 drawable cards."""
    total_drawable = 72 - 2 * HAND_SIZE  # 56
    remaining = deck_cards_remaining(flags, hand)
    return 1.0 - (remaining / total_drawable)


def turns_remaining(flags, hand):
    """Approximate turns left for the current player."""
    return deck_cards_remaining(flags, hand) // 2


# ---------------------------------------------------------------------------
# Expected value of draws
# ---------------------------------------------------------------------------

def card_value_for_me(card, flags, me):
    """How valuable is drawing this specific card?

    Four categories of cards:
    1. Useful to me          -> positive
    2. Useful to opponent    -> negative (I'd rather it stay in the deck)
    3. Useful to both        -> positive (I get it, opponent doesn't)
    4. Useful to neither     -> zero (just game clock)
    """
    suit = card[0]
    my_played = flags[suit].played[me]
    opp_played = flags[suit].played[1 - me]

    playable_for_me = is_playable(card, my_played)
    playable_for_opp = is_playable(card, opp_played)

    if not playable_for_me and not playable_for_opp:
        return 0.0  # Category 4: dead card, just game clock

    if not playable_for_me and playable_for_opp:
        # Category 2: helps opponent only — slightly negative since it clogs
        # my hand as deadwood. But mild: it's not actively harmful.
        return -0.2

    # Category 1 or 3: playable for me
    if card[1] == '0':
        base_value = 2.0
    else:
        base_value = int(card[1]) + 1

    # Bonus for being sequential (no gap)
    if my_played:
        highest = int(my_played[-1][1])
        card_val = int(card[1])
        if card[1] != '0':
            gap = max(0, card_val - highest - 1)
            if gap == 0:
                base_value += 5
            elif gap == 1:
                base_value += 2
    else:
        # Starting a new expedition — moderate value
        if card[1] == '0':
            base_value = 3.0
        else:
            base_value *= 0.7

    # Multiplier bonus if we have contracts in this suit
    n_contracts = sum(1 for c in my_played if c[1] == '0')
    if n_contracts > 0 and card[1] != '0':
        base_value *= (1 + n_contracts * 0.3)

    # Category 3 bonus: if opponent also wants it, extra value in denying them
    if playable_for_opp and opp_played:
        base_value += 1.0

    return base_value


def expected_value_deck_draw(flags, hand, me):
    """Expected value of drawing from the deck.
    Averages card_value_for_me over all unseen cards. Positive values mean
    useful cards, negative means opponent-helpful cards, zero means neutral."""
    unseen = unseen_cards(flags, hand)
    if not unseen:
        return 0.0
    total = sum(card_value_for_me(c, flags, me) for c in unseen)
    return total / len(unseen)


def discard_draw_value(card, flags, me):
    """Value of drawing a specific card from a discard pile."""
    return card_value_for_me(card, flags, me)


def best_available_draw(flags, hand, me):
    """Compare all drawable discard pile cards against expected deck draw.
    Returns list of (card, value) for discard draws that beat the deck EV,
    sorted by value descending."""
    deck_ev = expected_value_deck_draw(flags, hand, me)

    candidates = []
    for suit in SUITS:
        discards = flags[suit].discards
        if discards:
            top = discards[-1]
            if is_playable(top, flags[suit].played[me]):
                val = discard_draw_value(top, flags, me)
                if val > deck_ev:
                    candidates.append((top, val))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates, deck_ev


# ---------------------------------------------------------------------------
# Discard & risk evaluation
# ---------------------------------------------------------------------------

def discard_danger(card, flags, me):
    """How much does discarding this card help the opponent?
    Higher = more dangerous to discard."""
    opp = 1 - me
    opp_played = flags[card[0]].played[opp]

    if not is_playable(card, opp_played):
        return 0.0  # Opponent can't use it

    # Base danger: face value the opponent would score
    if card[1] == '0':
        face_val = 0
    else:
        face_val = int(card[1]) + 1

    # Multiply by opponent's contract count in this suit
    n_contracts = sum(1 for c in opp_played if c[1] == '0')
    mult = 1 + n_contracts

    danger = mult * face_val

    # Extra danger if it's sequential for the opponent
    if opp_played:
        opp_highest = int(opp_played[-1][1])
        if int(card[1]) == opp_highest + 1:
            danger *= 1.5  # Sequential is especially dangerous

    # Danger if opponent hasn't started but card is a contract
    if not opp_played and card[1] == '0':
        danger = 3.0  # Contracts enable opponent's expedition

    return danger


def information_leak(card, flags, hand, me):
    """Estimate signal cost of discarding this card.
    Discarding from a suit you're collecting reveals information."""
    suit = card[0]
    my_played = flags[suit].played[me]
    hand_in_suit = [c for c in hand if c[0] == suit]

    # If you've played in this suit and still hold cards, discarding one
    # signals you have better cards or are narrowing
    if my_played and len(hand_in_suit) > 1:
        return 2.0

    # Discarding a high card reveals you don't value that suit
    if card[1] >= '6':
        return 1.5

    return 0.5


def smart_discard_score(card, flags, hand, me):
    """Combined discard evaluation. Lower score = better to discard."""
    danger = discard_danger(card, flags, me)
    leak = information_leak(card, flags, hand, me)
    my_value = card_value_for_me(card, flags, me)

    # We WANT to discard cards that are low value to us and low danger
    return danger + leak + max(0, my_value)


# ---------------------------------------------------------------------------
# Opponent modeling
# ---------------------------------------------------------------------------

def opponent_committed_suits(flags, me):
    """Which suits has the opponent started, and how deep are they?
    Returns dict of suit -> card count."""
    opp = 1 - me
    committed = {}
    for s in SUITS:
        played = flags[s].played[opp]
        if played:
            committed[s] = len(played)
    return committed


def opponent_suit_potential(suit, flags, hand, me):
    """Estimate opponent's maximum possible score in a suit."""
    opp = 1 - me
    played = list(flags[suit].played[opp])
    if not played:
        return 0

    # Cards above opponent's highest that are unseen (could be in their hand)
    highest = played[-1][1]
    unseen = unseen_cards(flags, hand)
    future = [c for c in unseen if c[0] == suit and c[1] > highest]

    projected = played + sorted(future, key=lambda c: c[1])
    return expedition_score(projected)


def opponent_needs_from_discard(flags, me):
    """Which discard pile top cards are playable for the opponent?
    Returns list of cards we should avoid adding to."""
    opp = 1 - me
    dangerous_suits = []
    for s in SUITS:
        discards = flags[s].discards
        if discards:
            top = discards[-1]
            if is_playable(top, flags[s].played[opp]):
                dangerous_suits.append(top)
    return dangerous_suits


def deny_draw_value(card, flags, hand, me):
    """Value of drawing a discard pile card to deny opponent access.
    High value means opponent really wants this card."""
    opp = 1 - me
    opp_played = flags[card[0]].played[opp]

    if not is_playable(card, opp_played):
        return 0.0

    # How much would this help the opponent?
    if card[1] == '0':
        face_val = 0
    else:
        face_val = int(card[1]) + 1

    n_contracts = sum(1 for c in opp_played if c[1] == '0')
    return (1 + n_contracts) * face_val


# ---------------------------------------------------------------------------
# Hand quality
# ---------------------------------------------------------------------------

def hand_flexibility(hand, flags, me):
    """How many suits do you have playable options in?"""
    suits_with_plays = set()
    for c in hand:
        if is_playable(c, flags[c[0]].played[me]):
            suits_with_plays.add(c[0])
    return len(suits_with_plays)


def hand_deadwood(hand, flags, me):
    """Cards in hand that can't be played anywhere. Must be discarded."""
    return [c for c in hand if not is_playable(c, flags[c[0]].played[me])]


def suit_density_in_hand(suit, hand):
    """How many cards of this suit do you hold?"""
    return sum(1 for c in hand if c[0] == suit)


def contract_value(suit, hand, flags, me):
    """How good is playing a contract in this suit?
    Considers: cards in hand, remaining cards, whether breakeven is reachable."""
    hand_in_suit = [c for c in hand if c[0] == suit and c[1] != '0']
    hand_sum = sum_cards(hand_in_suit)
    remaining = remaining_above(suit, flags, hand, me)
    remaining_sum = sum_cards(remaining)

    # Can we reach breakeven with what we have + what's out there?
    total_possible = hand_sum + remaining_sum

    # Number of contracts we'd have (existing + this one)
    played = flags[suit].played[me]
    existing_contracts = sum(1 for c in played if c[1] == '0')
    new_mult = 1 + existing_contracts + 1  # +1 for the contract we're considering

    # Projected score: multiplier * (total - breakeven)
    # But we won't get everything, so discount the remaining cards
    estimated_sum = hand_sum + remaining_sum * 0.3  # Expect ~30% of remaining
    projected = new_mult * (estimated_sum - BREAKEVEN)

    # Card count: can we reach bonus?
    hand_count = len(hand_in_suit)
    remaining_count = len(remaining)
    total_cards = len(played) + 1 + hand_count  # played + contract + hand cards
    bonus_reachable = (total_cards + remaining_count) >= BONUS_THRESHOLD

    if bonus_reachable:
        projected += BONUS_POINTS * 0.3  # Discount probability

    return projected


# ---------------------------------------------------------------------------
# Tempo evaluation
# ---------------------------------------------------------------------------

def my_total_score(flags, me):
    """Current total score across all expeditions."""
    return sum(expedition_score(flags[s].played[me]) for s in SUITS)


def opponent_total_score(flags, me):
    """Current total score across all opponent's expeditions."""
    opp = 1 - me
    return sum(expedition_score(flags[s].played[opp]) for s in SUITS)


def tempo_advantage(flags, hand, me):
    """Am I winning or losing? Positive means ahead.
    Also considers projected scores from hand cards."""
    my_score = my_total_score(flags, me)
    opp_score = opponent_total_score(flags, me)

    # Add projected value from hand
    my_projected = sum(expedition_projected_score(s, flags, hand, me) for s in SUITS)

    return my_projected - opp_score


def should_stall(flags, hand, me):
    """Should I slow the game down (draw from discard piles)?
    True if behind and need more turns, or close to bonus thresholds."""
    phase = game_phase(flags, hand)
    advantage = tempo_advantage(flags, hand, me)

    # Behind in late game: stall
    if phase > 0.5 and advantage < -10:
        return True

    # Close to bonus in any suit: stall to get more draws
    for s in SUITS:
        played = flags[s].played[me]
        hand_in_suit = playable_in_hand(s, hand, flags, me)
        total_cards = len(played) + len(hand_in_suit)
        if 5 <= total_cards < BONUS_THRESHOLD:
            remaining = len(remaining_above(s, flags, hand, me))
            if remaining >= (BONUS_THRESHOLD - total_cards):
                return True

    return False
