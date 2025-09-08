import random

def is_playable(card, played):
    return not played or card[1] >= played[-1][1]

def safe_discards(cards, flags, me):
    """Cards the opponent can't use"""
    return [c for c in cards if not is_playable(c, flags[c[0]].played[1-me])]

def useless_discards(cards, flags, me):
    """Cards neither player can use"""
    return [c for c in cards if not is_playable(c, flags[c[0]].played[1-me])
                            and not is_playable(c, flags[c[0]].played[me])]

def discard_intelligently(cards, flags, me):
    """Return a good discard, accounting for face value and playability."""
    useless = useless_discards(cards, flags, me)
    if useless:  # Preferably, discard any useless card.
        return random.choice(useless)
    safe = safe_discards(cards, flags, me)
    if safe:  # Or the lowest safe card
        safe.sort(key=lambda x: x[1])  # TODO: break ties randomly?  And below
        return safe[0]
    cards.sort(key=lambda x: x[1])
    return cards[0]  # Or just the lowest

def playable_draws(flags, me):
    return [f.discards[-1] for f in flags.values()
                            if f.discards
                           and is_playable(f.discards[-1],
                                           flags[f.discards[-1][0]].played[me])]
