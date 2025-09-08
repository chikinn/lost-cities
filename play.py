"""
"""

from classes import *

def play_one_round(players, names, verbose=False):
    r = Round(players, names, verbose)
    r.generate_decks_and_deal_hands()

    while r.deck:
        if verbose:
            hand = r.h[r.whose_turn]
            pad_length = hand.show()
        play = r.execute_play(players[r.whose_turn])
        if verbose:
            show_play(r, play, pad_length)
        r.whose_turn = 1 - r.whose_turn

    return r.h[r.get_winner()].name

def show_play(r, play, pad_length):
    card, is_discard, draw = play
    action_text = 'Discards' if is_discard else 'Plays'
    print(pad_length * ' ' + f'{action_text} {card}')
    if not draw == 'deck':
        print(pad_length * ' ' + f'Draws {draw}')
    r.show_flags()
