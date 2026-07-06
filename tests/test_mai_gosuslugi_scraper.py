import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))


class MaiGosuslugiScraperTests(unittest.TestCase):
    def test_selects_only_mai_budget_full_time_base_groups(self):
        from services.mai_gosuslugi_scraper import select_target_items

        items = [
            {
                "id": 117492,
                "oksoCode": "2.09.03.01",
                "oksoName": "Информатика и вычислительная техника",
                "educationLevelName": "Базовое высшее образование",
                "educationFormName": "Очная",
                "placeTypeName": "Основные места в рамках КЦП",
                "numberPlaces": 155,
                "programs": [{"name": "Профиль", "studyDuration": 48}],
            },
            {
                "id": 117493,
                "oksoCode": "2.09.03.02",
                "oksoName": "Не наш уровень",
                "educationLevelName": "Магистратура",
                "educationFormName": "Очная",
                "placeTypeName": "Основные места в рамках КЦП",
                "numberPlaces": 10,
            },
            {
                "id": 117494,
                "oksoCode": "2.09.03.03",
                "oksoName": "Платное",
                "educationLevelName": "Базовое высшее образование",
                "educationFormName": "Очная",
                "placeTypeName": "Платные места",
                "numberPlaces": 10,
            },
        ]

        selected = select_target_items(items)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].group_id, 117492)
        self.assertEqual(selected[0].fgos_code, "09.03.01")
        self.assertEqual(selected[0].name, "Информатика и вычислительная техника")
        self.assertEqual(selected[0].seats, 155)

    def test_converts_applicants_to_rows_and_skips_empty_scores(self):
        from services.mai_gosuslugi_scraper import rows_from_applicants

        applicants = [
            {
                "rating": 268,
                "idApplication": 1422086,
                "sumMark": 277.0,
                "priority": 1,
                "consent": "ONLINE",
            },
            {
                "rating": 999,
                "idApplication": 111,
                "sumMark": 0,
                "priority": 2,
                "consent": "NONE",
            },
        ]

        rows = rows_from_applicants(applicants)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].position, 268)
        self.assertEqual(rows[0].unique_code, "1422086")
        self.assertEqual(rows[0].total_score, 277)
        self.assertEqual(rows[0].priority, 1)
        self.assertTrue(rows[0].consent)


if __name__ == "__main__":
    unittest.main()
