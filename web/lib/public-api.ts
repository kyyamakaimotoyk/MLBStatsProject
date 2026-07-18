import { getJSON } from "@/lib/api";

export type FeedGame = {
  game_pk: number;
  game_date: string;
  status: string | null;
  is_final: boolean;
  home: string;
  home_name: string;
  away: string;
  away_name: string;
  home_score: number | null;
  away_score: number | null;
  p_home: number | null;
  pred_home_runs: number | null;
  pred_away_runs: number | null;
  pred_total: number | null;
  // The betting market's pregame view when a line was captured (closing
  // preferred, morning line for tonight's games): no-vig home win
  // probability and the total line. Benchmarks only, never model inputs.
  market_p_home: number | null;
  market_total: number | null;
  pick: string;
  pick_chance: number;
  correct: boolean | null;
  watch: { name: string; p_hr: number; exp_h: number; p_hit: number }[];
};

export type Feed = { days: { date: string; games: FeedGame[] }[] };

export type Summary = {
  games_graded: number;
  winners_pct: number;
  last30_wins: number;
  last30_losses: number;
  avg_score_error: number;
  avg_total_error: number;
  batter_calls_graded: number;
  batter_hit_call_pct: number | null;
  since: string;
};

export type TeamDetail = {
  team: string;
  last10_wins: number;
  last10_losses: number;
  runs_per_game_l10: number | null;
  games: {
    game_pk: number;
    game_date: string;
    is_final: boolean;
    home: string;
    away: string;
    home_score: number | null;
    away_score: number | null;
    p_home: number | null;
    pred_home_runs: number | null;
    pred_away_runs: number | null;
    team_won: boolean | null;
  }[];
};

export type BattingGame = {
  game_date: string;
  season: number;
  home: string;
  away: string;
  home_score: number | null;
  away_score: number | null;
  pa: number | null;
  ab: number | null;
  r: number | null;
  h: number | null;
  hr: number | null;
  tb: number | null;
  rbi: number | null;
  bb: number | null;
  k: number | null;
  sb: number | null;
  exp_h: number | null;
  exp_tb: number | null;
  exp_hr: number | null;
  exp_bb: number | null;
  exp_k: number | null;
  p_hit: number | null;
  p_hr: number | null;
};

export type PitchingGame = {
  game_date: string;
  season: number;
  home: string;
  away: string;
  home_score: number | null;
  away_score: number | null;
  is_starter: boolean | null;
  outs: number | null;
  h: number | null;
  er: number | null;
  bb: number | null;
  k: number | null;
  hr: number | null;
  pitches: number | null;
};

export type PlayerDetail = {
  player_id: number;
  name: string;
  position: string | null;
  batting: {
    season: {
      season: number;
      games: number;
      pa: number;
      avg: number | null;
      obp: number | null;
      slg: number | null;
      ops: number | null;
      hr: number;
      rbi: number;
      sb: number;
    } | null;
    games: BattingGame[];
  } | null;
  pitching: {
    season: {
      season: number;
      games: number;
      starts: number;
      ip: number;
      era: number | null;
      whip: number | null;
      k9: number | null;
      so: number;
    } | null;
    games: PitchingGame[];
  } | null;
  latest_pred: {
    exp_pa: number;
    exp_h: number;
    exp_tb: number;
    exp_hr: number;
    exp_bb: number;
    exp_k: number;
    p_hit: number;
    p_hr: number;
    for_date: string;
  } | null;
};

export type TeamTrends = {
  season: number;
  stat: string;
  series: { team: string; points: { date: string; value: number; rolling: number | null }[] }[];
};

export const getTeamTrends = (stat: string, teams: string[], season?: number) =>
  getJSON<TeamTrends>(
    `/api/public/team-trends?stat=${stat}&teams=${teams.join(",")}${season ? `&season=${season}` : ""}`,
  );

export type TeamRow = {
  team_id: number;
  abbrev: string;
  name: string;
  league: string;
  division: string;
};

export type PitcherBoardRow = {
  game_pk: number;
  game_date: string;
  home: string;
  away: string;
  pitcher_id: number;
  team: string;
  pitcher: string;
  throws: string | null;
  starts: number | null;
  ip: number | null;
  era: number | null;
  whip: number | null;
  k9: number | null;
  batters_predicted: number | null;
  opp_exp_h: number | null;
  opp_exp_k: number | null;
  opp_exp_hr: number | null;
  // starter-scoped heads (B7): while the starter is in the game
  sp_exp_k: number | null;
  sp_exp_bb: number | null;
  sp_exp_h: number | null;
};

export const getPitcherBoard = () => getJSON<PitcherBoardRow[]>("/api/public/pitchers");

export const getSummary = () => getJSON<Summary>("/api/public/summary");
export const getFeed = (days = 7) => getJSON<Feed>(`/api/public/feed?days=${days}`);
export const getTeam = (abbrev: string) =>
  getJSON<TeamDetail>(`/api/public/team/${encodeURIComponent(abbrev)}`);
export const getTeams = () => getJSON<TeamRow[]>("/api/public/teams");
export const getPlayer = (id: number) => getJSON<PlayerDetail>(`/api/public/player/${id}`);
export const searchPlayers = (q: string) =>
  getJSON<{ player_id: number; full_name: string }[]>(
    `/api/public/players?q=${encodeURIComponent(q)}`,
  );
