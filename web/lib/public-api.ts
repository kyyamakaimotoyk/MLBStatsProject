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
  consensus: number | null;
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

export type PlayerDetail = {
  player_id: number;
  name: string;
  l15_hits_per_game: number | null;
  l15_hr: number;
  games: {
    game_date: string;
    home: string;
    away: string;
    pa: number | null;
    h: number | null;
    hr: number | null;
    tb: number | null;
    bb: number | null;
    k: number | null;
    exp_h: number | null;
    p_hit: number | null;
    p_hr: number | null;
  }[];
};

export type TeamRow = {
  team_id: number;
  abbrev: string;
  name: string;
  league: string;
  division: string;
};

export const getSummary = () => getJSON<Summary>("/api/public/summary");
export const getFeed = (days = 7) => getJSON<Feed>(`/api/public/feed?days=${days}`);
export const getTeam = (abbrev: string) => getJSON<TeamDetail>(`/api/public/team/${abbrev}`);
export const getTeams = () => getJSON<TeamRow[]>("/api/public/teams");
export const getPlayer = (id: number) => getJSON<PlayerDetail>(`/api/public/player/${id}`);
export const searchPlayers = (q: string) =>
  getJSON<{ player_id: number; full_name: string }[]>(
    `/api/public/players?q=${encodeURIComponent(q)}`,
  );
