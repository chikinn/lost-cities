def is_playable(card, played):
    return not played or card[1] >= played[-1][1]
