"""Оркестрация симуляции для одного прогона: строит вход из БД, гоняет
детерминированный baseline + N случайных прогонов (Monte Carlo) поверх
services.simulation.run_deferred_acceptance, и сохраняет SimulationResult.

Что рандомизируем и почему (см. обсуждение с пользователем):
- Группы 1 и 2 (согласие есть, вопрос только в том, на какой из СВОИХ
  приоритетов человек реально попадёт) - это НЕ требует рандомизации,
  алгоритм отложенного принятия сам разруливает каскад приоритетов
  корректно и детерминированно.
- Группа 3 (согласия ещё нет) - неопределённость: может подать позже.
  С вероятностью MC_P3_NO_CONSENT_JOINS в конкретном прогоне считаем, что
  подал(а).
- Группа 4 (реально уйдёт в другой вуз, хотя согласие в МАИ есть) - не
  видна из данных МАИ. С вероятностью MC_P4_CONSENT_DROPS_OUT в конкретном
  прогоне считаем, что человек с согласием выбывает из пула целиком.

Две вероятности на направление:
- probability_pct - безусловная: итоговый результат ПОЛНОЙ симуляции с её
  реальным списком приоритетов (куда её распределит алгоритм на самом деле).
- standalone_probability_pct - независимая оценка направления САМОГО ПО
  СЕБЕ, как если бы оно было её единственным (и потому приоритетом 1).
  Считается через "фоновую" симуляцию БЕЗ отслеживаемых абитуриентов
  (реальные конкуренты каскадируют по своим приоритетам как обычно), а
  затем проверяем - попала бы она в топ-capacity мест по баллу. Не зависит
  от того, что у неё есть другие направления - поэтому не может быть
  искусственно занижена приоритетом 1.
"""
import random
import statistics
from collections import defaultdict

from config import SIM_CATEGORY, MC_TRIALS, MC_P3_NO_CONSENT_JOINS, MC_P4_CONSENT_DROPS_OUT
from models import CompetitorSnapshot, SeatPlan, TrackedApplicant, SimulationResult
from services.simulation import run_deferred_acceptance, cutoff_scores


def _latest_capacities(db, as_of_run_id: int) -> dict:
    """{direction_id: seats_budget} - последняя известная строка seat_plans
    на момент прогона as_of_run_id (включая места, добавленные в этом же
    прогоне)."""
    rows = (
        db.query(SeatPlan)
        .filter(SeatPlan.source_run_id <= as_of_run_id)
        .order_by(SeatPlan.direction_id, SeatPlan.valid_from.desc())
        .all()
    )
    capacities = {}
    for row in rows:
        if row.direction_id not in capacities:
            capacities[row.direction_id] = row.seats_budget
    return capacities


def _load_grouped_rows(db, run_id: int):
    """{unique_code: [(direction_id, priority, score, consent), ...]}
    отсортировано по priority по возрастанию."""
    rows = (
        db.query(CompetitorSnapshot)
        .filter(CompetitorSnapshot.run_id == run_id, CompetitorSnapshot.category == SIM_CATEGORY)
        .all()
    )
    grouped = defaultdict(list)
    for r in rows:
        if r.priority is None or r.total_score is None:
            continue
        grouped[r.unique_code].append((r.direction_id, r.priority, r.total_score, r.consent))
    for code in grouped:
        grouped[code].sort(key=lambda e: e[1])
    return grouped


def _build_baseline_applicants(grouped: dict) -> dict:
    """Только те, у кого есть согласие хотя бы на одно направление -
    baseline = "как если бы сейчас закрыли приём"."""
    applicants = {}
    for code, entries in grouped.items():
        consented = [(d, p, s) for d, p, s, c in entries if c]
        if consented:
            applicants[code] = consented
    return applicants


def _build_trial_applicants(grouped: dict, protected_codes: set) -> dict:
    """protected_codes - отслеживаемые абитуриенты: их реальное состояние
    (согласие подано/не подано) берём как есть, без рандомизации - мы же
    не оцениваем ИХ собственную вероятность передумать, а оцениваем шансы
    ПРОТИВ неопределённого поведения остальных конкурентов."""
    applicants = {}
    for code, entries in grouped.items():
        consented = [(d, p, s) for d, p, s, c in entries if c]
        not_consented = [(d, p, s) for d, p, s, c in entries if not c]

        if code in protected_codes:
            trial_entries = consented  # как в baseline, без рандомизации
        else:
            trial_entries = []
            if consented:
                if random.random() >= MC_P4_CONSENT_DROPS_OUT:
                    trial_entries = consented
            elif not_consented:
                if random.random() < MC_P3_NO_CONSENT_JOINS:
                    trial_entries = not_consented

        if trial_entries:
            trial_entries = sorted(trial_entries, key=lambda e: e[1])
            applicants[code] = trial_entries
    return applicants


