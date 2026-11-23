import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lookup_layout import layout_settings, valid_grid, weights


class LookupLayoutTests(unittest.TestCase):
    def test_legacy_split_and_ratio_migrate(self):
        value = layout_settings({'lookup_split': True, 'lookup_ratio': .35})
        self.assertEqual(value['lookup_grid'], [[0, 1]])
        self.assertEqual(value['lookup_column_weights'], [.35, .65])
        self.assertEqual(layout_settings({})['lookup_grid'], [[0]])

    def test_rectangular_grid_keeps_stable_ids(self):
        grid = [[0, 1, 4], [2, 3, 5]]
        self.assertTrue(valid_grid(grid))
        self.assertEqual(layout_settings({'lookup_grid': grid})['lookup_grid'], grid)

    def test_large_grid_is_not_artificially_capped(self):
        grid = [list(range(row * 11, (row + 1) * 11)) for row in range(11)]
        self.assertTrue(valid_grid(grid))
        self.assertEqual(len(layout_settings({'lookup_grid': grid})['lookup_grid']), 11)

    def test_closing_cells_preserves_remaining_identifiers(self):
        grid = [[0, 4, None], [7, 8, 9]]
        self.assertTrue(valid_grid(grid))
        self.assertEqual(layout_settings({'lookup_grid': grid})['lookup_grid'], grid)
        self.assertTrue(valid_grid([[0, 8]]))
        self.assertFalse(valid_grid([[0, None], [None, None]]))

    def test_invalid_or_duplicate_cells_are_rejected(self):
        for value in ([], [[1]], [[0, 0]], [[0, 1], [2]], [[0, '1']], [[False]]):
            self.assertFalse(valid_grid(value), value)

    def test_invalid_weights_fall_back_without_nan(self):
        self.assertEqual(weights([float('nan'), 1], 2), [.5, .5])
        self.assertEqual(weights([0, 1], 2), [.5, .5])
        self.assertEqual(weights([1, 3], 2), [.25, .75])
