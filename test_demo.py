import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "demo"))
import build_demo  # noqa: E402

F, M = build_demo.FEMALE, build_demo.MALE


def row(film, title, date, actor, gender, links=100, series="James Bond"):
    return {"s": series, "f": film, "ft": title, "d": date, "a": actor, "an": actor, "g": gender, "l": links}


class ConvertTests(unittest.TestCase):
    def test_filters_by_links_and_needs_both_genders(self):
        rows = [
            row("Q1", "Dr. No", "1962-10-05", "Ursula", F),
            row("Q1", "Dr. No", "1962-10-05", "Sean", M),
            row("Q1", "Dr. No", "1962-10-05", "Extra", M, links=3),  # 知名度不足
            row("Q2", "Only Men", "1970-01-02", "Sean", M),  # 沒有女演員 → 不收
        ]
        data = build_demo.convert(rows, 40)
        self.assertEqual([w["title"] for w in data["works"]], ["Dr. No"])
        self.assertEqual(data["works"][0]["males"], ["Sean"])
        self.assertEqual([a["name"] for a in data["actresses"]], ["Ursula"])

    def test_prefers_full_date_over_january_first(self):
        rows = [
            row("Q1", "Dr. No", "1962-01-01", "Ursula", F),
            row("Q1", "Dr. No", "1962-10-05", "Sean", M),
        ]
        self.assertEqual(build_demo.convert(rows, 1)["works"][0]["date"], "1962-10-05")

    def test_skips_unreleased_films(self):
        rows = [row("Q1", "Future", "2999-01-01", "A", F), row("Q1", "Future", "2999-01-01", "B", M)]
        self.assertEqual(build_demo.convert(rows, 1)["works"], [])

    def test_code_is_title_and_year_so_remakes_stay_distinct(self):
        rows = [
            row("Q1", "Casino Royale", "1967-04-14", "A", F), row("Q1", "Casino Royale", "1967-04-14", "B", M),
            row("Q2", "Casino Royale", "2006-11-14", "A", F), row("Q2", "Casino Royale", "2006-11-14", "B", M),
        ]
        codes = [w["code"] for w in build_demo.convert(rows, 1)["works"]]
        self.assertEqual(codes, ["Casino Royale (1967)", "Casino Royale (2006)"])

    def test_actress_counts_and_order(self):
        rows = []
        for i, d in enumerate(["2001-01-02", "2002-01-02"]):
            rows += [row(f"Q{i}", f"Film {i}", d, "Judi", F), row(f"Q{i}", f"Film {i}", d, "Daniel", M)]
        rows += [row("Q9", "Film 9", "2003-01-02", "Eva", F), row("Q9", "Film 9", "2003-01-02", "Daniel", M)]
        data = build_demo.convert(rows, 1)
        self.assertEqual([(a["name"], a["works"]) for a in data["actresses"]], [("Judi", 2), ("Eva", 1)])
        self.assertEqual(data["total_works"], 3)

    def test_unlabeled_people_are_skipped(self):
        rows = [row("Q1", "Film", "2001-01-02", "Q12345", F), row("Q1", "Film", "2001-01-02", "Bob", M)]
        self.assertEqual(build_demo.convert(rows, 1)["works"], [])


if __name__ == "__main__":
    unittest.main()
