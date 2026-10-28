export interface Competition { competition_id: number }
export interface Season { season_id: number }
export interface Context { competitionId: number; seasonId: number }
export interface MatchOverview {
  competition_id: number; season_id: number; match_id: number; match_label: string;
  match_date: string; kick_off: string; competition_stage_id: number; competition_stage_name: string;
  home_team_id: number; home_team_name: string; away_team_id: number; away_team_name: string;
  home_score: number; away_score: number; display_score: string; result_method: string;
  went_to_extra_time: boolean; went_to_penalties: boolean;
  winner_team_id: number | null; winner_team_name: string | null;
}
export interface Metrics {
  event_count: number; pass_attempts: number; shot_count: number; shot_xg: number;
  shot_goals: number; under_pressure_events: number; counterpress_events: number;
}
export interface TeamMatchStats extends Metrics {
  team_id: number; team_name: string; opponent_team_id: number; opponent_team_name: string;
  is_home: boolean; goals_for: number; goals_against: number; goal_difference: number;
  match_result: string; players_with_events: number;
}
export interface PlayerMatchStats extends Metrics {
  team_id: number; team_name: string; player_id: number; player_name: string; is_home: boolean;
}
export interface Shot {
  event_id: string; event_index: number; shot_label: string;
  team_id: number; team_name: string; player_id: number | null; player_name: string | null;
  period: number; minute: number; second: number; statsbomb_xg: number;
  outcome_id: number; outcome_name: string | null; is_goal: boolean; is_extra_time: boolean;
  start_x: number | null; start_y: number | null; end_x: number | null; end_y: number | null; end_z: number | null;
}
export interface XgRacePoint {
  event_order: number; event_id: string; event_index: number; period: number; minute: number; second: number;
  team_id: number; team_name: string; is_home: boolean; cumulative_xg: number;
}
export interface ShootoutAttempt {
  shootout_order: number; team_attempt_number: number; team_id: number; team_name: string;
  player_id: number | null; player_name: string | null; outcome_id: number; outcome_name: string | null;
  is_goal: boolean; home_shootout_goals_after: number; away_shootout_goals_after: number;
}
export interface Shootout { match_id: number; went_to_penalties: boolean; attempts: ShootoutAttempt[] }
export interface MatchAnalysisResponse {
  match: MatchOverview; teams: TeamMatchStats[]; players: PlayerMatchStats[];
  shots: Shot[]; xg_race: XgRacePoint[]; shootout: Shootout;
}
export interface ApiError { error: { code: string; message: string } }

export type PassStatus = 'completed' | 'failed' | 'unknown';
export interface PassEvent {
  event_id: string; event_index: number; team_id: number; team_name: string;
  player_id: number | null; player_name: string | null; recipient_id: number | null; recipient_name: string | null;
  period: number; minute: number; second: number; start_x: number; start_y: number; end_x: number; end_y: number;
  outcome_id: number | null; outcome_name: string | null; completion_status: PassStatus;
}
export interface PassFilters { team_id?: number; player_id?: number; period?: number }
export interface PassMapResponse {
  competition_id: number; season_id: number; match_id: number;
  filters: { team_id: number | null; player_id: number | null; period: number | null };
  coordinate_system: { name: string; length: number; width: number; origin: string; x_direction: string;
    y_direction: string; orientation: string; units: string; tracking: boolean };
  response_limit: number; total_count: number; returned_count: number;
  outcome_counts: Record<PassStatus, number>;
  excluded: { count: number; reasons: { missing_coordinates: number; non_finite_coordinates: number; out_of_bounds_coordinates: number } };
  passes: PassEvent[];
}
