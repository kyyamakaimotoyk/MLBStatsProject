-- market_p_home is COMPUTED (no-vig conversion of two moneylines), not copied
-- from a source column, and it is computed in float64. Storing it as REAL
-- silently rounded it to ~7 significant digits, which showed up as
-- 0.6219831346321605 becoming 0.6219831 in the API response.
--
-- The neighbouring columns are deliberately left as REAL: p_home,
-- pred_margin, pred_total, margin_err and total_err are all float4 by
-- construction (they come from, or are arithmetic on, REAL columns in
-- model_predictions), and market_total is copied straight from
-- odds_lines.total, which is REAL. Widening those would invent precision that
-- was never in the source.
--
-- pred_grades is derived, so this is a plain type change; the next
-- `python -m orchestration.grades --full` repopulates at full precision.
ALTER TABLE pred_grades
    ALTER COLUMN market_p_home TYPE DOUBLE PRECISION;
