import random


def pick_winners(top, k, rng=random):
    """top: [(user_id, cnt)] — уже отобранный топ-N. Шанс пропорционален cnt, без повторов."""
    pool = list(top)
    winners = []
    while pool and len(winners) < k:
        w = rng.choices(pool, weights=[c for _, c in pool])[0]
        pool.remove(w)
        winners.append(w[0])
    return winners
