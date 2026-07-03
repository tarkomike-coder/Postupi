"""Оркестрация симуляции для одного прогона: строит вход из БД, гоняет
детерминированный baseline + N случайных прогонов (Monte Carlo) поверх
services.simulation.run_deferred_acceptance, и сохраняет SimulationResult.

Ключевая идея по "реальным" конкурентам (см. обсуждение с пользователем):
позиция в сыром списке или даже "подано согласие" сами по себе мало что
говорят. Реальный конкурент - это тот, кого алгоритм отложенного принятия
(по ТЕКУЩИМ согласиям, детерминированно, без рандомизации) реально
распределяет ИМЕННО СЮДА: либо это его приоритет 1, либо он не проходит на
более высокие приоритеты и каскадом попадает сюда. Человек с согласием,
у которого более высокий приоритет ГДЕ-ТО ЕЩЁ, и который туда реально
проходит - сюда не считается, он не мешает (baseline_assignment это уже
учитывает).

Отдельно - Monte Carlo слой оценивает неопределённость, которую baseline
не видит:
- Группа "без согласия" - могут подать его позже (MC_P3_NO_CONSENT_JOINS).
- Группа "согласие есть" - могут передумать и уйти в другой вуз
  (MC_P4_CONSENT_DROPS_OUT).
"""
import random
import statistics
from collections import defaultdict

from config import SIM_CATEGORY, MC_TRIALS, MC_P3_NO_CONSENT_JOINS, MC_P4_CONSENT_DROPS_OUT
from models import CompetitorSnapshot, SeatPlan, TrackedApplicant, SimulationResult
from services.simulation import run_deferred_acceptance


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
    отсортировано по priority по возрастанию. Строки с баллом 0 отбрасываются
    сразу - это не реальный ноль, а ещё не посчитанный результат (результаты
    ЕГЭ/индивидуальных достижений не внесены), фейковый "конкурент"."""
    rows = (
        db.query(CompetitorSnapshot)
        .filter(CompetitorSnapshot.run_id == run_id, CompetitorSnapshot.category == SIM_CATEGORY)
        .all()
    )
    grouped = defaultdict(list)
    for r in rows:
        if r.priority is None or not r.total_score:
            continue
        grouped[r.unique_code].append((r.direction_id, r.priority, r.total_score, r.consent))
    for code in grouped:
        grouped[code].sort(key=lambda e: e[1])
    return grouped


def _build_baseline_applicants(grouped: dict) -> dict:
    """Только те, у кого есть согласие хотя бы на одно направление -
    baseline = "как если бы сейчас закрыли приём", без рандомизации."""
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


def _real_competitors_by_direction(grouped: dict, baseline_assignment: dict, tracked_codes: set) -> dict:
    """{direction_id: [(code, score), ...]} - те, кого baseline-каскад
    (по текущим согласиям, без рандомизации) реально распределяет именно
    сюда. Это и есть "реальные конкуренты" (не путать с сырым списком
    согласившихся - часть из них каскадом уйдёт на свой более высокий
    приоритет)."""
    by_direction = defaultdict(list)
    for code, direction_id in baseline_assignment.items():
        if direction_id is None or code in tracked_codes:
            continue
        # найдём балл этого человека по назначенному направлению
        for d2, _p2, score, _c2 in grouped.get(code, []):
            if d2 == direction_id:
                by_direction[direction_id].append((code, score))
                break
    return by_direction


def _group_breakdown(grouped: dict, baseline_assignment: dict, tracked_codes: set) -> dict:
    """{direction_id: {"cascaded_in": N, "consent_elsewhere": N, "no_consent": N}}"""
    result = defaultdict(lambda: {"cascaded_in": 0, "consent_elsewhere": 0, "no_consent": 0})
    for code, entries in grouped.items():
        if code in tracked_codes:
            continue
        assigned_to = baseline_assignment.get(code)
        for direction_id, _priority, _score, consent in entries:
            if not consent:
                result[direction_id]["no_consent"] += 1
            elif assigned_to == direction_id:
                result[direction_id]["cascaded_in"] += 1
            else:
                result[direction_id]["consent_elsewhere"] += 1
    return result


def compute_simulation(db, run_id: int, trials: int = MC_TRIALS):
    grouped = _load_grouped_rows(db, run_id)
    capacities = _latest_capacities(db, run_id)

    tracked_applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    tracked_codes = {a.unique_code: a for a in tracked_applicants}

    # --- детерминированный baseline (текущее состояние, без рандомизации) ---
    baseline_applicants = _build_baseline_applicants(grouped)
    baseline_assignment = run_deferred_acceptance(baseline_applicants, capacities)

    real_competitors = _real_competitors_by_direction(grouped, baseline_assignment, set(tracked_codes))
    breakdown = _group_breakdown(grouped, baseline_assignment, set(tracked_codes))

    # --- Monte Carlo ---
    tally = {code: defaultdict(int) for code in tracked_codes}            # итоговый результат (её реальный список)
    standalone_tally = {code: defaultdict(int) for code in tracked_codes}  # независимая оценка направления
    predicted_cutoffs = defaultdict(list)                                  # прогноз проходного балла по прогонам

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

        for direction_id, cap in capacities.items():
            pool = admitted_scores.get(direction_id, [])
            if len(pool) >= cap and cap > 0:
                predicted_cutoffs[direction_id].append(min(pool))

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
            prob_pct = 100.0 * code_tally.get(direction_id, 0) / trials if trials else None
            standalone_pct = (100.0 * code_standalone_tally.get(direction_id, 0) / trials
                               if trials and cap is not None else None)

            cutoffs = predicted_cutoffs.get(direction_id, [])
            predicted_cutoff = statistics.mean(cutoffs) if cutoffs else None
            predicted_gap = (score - predicted_cutoff) if predicted_cutoff is not None else None

            real_scores = [s for c2, s in real_competitors.get(direction_id, [])]
            real_count = len(real_scores)
            real_position = 1 + sum(1 for s in real_scores if s > score)
            avg_real = statistics.mean(real_scores) if real_scores else None
            min_real = min(real_scores) if real_scores else None

            bd = breakdown.get(direction_id, {"cascaded_in": 0, "consent_elsewhere": 0, "no_consent": 0})

            results.append(SimulationResult(
                run_id=run_id,
                tracked_applicant_id=applicant.id,
                direction_id=direction_id,
                deterministic_admitted=admitted_here,
                probability_pct=prob_pct,
                standalone_probability_pct=standalone_pct,
                predicted_cutoff_score=predicted_cutoff,
                predicted_gap=predicted_gap,
                real_competitor_count=real_count,
                real_competitor_position=real_position,
                avg_real_competitor_score=avg_real,
                gap_to_avg=(score - avg_real) if avg_real is not None else None,
                min_real_competitor_score=min_real,
                gap_to_min=(score - min_real) if min_real is not None else None,
                cascaded_in_count=bd["cascaded_in"],
                consent_elsewhere_count=bd["consent_elsewhere"],
                no_consent_count=bd["no_consent"],
                trials=trials,
            ))

    db.bulk_save_objects(results)
    db.commit()
    return results
