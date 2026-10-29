import type { MatchAnalysisResponse, MatchOverview, Shot, PassMapResponse } from '../src/types';

// Small synthetic fixture using the inspected Stage 5A shape, not a full match.
export const match: MatchOverview = {
  competition_id: 11, season_id: 22, match_id: 7, match_label: '2022-12-18 | Red FC - Blue FC',
  match_date: '2022-12-18', kick_off: '17:00:00.000', competition_stage_id: 26, competition_stage_name: 'Final',
  home_team_id: 10, home_team_name: 'Red FC', away_team_id: 20, away_team_name: 'Blue FC',
  home_score: 1, away_score: 1, display_score: '1-1 (4-2 pens)', result_method: 'PENALTIES',
  went_to_extra_time: true, went_to_penalties: true, winner_team_id: 10, winner_team_name: 'Red FC',
};
export const otherMatch: MatchOverview = { ...match, match_id: 8, match_label: '2022-12-19 | Red FC - Blue FC',
  match_date: '2022-12-19', went_to_penalties: false, winner_team_id: null, winner_team_name: null,
  display_score: '1-1', result_method: 'DRAW' };
const metrics = { event_count: 10, pass_attempts: 5, shot_count: 1, shot_xg: 0.1,
  shot_goals: 1, under_pressure_events: 2, counterpress_events: 1 };
export const shot: Shot = { event_id: '00000000-0000-0000-0000-000000000001', event_index: 100,
  shot_label: 'Player One | 4:04 | Goal | #100', team_id: 10, team_name: 'Red FC', player_id: 1,
  player_name: 'Player One', period: 1, minute: 4, second: 4, statsbomb_xg: 0.1,
  outcome_id: 97, outcome_name: 'Goal', is_goal: true, is_extra_time: false,
  start_x: 108, start_y: 40, end_x: 120, end_y: 40, end_z: null };
export const analysis: MatchAnalysisResponse = {
  match,
  teams: [{ ...metrics, team_id: 10, team_name: 'Red FC', opponent_team_id: 20, opponent_team_name: 'Blue FC',
    is_home: true, goals_for: 1, goals_against: 1, goal_difference: 0, match_result: 'W', players_with_events: 1 },
    { ...metrics, team_id: 20, team_name: 'Blue FC', opponent_team_id: 10, opponent_team_name: 'Red FC',
      is_home: false, goals_for: 1, goals_against: 1, goal_difference: 0, match_result: 'L', players_with_events: 1 }],
  players: [{ ...metrics, team_id: 10, team_name: 'Red FC', player_id: 1, player_name: 'Player One', is_home: true },
    { ...metrics, event_count: 0, pass_attempts: 0, shot_count: 0, shot_xg: 0, shot_goals: 0,
      under_pressure_events: 0, counterpress_events: 0, team_id: 20, team_name: 'Blue FC', player_id: 2, player_name: 'Unused Player', is_home: false }],
  shots: [shot],
  xg_race: [{ event_order: 1, event_id: shot.event_id, event_index: 100, period: 1, minute: 4, second: 4,
    team_id: 10, team_name: 'Red FC', is_home: true, cumulative_xg: 0.1 },
    { event_order: 1, event_id: shot.event_id, event_index: 100, period: 1, minute: 4, second: 4,
      team_id: 20, team_name: 'Blue FC', is_home: false, cumulative_xg: 0 }],
  shootout: { match_id: 7, went_to_penalties: true, attempts: [{ shootout_order: 1, team_attempt_number: 1,
    team_id: 10, team_name: 'Red FC', player_id: 1, player_name: 'Player One', outcome_id: 97, outcome_name: 'Goal',
    is_goal: true, home_shootout_goals_after: 1, away_shootout_goals_after: 0 }] },
};
export const otherAnalysis: MatchAnalysisResponse = { ...analysis, match: otherMatch,
  shootout: { match_id: 8, went_to_penalties: false, attempts: [] } };

export const passMap: PassMapResponse = {
  competition_id: 11, season_id: 22, match_id: 7,
  filters: { team_id: 10, player_id: null, period: 1 },
  coordinate_system: { name: 'StatsBomb', length: 120, width: 80, origin: 'top-left', x_direction: 'right',
    y_direction: 'down', orientation: 'source_preserved', units: 'statsbomb', tracking: false },
  response_limit: 5000, total_count: 3, returned_count: 3,
  outcome_counts: { completed: 1, failed: 1, unknown: 1 },
  excluded: { count: 0, reasons: { missing_coordinates: 0, non_finite_coordinates: 0, out_of_bounds_coordinates: 0 } },
  passes: [
    { event_id: 'pass-1', event_index: 1, team_id: 10, team_name: 'Red FC', player_id: 1, player_name: 'Player One',
      recipient_id: 3, recipient_name: 'Player Three', period: 1, minute: 1, second: 2,
      start_x: 0, start_y: 80, end_x: 120, end_y: 0, outcome_id: null, outcome_name: null, completion_status: 'completed' },
    { event_id: 'pass-2', event_index: 2, team_id: 10, team_name: 'Red FC', player_id: 1, player_name: 'Player One',
      recipient_id: null, recipient_name: null, period: 1, minute: 2, second: 3,
      start_x: 5.123456789, start_y: 2, end_x: 30, end_y: 50, outcome_id: 9, outcome_name: 'Incomplete', completion_status: 'failed' },
    { event_id: 'pass-3', event_index: 3, team_id: 10, team_name: 'Red FC', player_id: 1, player_name: 'Player One',
      recipient_id: 3, recipient_name: 'Player Three', period: 1, minute: 3, second: 4,
      start_x: 120, start_y: 0, end_x: 0, end_y: 80, outcome_id: 77, outcome_name: 'Unknown', completion_status: 'unknown' },
  ],
};

export const pressureMap: import('../src/types').PressureHeatmapResponse = {
  competition_id: 11, season_id: 22, match_id: 7,
  filters: { type: 'pressure', team_id: 10, period: 1 },
  coordinate_system: { ...passMap.coordinate_system },
  grid: { columns: 12, rows: 8, cell_width: 10, cell_height: 10, boundary_rule: 'left_closed_right_open_outer_inclusive' },
  metric: { id: 'pressure_event_count', event_type: 'Pressure', type_id: 17,
    definition: 'Count of registered Pressure events per cell, not tracking movement.', normalization: 'none', smoothing: 'none' },
  intensity_scale: { kind: 'fixed_absolute_count', lower_bounds: [0, 1, 2, 4, 8, 16], top_bin: '16+' },
  total_count: 19, eligible_event_total: 19,
  excluded: { count: 0, reasons: { missing_coordinates: 0, non_finite_coordinates: 0, out_of_bounds_coordinates: 0 } },
  cells: Array.from({ length: 96 }, (_, i) => ({ column: i % 12, row: Math.floor(i / 12), count: i === 0 ? 1 : i === 13 ? 2 : i === 95 ? 16 : 0 })),
};

export const pressureCoordinates: import('../src/types').PressureCoordinatesResponse = {
  ...pressureMap, response_limit: 5000,
  points: pressureMap.cells.flatMap((cell, i) => Array.from({ length: cell.count }, (_, j) =>
    ({ event_id: `pressure-${i}-${j}`, x: cell.column * 10 + 5, y: cell.row * 10 + 5 }))),
};
