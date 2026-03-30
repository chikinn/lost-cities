"""SO-ISMCTS (Single Observer Information Set Monte Carlo Tree Search) player.

Handles hidden information by determinizing (sampling possible worlds) each
iteration and sharing one tree across all determinizations.  Tree nodes
represent information sets (move sequences), not specific game states.

Reference: Cowling, Powley & Whitehouse (2012),
"Information Set Monte Carlo Tree Search".
"""

import random
import math
from classes import Player, Round, SUITS, CARDS, HAND_SIZE, N_PLAYERS
from utils import is_playable, playable_draws


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class ISMCTSNode:
    __slots__ = ('move', 'parent', 'children', 'visits', 'total_reward')

    def __init__(self, move=None, parent=None):
        self.move = move
        self.parent = parent
        self.children = []
        self.visits = 0
        self.total_reward = 0.0

    def compatible_children(self, legal_moves):
        """Children whose moves are legal in the current determinization."""
        legal_set = set(legal_moves)
        return [c for c in self.children if c.move in legal_set]


# ---------------------------------------------------------------------------
# Determinization
# ---------------------------------------------------------------------------

def determinize(view):
    """Build a full Round by randomly distributing unknown cards."""
    # Build list of all known cards (preserving duplicates)
    known = list(view.hand.cards)
    for s in SUITS:
        known.extend(view.flags[s].played[0])
        known.extend(view.flags[s].played[1])
        known.extend(view.flags[s].discards)

    # Remove known cards one-by-one from the full deck to handle duplicates
    unknown = [s + c for s in SUITS for c in CARDS]
    for card in known:
        unknown.remove(card)
    random.shuffle(unknown)

    me = view.whose_turn
    opp = 1 - me
    opp_hand_cards = unknown[:HAND_SIZE]
    sim_deck = unknown[HAND_SIZE:]

    # Build Round without calling __init__
    r = object.__new__(Round)
    r.verbose = False
    r.whose_turn = view.whose_turn

    r.flags = {}
    for s in SUITS:
        f = object.__new__(Round.Flag)
        f.played = [list(view.flags[s].played[0]),
                     list(view.flags[s].played[1])]
        f.discards = list(view.flags[s].discards)
        r.flags[s] = f

    r.h = [None, None]

    my_hand = object.__new__(Round.Hand)
    my_hand.cards = list(view.hand.cards)
    my_hand.seat = me
    my_hand.name = f'Player{me}'
    r.h[me] = my_hand

    opp_hand = object.__new__(Round.Hand)
    opp_hand.cards = opp_hand_cards
    opp_hand.seat = opp
    opp_hand.name = f'Player{opp}'
    r.h[opp] = opp_hand

    r.deck = sim_deck
    return r


# ---------------------------------------------------------------------------
# Legal moves & simulation helpers
# ---------------------------------------------------------------------------

def get_legal_moves(r):
    """All valid (card, is_discard, draw) tuples for current player."""
    me = r.whose_turn
    hand = r.h[me].cards
    flags = r.flags

    drawable = playable_draws(flags, me)
    draw_options = ['deck'] + drawable if r.deck else drawable

    moves = []
    seen_cards = set()
    for card in hand:
        if card in seen_cards:
            continue
        seen_cards.add(card)
        suit = card[0]

        # Play (ascending order required)
        if is_playable(card, flags[suit].played[me]):
            for draw in draw_options:
                moves.append((card, False, draw))

        # Discard (can't discard to same pile you draw from)
        for draw in draw_options:
            if draw != 'deck' and draw[0] == suit:
                continue
            moves.append((card, True, draw))

    return moves


def apply_move(r, move):
    """Apply a move to a Round in place."""
    card, is_discard, draw = move
    me = r.whose_turn
    h = r.h[me]
    suit = card[0]

    h.drop(card)

    if is_discard:
        r.flags[suit].discards.append(card)
    else:
        r.flags[suit].played[me].append(card)

    drawn_card = r.draw(draw)
    h.add(drawn_card)

    r.whose_turn = 1 - r.whose_turn


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def get_scores(r):
    """Return [score_p0, score_p1]."""
    from classes import BREAKEVEN, BONUS_THRESHOLD, BONUS_POINTS

    scores = [0, 0]
    for p in range(N_PLAYERS):
        for f in r.flags.values():
            cards = f.played[p]
            if not cards:
                continue
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
            scores[p] += score
    return scores


def sigmoid_reward(r, me, k=20.0):
    """Reward in (0, 1) based on score differential."""
    scores = get_scores(r)
    diff = scores[me] - scores[1 - me]
    return 1.0 / (1.0 + math.exp(-diff / k))


# ---------------------------------------------------------------------------
# UCB1 selection
# ---------------------------------------------------------------------------

def ucb1_select(children, exploration):
    """Select the child with highest UCB1 score."""
    total_visits = sum(c.visits for c in children)
    log_total = math.log(total_visits)

    best_score = -float('inf')
    best_child = None
    for child in children:
        if child.visits == 0:
            return child
        exploit = child.total_reward / child.visits
        explore = exploration * math.sqrt(log_total / child.visits)
        score = exploit + explore
        if score > best_score:
            best_score = score
            best_child = child
    return best_child


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------

def ismcts_search(view, iterations=1000, exploration=0.7):
    """Run SO-ISMCTS and return the best move."""
    root = ISMCTSNode()
    me = view.whose_turn

    for _ in range(iterations):
        # 1. Determinize
        r = determinize(view)
        node = root

        # 2. Select + 3. Expand
        while r.deck:  # not terminal
            legal_moves = get_legal_moves(r)
            if not legal_moves:
                break

            compatible = node.compatible_children(legal_moves)
            tried_moves = {c.move for c in compatible}
            untried = [m for m in legal_moves if m not in tried_moves]

            if untried:
                # Expand: add one new child
                move = random.choice(untried)
                child = ISMCTSNode(move=move, parent=node)
                node.children.append(child)
                apply_move(r, move)
                node = child
                break
            else:
                # Select among compatible children
                node = ucb1_select(compatible, exploration)
                apply_move(r, node.move)

        # 4. Simulate (random playout)
        while r.deck:
            legal_moves = get_legal_moves(r)
            if not legal_moves:
                break
            apply_move(r, random.choice(legal_moves))

        # 5. Backpropagate
        reward = sigmoid_reward(r, me)
        while node is not None:
            node.visits += 1
            node.total_reward += reward
            node = node.parent

    # Return the most-visited root child
    if not root.children:
        # Fallback: shouldn't happen, but just in case
        r = determinize(view)
        return random.choice(get_legal_moves(r))

    best = max(root.children, key=lambda c: c.visits)
    return best.move


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class ISMCTS(Player):
    @classmethod
    def get_name(cls):
        return 'ismcts'

    def __init__(self, p):
        super().__init__(p)
        self.iterations = 1000

    def play(self, view):
        return ismcts_search(view, iterations=self.iterations)
