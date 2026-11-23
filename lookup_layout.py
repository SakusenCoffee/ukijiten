"""Saved rectangular lookup layouts, with stable identifiers for each search."""
import math


def valid_grid(value):
    if not isinstance(value, list) or not value or not isinstance(value[0], list) or not value[0]:
        return False
    width = len(value[0])
    if any(not isinstance(row, list) or len(row) != width for row in value):
        return False
    cells = [cell for row in value for cell in row if cell is not None]
    return (value[0][0] == 0 and all(any(cell is not None for cell in row) for row in value)
            and all(type(cell) is int and cell >= 0 for cell in cells)
            and len(set(cells)) == len(cells))


def weights(value, count):
    if (not isinstance(value, list) or len(value) != count or any(
            type(item) not in (int, float) or not math.isfinite(item) or item <= 0 for item in value)):
        return [1 / count] * count
    total = sum(value)
    return [item / total for item in value]


def layout_settings(data):
    grid = data.get('lookup_grid')
    if not valid_grid(grid):
        grid = [[0, 1]] if data.get('lookup_split') else [[0]]
    columns, rows = len(grid[0]), len(grid)
    column_weights = data.get('lookup_column_weights')
    if column_weights is None and columns == 2:
        try:
            ratio = max(.15, min(.85, float(data.get('lookup_ratio', .5))))
        except (ValueError, TypeError):
            ratio = .5
        column_weights = [ratio, 1 - ratio]
    return dict(lookup_grid=grid, lookup_column_weights=weights(column_weights, columns),
                lookup_row_weights=weights(data.get('lookup_row_weights'), rows),
                lookup_split=sum(cell is not None for row in grid for cell in row) > 1)
