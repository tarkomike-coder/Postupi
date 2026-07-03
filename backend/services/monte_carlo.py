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
"""
import random
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


def compute_simulation(db, run_id: int, trials: int = MC_TRIALS):
    grouped = _load_grouped_rows(db, run_id)
    capacities = _latest_capacities(db, run_id)

    tracked_applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    tracked_codes = {a.unique_code: a for a in tracked_applicants}

    # --- детерминированный baseline ---
    baseline_applicants = _build_baseline_applicants(grouped)
    baseline_assignment = run_deferred_acceptance(baseline_applicants, capacities)
    baseline_cutoffs = cutoff_scores(baseline_applicants, capacities, baseline_assignment)

    # --- Monte Carlo ---
    # tally[unique_code][direction_id_or_None] = сколько раз в N прогонов
    tally = {code: defaultdict(int) for code in tracked_codes}
    for _ in range(trials):
        trial_applicants = _build_trial_applicants(grouped, set(tracked_codes))
        assignment = run_deferred_acceptance(trial_applicants, capacities)
        for code in tracked_codes:
            tally[code][assignment.get(code)] += 1

    results = []
    for code, applicant in tracked_codes.items():
        own_entries = grouped.get(code, [])
        # её собственные направления в порядке приоритета (1 = самый желанный)
        own_entries_sorted = sorted(own_entries, key=lambda e: e[1])
        code_tally = tally.get(code, {})

        # trials, в которых она НЕ попала ни на один более высокий приоритет -
        # знаменатель для условной вероятности "запасного варианта"
        still_in_play = trials
        for direction_id, priority, score, consent in own_entries_sorted:
            admitted_here = baseline_assignment.get(code) == direction_id
            cutoff = baseline_cutoffs.get(direction_id)
            gap = (score - cutoff) if cutoff is not None else None
            hits = code_tally.get(direction_id, 0)
            prob_pct = 100.0 * hits / trials if trials else None
            cond_prob_pct = 100.0 * hits / still_in_play if still_in_play else None

            results.append(SimulationResult(
                run_id=run_id,
                tracked_applicant_id=applicant.id,
                direction_id=direction_id,
                deterministic_admitted=admitted_here,
                cutoff_score_estimate=cutoff,
                gap=gap,
                probability_pct=prob_pct,
                conditional_probability_pct=cond_prob_pct,
                trials=trials,
            ))

            still_in_play -= hits  # эти trials больше не "в игре" для след. приоритета

    db.bulk_save_objects(results)
    db.commit()
    return results