def _competitor_score_stats(grouped: dict, tracked_codes: set) -> dict:
    """{direction_id: [баллы согласившихся конкурентов, без отслеживаемых]}
    - текущее реальное состояние (не рандомизация), для средних/минимумов."""
    by_direction = defaultdict(list)
    for code, entries in grouped.items():
        if code in tracked_codes:
            continue
        for direction_id, _priority, score, consent in entries:
            if consent:
                by_direction[direction_id].append(score)
    return by_direction


def compute_simulation(db, run_id: int, trials: int = MC_TRIALS):
    grouped = _load_grouped_rows(db, run_id)
    capacities = _latest_capacities(db, run_id)

    tracked_applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    tracked_codes = {a.unique_code: a for a in tracked_applicants}

    # --- детерминированный baseline (текущее состояние, без рандомизации) ---
    baseline_applicants = _build_baseline_applicants(grouped)
    baseline_assignment = run_deferred_acceptance(baseline_applicants, capacities)
    baseline_cutoffs = cutoff_scores(baseline_applicants, capacities, baseline_assignment)
    competitor_scores = _competitor_score_stats(grouped, set(tracked_codes))

    # --- Monte Carlo ---
    # tally: итоговый результат полной симуляции (с её реальным списком приоритетов)
    # standalone_tally: попала бы она сюда, если бы это было её единственное направление
    tally = {code: defaultdict(int) for code in tracked_codes}
    standalone_tally = {code: defaultdict(int) for code in tracked_codes}

    for _ in range(trials):
        trial_applicants = _build_trial_applicants(grouped, set(tracked_codes))
        assignment = run_deferred_acceptance(trial_applicants, capacities)
        for code in tracked_codes:
            tally[code][assignment.get(code)] += 1

        # "фоновая" симуляция - реальные конкуренты без отслеживаемых
        # абитуриентов, чтобы оценить каждое направление независимо от её
        # собственного списка приоритетов
        background_applicants = {c: v for c, v in trial_applicants.items() if c not in tracked_codes}
        background_assignment = run_deferred_acceptance(background_applicants, capacities)

        admitted_scores = defaultdict(list)
        for c, direction_id in background_assignment.items():
            if direction_id is None:
                continue
            for d2, _p2, s2 in background_applicants[c]:
                if d2 == direction_id:
                    admitted_scores[direction_id].append(s2)
                    break

        for code in tracked_codes:
            for direction_id, _priority, score, _consent in grouped.get(code, []):
                cap = capacities.get(direction_id)
                if cap is None:
                    continue
                pool = admitted_scores.get(direction_id, [])
                if len(pool) < cap or score > min(pool):
                    standalone_tally[code][direction_id] += 1

    results = []
    for code, applicant in tracked_codes.items():
        own_entries_sorted = sorted(grouped.get(code, []), key=lambda e: e[1])
        code_tally = tally.get(code, {})
        code_standalone_tally = standalone_tally.get(code, {})

        for direction_id, priority, score, consent in own_entries_sorted:
            cap = capacities.get(direction_id)

            admitted_here = baseline_assignment.get(code) == direction_id
            cutoff = baseline_cutoffs.get(direction_id)
            gap = (score - cutoff) if cutoff is not None else None

            prob_pct = 100.0 * code_tally.get(direction_id, 0) / trials if trials else None
            standalone_pct = (100.0 * code_standalone_tally.get(direction_id, 0) / trials
                               if trials and cap is not None else None)

            others = competitor_scores.get(direction_id, [])
            avg_score = statistics.mean(others) if others else None
            min_score = min(others) if others else None
            gap_to_avg = (score - avg_score) if avg_score is not None else None
            gap_to_min = (score - min_score) if min_score is not None else None
            consented_position = (1 + sum(1 for s in others if s > score)) if consent else None

            results.append(SimulationResult(
                run_id=run_id,
                tracked_applicant_id=applicant.id,
                direction_id=direction_id,
                deterministic_admitted=admitted_here,
                probability_pct=prob_pct,
                standalone_probability_pct=standalone_pct,
                cutoff_score_estimate=cutoff,
                gap=gap,
                consented_count=len(others) + (1 if consent else 0),
                consented_position=consented_position,
                avg_competitor_score=avg_score,
                gap_to_avg=gap_to_avg,
                min_competitor_score=min_score,
                gap_to_min=gap_to_min,
                trials=trials,
            ))

    db.bulk_save_objects(results)
    db.commit()
    return results
