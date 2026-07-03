"""Детерминированная симуляция распределения бюджетных мест - алгоритм
отложенного принятия (Гейл-Шепли, "abitурient-proposing"), применённый к
конкурсным спискам МАИ. Чистая функция, без обращений к БД - вход/выход
только в памяти, что позволяет гонять её тысячи раз для Monte Carlo слоя
(services/monte_carlo.py).
"""
import heapq
from collections import deque
from typing import Dict, List, Optional, Tuple

# applicants: {unique_code: [(direction_id, priority, score), ...]} -
#   список ДОЛЖЕН быть отсортирован по priority по возрастанию (1 = самый желанный)
# capacities: {direction_id: seats_budget}
Applicants = Dict[str, List[Tuple[int, int, int]]]
Capacities = Dict[int, int]


def run_deferred_acceptance(applicants: Applicants, capacities: Capacities) -> Dict[str, Optional[int]]:
    """Возвращает {unique_code: direction_id или None (не прошёл никуда)}."""
    pointer = {code: 0 for code in applicants}
    heaps: Dict[int, list] = {}
    free = deque(applicants.keys())

    while free:
        code = free.popleft()
        prefs = applicants[code]
        idx = pointer[code]

        # пропускаем направления без известной вместимости (edge case -
        # не смогли сматчить с планом приёма) - для абитуриента это как
        # будто он туда не подавал
        while idx < len(prefs) and not capacities.get(prefs[idx][0]):
            idx += 1
        pointer[code] = idx

        if idx >= len(prefs):
            continue  # исчерпал все приоритеты - никуда не прошёл

        direction_id, _priority, score = prefs[idx]
        cap = capacities[direction_id]
        heap = heaps.setdefault(direction_id, [])
        heapq.heappush(heap, (score, code))

        if len(heap) > cap:
            _evicted_score, evicted_code = heapq.heappop(heap)
            pointer[evicted_code] += 1
            free.append(evicted_code)

    assignment: Dict[str, Optional[int]] = {code: None for code in applicants}
    for direction_id, heap in heaps.items():
        for score, code in heap:
            assignment[code] = direction_id
    return assignment


def cutoff_scores(applicants: Applicants, capacities: Capacities,
                   assignment: Dict[str, Optional[int]]) -> Dict[int, Optional[int]]:
    """Минимальный балл среди зачисленных по направлению (проходной балл по
    итогам симуляции). None - если направление не заполнено до конца (тогда
    "проходной балл" не имеет смысла - хватает всем)."""
    by_direction: Dict[int, list] = {}
    for code, direction_id in assignment.items():
        if direction_id is None:
            continue
        for d_id, _p, score in applicants[code]:
            if d_id == direction_id:
                by_direction.setdefault(direction_id, []).append(score)
                break

    result = {}
    for direction_id, cap in capacities.items():
        scores = by_direction.get(direction_id, [])
        result[direction_id] = min(scores) if len(scores) >= cap and scores else None
    return result
