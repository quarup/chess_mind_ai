from chess_mind_ai.elo import blunder_budget_cp, noise_amplitude


def test_budget_at_anchor_points():
    assert blunder_budget_cp(700) == 800
    assert blunder_budget_cp(1000) == 500
    assert blunder_budget_cp(1400) == 250
    assert blunder_budget_cp(1800) == 120
    assert blunder_budget_cp(2200) == 50


def test_budget_clamps_outside_range():
    assert blunder_budget_cp(500) == 800
    assert blunder_budget_cp(3000) == 50


def test_budget_is_monotonic_decreasing():
    last = float("inf")
    for elo in range(700, 2201, 50):
        value = blunder_budget_cp(elo)
        assert value <= last
        last = value


def test_noise_decreases_with_elo():
    assert noise_amplitude(700) > noise_amplitude(1000) > noise_amplitude(2200)


def test_noise_interpolates():
    # Midway between 1000 (noise=50) and 1400 (noise=30): expect 40
    assert noise_amplitude(1200) == 40
