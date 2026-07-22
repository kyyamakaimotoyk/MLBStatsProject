// English/Japanese UI dictionaries. `en` defines the shape; `ja` is type-checked
// against it, so a missing translation is a build error. (Same pattern as
// hoopmodel.com — see the NBA project's web/lib/translations.ts.)
//
// Japanese style guide (edit this glossary and the strings will follow):
//   pick / call / prediction → 予測
//   winners called           → 勝敗的中率
//   score call               → スコア予測 / score miss → スコア誤差
//   total runs               → 合計得点（トータル・オーバーアンダーとしない）
//   graded                   → 採点済み
//   market favorite          → 市場の本命 / pregame・closing line → 試合前のライン・最終ライン
//   betting                  → 賭け（ベッティングとしない）
//   coin flip / even         → 五分五分・互角（コイン投げ・コイントスと直訳しない）
//   probable pitcher         → 予告先発
//   gets a hit               → ヒットを打つ／安打（ゲットヒットとしない）
//   homer                    → 本塁打
//   hitter/batter → 打者, away → ビジター, walk → 四球, strikeout → 三振（投手側は奪三振）
//   register                 → 丁寧体（です・ます）。直訳調・過剰なカタカナ語は避ける。
// Team codes (NYY, PHI…), player names and dates stay untranslated by design.

import type { WindowKey } from "./windows";

export type Lang = "en" | "ja";

const en = {
  nav: {
    tonight: "Tonight",
    record: "Record",
    teams: "Teams",
    players: "Players",
    battersDeep: "Batters in-depth",
    modelLab: "Model lab",
    about: "About",
  },

  site: {
    tagline: "Nightly MLB predictions — with receipts.",
    subtitle:
      "A machine-learning model picks every MLB game — the winner, the score, " +
      "and the hitters to watch. Every prediction is logged, graded against the " +
      "real result, and published. Hits and misses alike.",
    disclaimer: "Predictions are machine-learning model output, not betting advice.",
    ctaTonight: "Tonight's picks",
    ctaRecord: "See the track record",
    noTonight: "Tonight's picks aren't posted yet",
    noTonightSub: "New picks go up every morning, US time.",
    clockNote: "All dates are US Eastern time.",
  },

  common: {
    loading: "Loading…",
    plusMinusRuns: (v: string) => `±${v} runs`,
    // Win–loss record, e.g. "45–30" / 「45勝30敗」.
    wl: (w: string, l: string) => `${w}–${l}`,
    tbd: "TBD",
    dash: "—",
  },

  windows: {
    "1m": "Last month",
    "2m": "Last two months",
    "3m": "Last three months",
    season: "This season",
    "2seasons": "Last two seasons",
    "3seasons": "Last three seasons",
  } as Record<WindowKey, string>,

  table: {
    matchup: "Matchup",
    pick: "Pick",
    winChance: "Win chance",
    scoreCall: "Score call",
    totalRuns: "Total runs",
    marketFavorite: "Market favorite",
    marketTotal: "Market total",
    final: "Final",
    result: "Result",
    coinFlip: "coin flip",
    even: "even",
  },

  proof: {
    winners: (window: string) => `winners called, ${window}`,
    scoreMiss: (window: string) => `average score miss, ${window}`,
    logged: "predictions logged",
    loggedSub: "and publicly scored",
    last30: "last 30 days",
    sinceYear: (y: string) => `since ${y}`,
  },

  steps: [
    {
      title: "Every pitch, in",
      body: "Play-by-play and pitch-level data from every MLB game, updated each morning.",
    },
    {
      title: "Rolling form",
      body: "Each team's recent play — and tonight's actual lineup — distilled into features.",
    },
    {
      title: "One model, three calls",
      body: "A gradient-boosted model predicts each team's runs: that's the winner, the score, and the game total.",
    },
    {
      title: "Scored in public",
      body: "Picks post every morning, then get graded against the final score.",
    },
  ],

  home: {
    predictionsFor: (date: string) => `Predictions for ${date}`,
    errLate: "Predictions are loading late — check back shortly.",
    loadingTonight: "Loading tonight's picks…",
    hittersToWatch: "Hitters to watch tonight",
    allHittersLink: "Every hitter call for tonight →",
    toHomer: (pct: string) => `${pct} to homer`,
    recentResults: "Recent results",
    showMoreDays: "Show more days",
    windowRecordBefore: "Over this window: ",
    windowRecordAfter: (pct: string, n: string) =>
      ` picking winners (${pct} across ${n} games).`,
    dayTablesNote:
      "Day-by-day tables cover the most recent 90 days; the record line above covers the whole window. The full breakdown lives on the ",
    dayTablesLink: "Record",
    dayTablesNoteEnd: " page.",
    stepLabel: (i: number) => `STEP ${i}`,
  },

  record: {
    title: "The track record",
    subtitle:
      "Every prediction gets graded against the final score — the good calls and the bad ones. Nothing is deleted, nothing is cherry-picked.",
    winnersCalled: "winners called",
    wlOver: (wl: string) => `${wl} over this window`,
    gamesGraded: "games graded",
    since: (d: string) => `since ${d}`,
    avgScoreMiss: "average score miss",
    totalRunsMiss: (v: string) => `total-runs miss ±${v}`,
    hitterCallsRight: "hitter calls right",
    hitterCallsSub: (n: string) => `"gets a hit tonight?" — ${n} graded, all time`,
    noGraded: "No graded games in this window yet.",

    marketTitle: "The model vs the market",
    marketSub:
      "The betting market's pregame line is the strongest public prediction there is, so we grade ourselves against it on every game where we have one. Lines are a benchmark only — the model never sees them.",
    usVsMarket: "winners called — us vs the market favorite",
    sameGames: (n: string) => `same ${n} games, this window`,
    totalsVsMarket: "total-runs miss — us vs the market's line",
    totalsGames: (n: string) => `${n} games with a total line`,
    upsetPicks: "our picks against the market favorite",
    upsetSub: (n: string) =>
      `we called the upset ${n} times this window — this is how those calls went`,
    linesCover: (n: string, total: string) =>
      `Pregame lines cover ${n} of ${total} graded games in this window.`,
    fewLines: (n: number) =>
      `Only ${n} game${n === 1 ? " has" : "s have"} a stored pregame line in this window — we archive lines from 2023 onward and capture them daily. Pick a longer window to see the head-to-head.`,

    hittersTitle: "The hitter calls",
    hittersBody: (n: string) =>
      `The call that separates hitters is the home run, so that's the one we lead with: every night the model names its five likeliest hitters to go deep, and we grade the list against chance. The "gets a hit?" call is graded too — ${n} calls in this window — but most starters do get a hit, so it's the easier test.`,

    threeWeeksTitle: "The last three weeks, pick by pick",
    threeWeeksSub:
      "One square per game, oldest to newest. Tap any square for the call and the final score.",
    stretch: (wl: string) => `${wl} over this stretch`,

    underHoodTitle: "Under the hood",
    chartsAppear: "Charts appear once a window has more than 100 graded games.",
    backtestNote:
      "The record includes the model's full backtest: for every past game the model was trained only on games before it, then its prediction was graded — the same rules it plays by every night now.",
  },

  charts: {
    date: "Date",
    gameDate: "Game date",
    shareOfGames: "Share of games",
    confidence: {
      title: "Hit rate by pick confidence",
      sub: "Confidence is the win chance the model gave its own pick. The orange line is the hit rate counting only picks at least that confident; the blue line is the share of games that clears the bar. A well-behaved model climbs from left to right — its surer picks should land more often. The dashed line is coin-flip.",
      x: "Minimum win chance to count the pick",
      y: "Percent of games",
      hitRate: "Hit rate",
      shareKept: "Share of games kept",
      atLeast: (v: string) => `Confidence at least ${v}%`,
    },
    skill: {
      title: "Skill curve — wins above coin-flip",
      sub: "The running total of correct picks minus half the games played: a coin-flipper drifts along zero, skill climbs. Both lines count only games with a pregame line, so the market benchmark is on the same footing.",
      y: "Wins above coin-flip",
      model: "Our model",
      market: "Market favorite",
    },
    totalSkill: {
      title: "Skill curve — the total, over or under",
      sub: "The same running total for the over/under: our side of the market's total line, right calls minus half the games. Games that land exactly on the line are pushes and count for nobody.",
      y: "Right calls above coin-flip",
      series: "Our over/under calls",
    },
    batterSkill: {
      title: "Skill curve — the hit calls",
      sub: 'The same running total for "gets a hit tonight?" — but most starters do get a hit, so the dashed line is the lazy rule that says yes for everyone, not a coin-flip. We count right calls above that rule\'s pace on the same nights; skill is only what climbs above zero.',
      y: "Right calls above the lazy rule",
      series: "Our calls vs the lazy rule",
    },
    hrWatch: {
      title: "Skill curve — the home-run watch",
      sub: "Each night the model names its five likeliest hitters to homer. Five random starters would homer at the night's base rate — the dashed line. This counts homers by our five above that pace; skill is only what climbs above zero.",
      y: "Homers above chance",
      series: "Our five vs chance",
    },
    roc: {
      title: (auc: string) => `Telling winners from losers — score ${auc}`,
      sub: "The curve should bow above the dashed line. 0.50 is guessing; 1.00 is perfect. (This is the ROC curve.)",
      x: "False alarms — losses we called wins",
      y: "Wins we caught",
    },
    marginMiss: {
      title: "How far the score calls miss",
      sub: "Predicted margin minus the real margin, in runs. Centered on zero is honest; the spread is baseball.",
      x: "Runs off — predicted margin minus actual",
      pctOfGames: (v: string) => `${v}% of games`,
      missedBy: (n: number) =>
        `missed by ${n > 0 ? `+${n}` : n} run${Math.abs(n) === 1 ? "" : "s"}`,
    },
    confusion: {
      title: "Picks vs what happened",
      sub: "Green cells are correct picks; red cells are misses. Rows are our pick, columns the real winner.",
      homeWon: "Home team won",
      awayWon: "Away team won",
      pickedHome: "Picked home",
      pickedAway: "Picked away",
      nGames: (n: string) => `${n} games`,
    },
    gameTooltip: {
      final: "Final:",
      expected: (v: string) => `(we expected ${v})`,
    },
    counting: {
      actualStat: (stat: string) => `Actual ${stat.toLowerCase()}`,
      expectedSeries: "We expected",
    },
    clear: {
      x: (stat: string) => `${stat} — at least this many`,
      y: "Chance of clearing it",
      window: "Recent games",
      model: "Model, next game",
    },
    trends: {
      y: (stat: string) => `${stat} (10-game average)`,
    },
  },

  players: {
    title: "Players",
    subtitle: "Look up any player's recent games and how our calls on them have done.",
    searchPlaceholder: "Search a player, e.g. Juan Soto",
    hitterBoardTitle: "Tonight's hitter board",
    fullBoardLink: "Full board — every hitter, any date →",
    hitterBoardSub:
      "Ranked by home-run chance — the call that separates hitters most on any given night.",
    noHitters: "No hitter predictions posted yet today.",
    colHitter: "Hitter",
    colGame: "Game",
    colFacing: "Facing",
    colHomers: "Homers",
    colTb2: "2+ total bases",
    colHit: "Gets a hit",
    hitterFoot:
      'Chances cover the whole game. We lead with home runs and extra bases because they separate hitters — most starters get a hit on any given night, so "gets a hit" runs 50–70% for nearly everyone.',
    pitchingTitle: "Tonight's pitching matchups",
    pitchingSub:
      "Every probable starter, with what our model expects them to allow while they're in the game — strikeouts, walks, and hits, built from our per-hitter calls against the exact lineup they face. Most strikeouts expected first.",
    noPitchers: "No probable starters posted yet today.",
    colPitcher: "Pitcher",
    colEra: "ERA",
    colWhip: "WHIP",
    colK9: "K/9",
    colExpK: "Ks expected",
    colExpBb: "Walks expected",
    colExpH: "Hits allowed expected",
    throws: (t: string) => `${t}HP`,
    pitchingFoot:
      'Season numbers are through last night. "Expected" columns cover only the starter\'s share of the game — how long he typically lasts, against tonight\'s exact lineup — so they read like a real pitching line.',
  },

  playerDetail: {
    notFound: "Player not found.",
    batStats: {
      h: "Hits",
      tb: "Total bases",
      hr: "Home runs",
      bb: "Walks",
      k: "Strikeouts",
      rbi: "RBI",
      r: "Runs",
    } as Record<string, string>,
    pitStats: {
      k: "Strikeouts",
      er: "Earned runs",
      innings: "Innings",
    } as Record<string, string>,
    windows: {
      "2w": "Last two weeks",
      "1m": "Last month",
      season: "This season",
    } as Record<string, string>,
    hitting: (season: number) => `Hitting — ${season}`,
    pitching: (season: number) => `Pitching — ${season}`,
    tiles: {
      avg: "Batting avg",
      obp: "On-base",
      slg: "Slugging",
      ops: "OPS",
      hr: "Home runs",
      rbi: "RBI",
      sb: "Steals",
      games: "Games",
      era: "ERA",
      whip: "WHIP",
      k9: "K per 9",
      so: "Strikeouts",
      ip: "Innings",
      starts: "Starts",
    },
    clearTitle: "Clearing a line",
    clearSub: (name: string) =>
      `Pick a stat and a number. Blue is how often ${name.split(" ").pop()} has cleared it this season; orange is the model's chance for the next game.`,
    atLeast: "at least",
    gamesThisSeason: "Games this season",
    avgPerGame: "Average per game",
    clearedTile: (line: number) => `Cleared ${line}+ (season)`,
    modelNextGame: "Model, next game",
    recentTitle: "Recent games, our calls graded",
    colDate: "Date",
    colGame: "Game",
    colSaidHit: "We said (a hit)",
    colRight: "Right?",
  },

  teams: {
    title: "Teams",
    trendsTitle: "Stat trends",
    trendsSub:
      "Pick up to six teams and a stat — the lines are 10-game rolling averages across this season.",
    trendStats: {
      runs_scored: "Runs scored",
      runs_allowed: "Runs allowed",
      run_diff: "Run difference",
      total_runs: "Total runs in their games",
    } as Record<string, string>,
    pickOne: "Pick at least one team.",
    teamPages: "Team pages",
  },

  teamPage: {
    notFound: "No recent games found.",
    last10: "Last 10:",
    scoring: (v: string) => `scoring ${v} runs a game`,
    colDate: "Date",
    colGame: "Game",
    colScore: "Score",
    colWl: "W/L",
    colOurCall: "Our call",
    colRight: "Right?",
    win: "W",
    loss: "L",
    teamToWin: (team: string, pct: string) => `${team} to win (${pct})`,
    opponent: (pct: string) => `opponent (${pct})`,
  },

  batters: {
    title: "Batter vs probable pitcher",
    allGames: "all games",
    noneFor: (date: string) => `No batter predictions for ${date}.`,
    colBatter: "Batter",
    colSlot: "Slot",
    colGame: "Game",
    colVsSp: "vs SP",
    colPHit: "P(hit)",
    colPHr: "P(HR)",
    colPTb2: "P(2+ TB)",
    colEH: "E[H]",
    colETb: "E[TB]",
    colEK: "E[K]",
  },

  perf: {
    title: "Model performance",
    lastNDays: (d: number) => `last ${d} days`,
    teamHeading: "Team models (vs final scores)",
    noGraded: "No graded predictions yet.",
    colModel: "Model",
    colVersion: "Version",
    colN: "N",
    colWinAcc: "Win acc",
    colMarginMae: "Margin MAE",
    colTotalMae: "Total MAE",
    marketHeading: "Vs closing line",
    noMarket: "No graded games with captured closing lines yet.",
    colModelAcc: "Model acc",
    colMarketAcc: "Market acc",
    colAgreement: "Pick agreement",
    batterHeading: "Batter model",
    colBrierHit: "Brier P(hit)",
    colBrierHr: "Brier P(HR)",
    colMaeHits: "MAE hits",
  },

  about: {
    title: "About",
    intro:
      "A side project built by Kai Y. that predicts MLB game winners, final scores, and run totals — plus how each hitter will do against the night's starting pitcher — and keeps score on itself, in public.",
    whatTitle: "What this is",
    whatBody:
      "Every morning, a machine-learning model predicts each MLB game: who wins, by roughly what score, and how many runs get scored. A second model works one plate appearance at a time and turns into hitter outlooks — the chance each starter gets a hit or homers tonight. Every prediction is logged before first pitch and graded against the box score after. The record is published whole: hits, misses, and everything.",
    dataTitle: "The data",
    dataBody:
      "The models train on eight seasons of play-by-play from the official MLB feed and nearly six million individual pitches of Statcast tracking data — exit velocity, pitch types, quality of contact. Team form is distilled into rolling features: recent scoring, starting-pitcher quality over the last ten starts, bullpen workload, and the actual posted lineup — who is in tonight, who is missing, and how much that lineup usually produces. Park effects and game-time weather forecasts feed the run-total side.",
    modelsTitle: "The models",
    modelsBody1:
      "The game model is a gradient-boosted system that predicts each team's runs directly — the winner, the score call, and the game total all fall out of the same prediction, so they can never disagree with each other. The hitter model classifies every plate appearance into eight outcomes (strikeout, walk, single, homer, and so on) from the batter's shrunken skill profile crossed with the opposing pitcher's arsenal, then aggregates the night's expected line analytically.",
    modelsBody2:
      "A deliberately simple rating system runs alongside as the in-house benchmark. Every change to the models must beat what came before on thousands of paired games — with significance tests, not vibes — before it ships. Most candidate ideas fail that bar, and the failures are logged too.",
    cycleTitle: "The daily cycle",
    cycleBody:
      "A scheduled job runs each morning: it ingests yesterday's games, re-grades every outstanding prediction, refreshes team and player form, retrains on a weekly cadence, and posts the day's picks. A second run in the late afternoon picks up the actual starting lineups once teams post them, sharpening the hitter outlooks and the missing-regulars signal before first pitch.",
    honestTitle: "Keeping myself honest",
    honestBody:
      'Accuracy alone can flatter, so the record page shows more: how far the score calls miss, whether a "60% chance" wins 60% of the time, and the model\'s picks graded next to the betting market\'s closing expectations — the strongest public benchmark there is. The historical record is a strict walk-forward backtest: for every past game the model was trained only on games that came before it, under the same rules it plays by every night now. An automated test guarantees no prediction ever peeks at the future.',
    notTitle: "What this is not",
    notBody:
      "Betting advice. The models and their outputs are published for curiosity, learning, and record-keeping only.",
    hoodTitle: "Under the hood",
    hoodBody:
      "Python and LightGBM for the models; PostgreSQL on AWS for eight seasons of games, plate appearances, and pitches; the pipeline runs as scheduled batch jobs on AWS Fargate; this site is a static Next.js frontend reading a small FastAPI service. The whole system — ingestion to models to this page — is a successor to ",
    hoodLink: "hoopmodel.com",
    hoodBodyEnd: ", rebuilt cloud-native for baseball.",
  },

  footer: {
    privacy: "Privacy",
    cookieSettings: "Cookie settings",
  },

  ads: {
    label: "Advertisement",
  },

  consent: {
    title: "Cookies & privacy.",
    body:
      "This site uses Google Analytics to understand how it's read, and Google AdSense ads to cover its costs. In the EEA, UK, and Switzerland these cookies stay off unless you opt in — if you decline, ads are shown non-personalized and analytics runs without cookies.",
    acceptAll: "Accept all",
    declineAll: "Essential only",
    privacyLink: "Privacy policy",
  },

  privacy: {
    title: "Privacy",
    updated: (date: string) => `Last updated ${date}`,
    intro:
      "moundmodel.com is a personal side project run by Kai Y. This page explains what data the site touches, why, and the choices you have. The short version: the site shows the same content to everyone, has no accounts, builds no personal profiles, and uses Google services for exactly two things — understanding traffic and funding the site with ads.",
    hostTitle: "Hosting & server logs",
    hostBody:
      "The site is served from Amazon Web Services (S3 + CloudFront). Like nearly every web server, CloudFront writes standard access logs — IP address, requested page, timestamp, and browser user agent. They're used only to operate the site and understand aggregate traffic, and are deleted automatically after 90 days.",
    analyticsTitle: "Analytics (Google Analytics 4)",
    analyticsBody:
      "We use Google Analytics 4 to see which pages get read and roughly where visitors come from. In the EEA, the UK, and Switzerland, analytics cookies stay off until you opt in through the cookie banner (Google Consent Mode v2); if you decline, Google receives only cookieless, aggregate signals. You can also block Analytics entirely with the opt-out browser add-on linked below.",
    adsTitle: "Advertising (Google AdSense)",
    adsBody1:
      "The site shows ads through Google AdSense to cover its running costs. Google and its partners may use advertising cookies to limit how often you see an ad and — where you've consented — to personalize the ads you see.",
    adsBody2:
      "In the EEA, the UK, and Switzerland, advertising cookies default to off: unless you accept them in the cookie banner, ads are served non-personalized. You can also manage ad personalization for your Google account at any time via the links below.",
    consentTitle: "Your choices",
    consentBody:
      "Your cookie choice is stored in your own browser (localStorage, key “moundmodel-consent”) and applied on every visit. You can change it whenever you like:",
    cookieSettings: "Open cookie settings",
    linksTitle: "Learn more / opt out",
    links: [
      {
        label: "How Google uses information from sites that use its services",
        href: "https://policies.google.com/technologies/partner-sites",
      },
      {
        label: "Google privacy policy",
        href: "https://policies.google.com/privacy",
      },
      {
        label: "Google Ads Settings — manage ad personalization",
        href: "https://adssettings.google.com",
      },
      {
        label: "Google Analytics opt-out browser add-on",
        href: "https://tools.google.com/dlpage/gaoptout",
      },
      {
        label: "More about interest-based ads (YourAdChoices)",
        href: "https://optout.aboutads.info",
      },
    ],
    changesBody:
      "If how the site handles data changes, this page will be updated and the date above revised.",
  },

  strip: {
    chipTitle: (away: string, home: string, pick: string, pct: string) =>
      `${away} @ ${home}: picked ${pick} (${pct})`,
    chipAria: (date: string, away: string, home: string, ok: boolean) =>
      `${date}: ${away} at ${home}, ${ok ? "correct" : "missed"} — tap for the call and the final score`,
    gotIt: "✓ got it",
    missed: "✗ missed",
    pickedBefore: "Picked ",
    pickedAfter: (pct: string) => ` to win (${pct})`,
    scoreCallLabel: "Score call",
    finalLabel: "Final",
  },
};

export type Dict = typeof en;

const ja: Dict = {
  nav: {
    tonight: "本日の予測",
    record: "的中実績",
    teams: "チーム",
    players: "選手",
    battersDeep: "打者予測の詳細",
    modelLab: "モデルの詳細",
    about: "このサイトについて",
  },

  site: {
    tagline: "MLBの全試合を、毎日予測。",
    subtitle:
      "機械学習モデルがMLBの全試合を予測します。勝敗、スコア、そして注目の打者まで。" +
      "予測はすべて試合前に記録し、実際の結果と照らし合わせて採点したうえで、" +
      "当たりも外れもそのまま公開しています。",
    disclaimer:
      "本サイトの予測は機械学習モデルの出力であり、賭けを推奨するものではありません。",
    ctaTonight: "本日の予測を見る",
    ctaRecord: "これまでの実績を見る",
    noTonight: "本日の予測はまだ掲載されていません",
    noTonightSub: "新しい予測は毎日、米国時間の朝に掲載されます。",
    clockNote: "日付はすべて米国東部時間です。",
  },

  common: {
    loading: "読み込んでいます…",
    plusMinusRuns: (v: string) => `±${v}点`,
    wl: (w: string, l: string) => `${w}勝${l}敗`,
    tbd: "未定",
    dash: "—",
  },

  windows: {
    "1m": "直近1か月",
    "2m": "直近2か月",
    "3m": "直近3か月",
    season: "今シーズン",
    "2seasons": "過去2シーズン",
    "3seasons": "過去3シーズン",
  } as Record<WindowKey, string>,

  table: {
    matchup: "対戦カード",
    pick: "予測",
    winChance: "勝率",
    scoreCall: "スコア予測",
    totalRuns: "合計得点",
    marketFavorite: "市場の本命",
    marketTotal: "市場の合計",
    final: "最終スコア",
    result: "結果",
    coinFlip: "五分五分",
    even: "互角",
  },

  proof: {
    winners: (window: string) => `勝敗的中率（${window}）`,
    scoreMiss: (window: string) => `平均スコア誤差（${window}）`,
    logged: "これまでの予測数",
    loggedSub: "（全件を公開・採点）",
    last30: "直近30日",
    sinceYear: (y: string) => `${y}年以降`,
  },

  steps: [
    {
      title: "一球ごとのデータを収集",
      body: "MLB公式フィードの全試合・一球単位のデータを、毎朝取り込みます。",
    },
    {
      title: "直近の調子を数値化",
      body: "各チームの最近の戦いぶりと、当日の実際のスタメンを特徴量に落とし込みます。",
    },
    {
      title: "1つのモデルで3つの予測",
      body: "勾配ブースティングモデルが両チームの得点を直接予測します。勝敗もスコアも合計得点も、同じ予測から導かれます。",
    },
    {
      title: "結果を公開採点",
      body: "予測は毎朝掲載され、最終スコアと照らし合わせて採点されます。",
    },
  ],

  home: {
    predictionsFor: (date: string) => `${date}の予測`,
    errLate: "予測の読み込みに時間がかかっています。しばらくしてからもう一度ご覧ください。",
    loadingTonight: "本日の予測を読み込んでいます…",
    hittersToWatch: "本日の注目打者",
    allHittersLink: "本日の打者予測をすべて見る →",
    toHomer: (pct: string) => `本塁打確率 ${pct}`,
    recentResults: "直近の結果",
    showMoreDays: "さらに表示する",
    windowRecordBefore: "この期間の勝敗予測は ",
    windowRecordAfter: (pct: string, n: string) =>
      `（${n}試合・的中率${pct}）です。`,
    dayTablesNote:
      "日別の一覧に表示されるのは直近90日分です（上の成績は期間全体の集計です）。詳しい内訳は",
    dayTablesLink: "的中実績",
    dayTablesNoteEnd: "のページをご覧ください。",
    stepLabel: (i: number) => `STEP ${i}`,
  },

  record: {
    title: "的中実績",
    subtitle:
      "すべての予測を最終スコアと照らし合わせて採点しています。良い予測もそうでない予測も、削除も選り好みも一切ありません。",
    winnersCalled: "勝敗的中率",
    wlOver: (wl: string) => `この期間 ${wl}`,
    gamesGraded: "採点済みの試合数",
    since: (d: string) => `${d}以降`,
    avgScoreMiss: "平均スコア誤差",
    totalRunsMiss: (v: string) => `合計得点の誤差 ±${v}点`,
    hitterCallsRight: "打者予測の的中率",
    hitterCallsSub: (n: string) => `「今夜ヒットを打つか？」— 全期間で${n}件を採点`,
    noGraded: "この期間には、採点済みの試合がまだありません。",

    marketTitle: "モデルと市場の比較",
    marketSub:
      "賭け市場の試合前のラインは、世の中で最も強力な公開予測です。そのため、ラインが手元にある試合では必ずそれを基準に自己採点しています。ラインはあくまで比較対象であり、モデルには一切入力されません。",
    usVsMarket: "勝敗的中率 — 当モデル vs 市場の本命",
    sameGames: (n: string) => `この期間の同じ${n}試合で比較`,
    totalsVsMarket: "合計得点の誤差 — 当モデル vs 市場のライン",
    totalsGames: (n: string) => `合計得点ラインのある${n}試合`,
    upsetPicks: "市場の本命に逆らった予測",
    upsetSub: (n: string) =>
      `この期間に${n}回、番狂わせを予測しました。その結果がこの成績です`,
    linesCover: (n: string, total: string) =>
      `この期間の採点済み${total}試合のうち、${n}試合に試合前のラインがあります。`,
    fewLines: (n: number) =>
      `この期間に試合前のラインが保存されている試合は${n}試合のみです。ラインは2023年以降、毎日収集して保存しています。より長い期間を選ぶと直接比較をご覧いただけます。`,

    hittersTitle: "打者予測",
    hittersBody: (n: string) =>
      `打者の力量の差がいちばん表れるのは本塁打です。そこでモデルは毎晩、本塁打が最も出そうな打者を5人挙げ、その顔ぶれを偶然と比べて採点しています。「ヒットを打つか？」の予測も採点していますが（この期間で${n}件）、先発出場する打者の多くはヒットを打つため、こちらは易しめのテストです。`,

    threeWeeksTitle: "直近3週間、1試合ずつ",
    threeWeeksSub:
      "1マスが1試合です（左から古い順）。マスをタップすると、予測と最終スコアが表示されます。",
    stretch: (wl: string) => `この期間は${wl}`,

    underHoodTitle: "モデルの中身",
    chartsAppear: "グラフは、期間内の採点済み試合が100試合を超えると表示されます。",
    backtestNote:
      "実績にはモデルのバックテスト全体も含まれています。過去のどの試合についても、モデルはその試合より前の試合だけで学習したうえで予測し、採点されています。現在毎晩使っているのと同じルールです。",
  },

  charts: {
    date: "日付",
    gameDate: "試合日",
    shareOfGames: "試合の割合",
    confidence: {
      title: "確信度別の的中率",
      sub: "確信度は、モデルが自分の予測に与えた勝率です。オレンジの線はその確信度以上の予測だけを数えた的中率、青の線はその基準を満たす試合の割合を示します。健全なモデルほどグラフは右肩上がりになり、確信の強い予測ほどよく当たるはずです。破線は五分五分の50%です。",
      x: "集計に含める最低勝率",
      y: "試合の割合",
      hitRate: "的中率",
      shareKept: "対象となる試合の割合",
      atLeast: (v: string) => `確信度${v}%以上`,
    },
    skill: {
      title: "スキルカーブ — 五分五分を上回る的中数",
      sub: "（的中数 − 試合数の半分）の累計です。当てずっぽうなら0付近を漂い、実力があれば右肩上がりになります。どちらの線も試合前のラインがある試合だけを対象にしているため、市場のベンチマークと同じ土俵で比較できます。",
      y: "五分五分超過の的中数",
      model: "当モデル",
      market: "市場の本命",
    },
    totalSkill: {
      title: "スキルカーブ — 合計得点の上か下か",
      sub: "同じ累計を、市場の合計得点ラインの上下予測について見たものです。的中数から試合数の半分を引いて集計し、ちょうどラインどおりに終わった試合は引き分け扱いで、どちらにも数えません。",
      y: "五分五分超過の的中数",
      series: "合計得点の上下予測",
    },
    batterSkill: {
      title: "スキルカーブ — ヒット予測",
      sub: "「今夜ヒットを打つか？」についての同じ累計です。ただし先発出場する打者の多くはヒットを打つため、破線が表すのは全員に「打つ」と答える手抜きのルールで、五分五分ではありません。同じ夜にその基準を上回った的中数を数えており、0より上に伸びたぶんだけが実力です。",
      y: "手抜きルール超過の的中数",
      series: "当モデルと手抜きルールの差",
    },
    hrWatch: {
      title: "スキルカーブ — 本塁打ウォッチ",
      sub: "モデルは毎晩、本塁打が最も出そうな打者を5人挙げます。無作為に選んだ5人なら、その夜の平均的な確率でしか本塁打は出ません（破線）。このグラフはモデルの5人がそのペースを上回って打った本塁打の累計で、0より上に伸びたぶんだけが実力です。",
      y: "偶然を上回る本塁打数",
      series: "モデルの5人と偶然の差",
    },
    roc: {
      title: (auc: string) => `勝敗の見極め — スコア ${auc}`,
      sub: "曲線が破線より上に膨らむほど優秀です。0.50は当てずっぽう、1.00は完璧を意味します（ROC曲線と呼ばれるものです）。",
      x: "誤警報 — 勝ちと予測して負けた割合",
      y: "捉えた勝利の割合",
    },
    marginMiss: {
      title: "スコア予測のずれ",
      sub: "予測点差から実際の点差を引いた値です（単位は点）。0を中心に分布していれば偏りはありません。裾野の広さは野球というスポーツの性質です。",
      x: "ずれ（点） — 予測点差 − 実際の点差",
      pctOfGames: (v: string) => `試合の${v}%`,
      missedBy: (n: number) => `ずれ ${n > 0 ? `+${n}` : n}点`,
    },
    confusion: {
      title: "予測と実際の結果",
      sub: "緑のマスが的中、赤のマスが外れです。行がモデルの予測、列が実際の勝者を表します。",
      homeWon: "ホームが勝利",
      awayWon: "ビジターが勝利",
      pickedHome: "ホームと予測",
      pickedAway: "ビジターと予測",
      nGames: (n: string) => `${n}試合`,
    },
    gameTooltip: {
      final: "最終スコア:",
      expected: (v: string) => `（予測 ${v}）`,
    },
    counting: {
      actualStat: (stat: string) => `実際の${stat}`,
      expectedSeries: "モデルの予測",
    },
    clear: {
      x: (stat: string) => `${stat} — この数以上`,
      y: "超える確率",
      window: "今季の実績",
      model: "モデルの次戦予測",
    },
    trends: {
      y: (stat: string) => `${stat}（直近10試合平均）`,
    },
  },

  players: {
    title: "選手",
    subtitle:
      "選手を検索すると、最近の試合成績と、その選手に対する当サイトの予測の成績を確認できます。",
    searchPlaceholder: "選手名で検索（例: Juan Soto）",
    hitterBoardTitle: "本日の打者ボード",
    fullBoardLink: "完全版を見る（全打者・日付指定）→",
    hitterBoardSub:
      "本塁打の確率が高い順に並べています。一晩の予測で打者の差がいちばん表れる項目です。",
    noHitters: "本日の打者予測はまだ掲載されていません。",
    colHitter: "打者",
    colGame: "試合",
    colFacing: "対戦投手",
    colHomers: "本塁打",
    colTb2: "塁打数2以上",
    colHit: "安打",
    hitterFoot:
      "確率はいずれも試合全体を通してのものです。本塁打と長打を先頭に置いているのは、打者の差が表れやすいからです。先発出場する打者の多くはその日ヒットを打つため、「安打」の確率はほぼ全員が50〜70%になります。",
    pitchingTitle: "本日の先発投手",
    pitchingSub:
      "全試合の予告先発と、登板している間に許すとモデルが見込む成績です。奪三振・与四球・被安打を、実際に対戦する打線への打者ごとの予測から積み上げています。奪三振の見込みが多い順です。",
    noPitchers: "本日の予告先発はまだ発表されていません。",
    colPitcher: "投手",
    colEra: "防御率",
    colWhip: "WHIP",
    colK9: "K/9",
    colExpK: "予想奪三振",
    colExpBb: "予想与四球",
    colExpH: "予想被安打",
    throws: (t: string) => (t === "R" ? "右投" : t === "L" ? "左投" : t),
    pitchingFoot:
      "シーズン成績は前日までのものです。「予想」の列は先発投手が登板している間だけが対象です。普段どのくらいの回まで投げるかと、今夜実際に対戦する打線を織り込んでいるため、現実の投球成績と同じ感覚で読めます。",
  },

  playerDetail: {
    notFound: "選手が見つかりませんでした。",
    batStats: {
      h: "安打",
      tb: "塁打",
      hr: "本塁打",
      bb: "四球",
      k: "三振",
      rbi: "打点",
      r: "得点",
    } as Record<string, string>,
    pitStats: {
      k: "奪三振",
      er: "自責点",
      innings: "投球回",
    } as Record<string, string>,
    windows: {
      "2w": "直近2週間",
      "1m": "直近1か月",
      season: "今シーズン",
    } as Record<string, string>,
    hitting: (season: number) => `打撃成績 — ${season}`,
    pitching: (season: number) => `投球成績 — ${season}`,
    tiles: {
      avg: "打率",
      obp: "出塁率",
      slg: "長打率",
      ops: "OPS",
      hr: "本塁打",
      rbi: "打点",
      sb: "盗塁",
      games: "試合数",
      era: "防御率",
      whip: "WHIP",
      k9: "K/9",
      so: "奪三振",
      ip: "投球回",
      starts: "先発数",
    },
    clearTitle: "基準値超えの割合",
    clearSub: (name: string) =>
      `スタッツと数字を選んでください。青は${name}選手が今シーズンその数字以上を記録した割合、オレンジは次の試合でモデルが見込む確率です。`,
    atLeast: "の基準値:",
    gamesThisSeason: "今季の試合数",
    avgPerGame: "1試合平均",
    clearedTile: (line: number) => `${line}以上を記録（今季）`,
    modelNextGame: "モデルの次戦予測",
    recentTitle: "最近の試合と、その予測の採点",
    colDate: "日付",
    colGame: "試合",
    colSaidHit: "安打の予測確率",
    colRight: "的中",
  },

  teams: {
    title: "チーム",
    trendsTitle: "スタッツの推移",
    trendsSub:
      "チームを最大6つと、スタッツをひとつ選んでください。線は今シーズンの直近10試合移動平均です。",
    trendStats: {
      runs_scored: "得点",
      runs_allowed: "失点",
      run_diff: "得失点差",
      total_runs: "試合の両チーム合計得点",
    } as Record<string, string>,
    pickOne: "チームをひとつ以上選んでください。",
    teamPages: "チーム別ページ",
  },

  teamPage: {
    notFound: "最近の試合が見つかりませんでした。",
    last10: "直近10試合:",
    scoring: (v: string) => `1試合平均${v}得点`,
    colDate: "日付",
    colGame: "試合",
    colScore: "スコア",
    colWl: "勝敗",
    colOurCall: "当モデルの予測",
    colRight: "的中",
    win: "勝",
    loss: "敗",
    teamToWin: (team: string, pct: string) => `${team}の勝利（${pct}）`,
    opponent: (pct: string) => `相手の勝利（${pct}）`,
  },

  batters: {
    title: "打者 × 予告先発",
    allGames: "全試合",
    noneFor: (date: string) => `${date}の打者予測はありません。`,
    colBatter: "打者",
    colSlot: "打順",
    colGame: "試合",
    colVsSp: "対先発",
    colPHit: "P(安打)",
    colPHr: "P(本塁打)",
    colPTb2: "P(塁打2+)",
    colEH: "E[安打]",
    colETb: "E[塁打]",
    colEK: "E[三振]",
  },

  perf: {
    title: "モデルの成績",
    lastNDays: (d: number) => `直近${d}日`,
    teamHeading: "チームモデル（最終スコアで採点）",
    noGraded: "採点済みの予測はまだありません。",
    colModel: "モデル",
    colVersion: "バージョン",
    colN: "N",
    colWinAcc: "勝敗的中率",
    colMarginMae: "点差MAE",
    colTotalMae: "合計得点MAE",
    marketHeading: "市場の最終ラインとの比較",
    noMarket: "最終ラインを記録済みの採点対象試合はまだありません。",
    colModelAcc: "モデル的中率",
    colMarketAcc: "市場的中率",
    colAgreement: "予測の一致率",
    batterHeading: "打者モデル",
    colBrierHit: "Brier P(安打)",
    colBrierHr: "Brier P(本塁打)",
    colMaeHits: "安打MAE",
  },

  about: {
    title: "このサイトについて",
    intro:
      "Kai Y. が個人プロジェクトとして開発したサイトです。MLBの各試合の勝敗、最終スコア、合計得点に加えて、各打者がその日の先発投手を相手にどんな成績を残すかを予測し、その予測の成績を公開の場で記録し続けています。",
    whatTitle: "何をしているのか",
    whatBody:
      "毎朝、機械学習モデルがMLBの全試合を予測します。どちらが勝つか、おおよそのスコアはどうなるか、そして合計で何点入るか。もうひとつのモデルは1打席ずつの計算を積み上げ、各打者が今夜ヒットや本塁打を打つ確率という打者予測に仕上げます。予測はすべて試合開始前に記録し、試合後にボックススコアと照らし合わせて採点します。記録は当たりも外れも含めて、すべてそのまま公開しています。",
    dataTitle: "データ",
    dataBody:
      "モデルの学習には、MLB公式フィード8シーズン分の全打席データと、約600万球分のStatcastトラッキングデータ（打球速度、球種、打球の質）を使っています。チームの調子は移動平均の特徴量に集約します。直近の得点力、先発投手の直近10登板の内容、ブルペンの稼働状況、そして実際に発表されたスタメン――今夜誰が出るのか、誰が欠けているのか、その打線が普段どれだけ得点するのか。球場ごとの特性と試合時間帯の天気予報は、合計得点の予測に反映されます。",
    modelsTitle: "モデル",
    modelsBody1:
      "試合モデルは勾配ブースティング方式で、両チームの得点を直接予測します。勝敗もスコアも合計得点も同じ予測から導かれるため、互いに矛盾することがありません。打者モデルはすべての打席を8種類の結果（三振、四球、単打、本塁打など）に分類します。縮小推定した打者のスキルプロファイルに相手投手の球種構成を掛け合わせ、その夜の期待成績を解析的に積み上げます。",
    modelsBody2:
      "あわせて、意図的にシンプルに作ったレーティングシステムを内部ベンチマークとして走らせています。モデルへの変更は、数千の対応試合で従来版を上回ること――感覚ではなく有意性検定で――を確認してからでないと本番に載りません。候補となるアイデアの大半はこの基準を超えられず、その失敗も記録に残しています。",
    cycleTitle: "毎日の流れ",
    cycleBody:
      "毎朝、定時ジョブが動きます。前日の試合を取り込み、未採点の予測をすべて採点し、チームと選手の調子を更新し、週1回のペースで再学習し、その日の予測を掲載します。午後遅くにはもう一度実行し、各チームが発表した実際のスタメンを取り込んで、打者予測と主力欠場のシグナルを試合前に磨き直します。",
    honestTitle: "ごまかしのない採点のために",
    honestBody:
      "的中率だけでは、実力を実際より良く見せられてしまいます。そこで実績ページでは一歩踏み込んで示しています。スコア予測がどれだけずれたか、「勝率60%」の予測が本当に60%勝っているか、そして賭け市場の最終予想――世の中で最も強力な公開ベンチマーク――と並べて採点したモデルの成績。過去の実績は厳密なウォークフォワード方式のバックテストで、どの試合についても、その試合より前の試合だけで学習したモデルが、現在毎晩使っているのと同じルールで予測しています。予測が未来の情報を覗き見していないことは、自動テストで保証しています。",
    notTitle: "このサイトではないもの",
    notBody:
      "賭けの助言ではありません。モデルとその出力は、好奇心と学習、そして記録のためだけに公開しています。",
    hoodTitle: "技術構成",
    hoodBody:
      "モデルはPythonとLightGBM。8シーズン分の試合・打席・投球データはAWS上のPostgreSQLに保存しています。パイプラインはAWS Fargate上の定時バッチ処理として動き、このサイトは静的書き出ししたNext.jsのフロントエンドが小さなFastAPIサービスを読む構成です。データ取り込みからモデル、このページまで、システム全体が",
    hoodLink: "hoopmodel.com",
    hoodBodyEnd: "の後継として、野球向けにクラウドネイティブで作り直したものです。",
  },

  footer: {
    privacy: "プライバシーポリシー",
    cookieSettings: "Cookie設定",
  },

  ads: {
    label: "広告",
  },

  consent: {
    title: "Cookieとプライバシーについて。",
    body:
      "本サイトでは、閲覧状況の把握のためにGoogle アナリティクスを、運営費をまかなう広告表示のためにGoogle AdSenseを使用しています。EEA・英国・スイスでは、同意いただくまでこれらのCookieは無効のままです。同意されない場合も、広告は非パーソナライズで表示され、アクセス解析はCookieを使わずに行われます。",
    acceptAll: "すべて同意する",
    declineAll: "必要最小限のみ",
    privacyLink: "プライバシーポリシー",
  },

  privacy: {
    title: "プライバシーポリシー",
    updated: (date: string) => `最終更新日：${date}`,
    intro:
      "moundmodel.com は Kai Y. が個人で運営するサイドプロジェクトです。このページでは、本サイトがどのようなデータを何のために扱うのか、そして閲覧者の皆さんが選べることを説明します。要点を先に述べると――本サイトは全員に同じ内容を表示し、アカウント登録はなく、個人プロファイルも作成しません。Googleのサービスを使うのは、アクセス状況の把握と広告表示の2つの目的だけです。",
    hostTitle: "ホスティングとサーバーログ",
    hostBody:
      "本サイトは Amazon Web Services（S3 + CloudFront）から配信されています。一般的なWebサーバーと同様に、CloudFrontは標準的なアクセスログ（IPアドレス、閲覧ページ、時刻、ブラウザのユーザーエージェント）を記録します。これらはサイトの運営と全体的なアクセス傾向の把握のみに使用し、90日後に自動的に削除されます。",
    analyticsTitle: "アクセス解析（Google アナリティクス 4）",
    analyticsBody:
      "どのページが読まれているか、どの地域からの訪問が多いかを把握するために Google アナリティクス 4 を使用しています。EEA・英国・スイスでは、Cookieバナーで同意いただくまで解析用Cookieは無効です（Google同意モード v2）。同意されない場合、GoogleにはCookieを使わない集計用の信号のみが送られます。下記リンクのオプトアウト用アドオンで、解析自体を完全にブロックすることもできます。",
    adsTitle: "広告（Google AdSense）",
    adsBody1:
      "本サイトは、運営費をまかなうために Google AdSense による広告を表示しています。Googleとそのパートナーは、広告の表示回数の制御や、同意いただいた場合の広告のパーソナライズのために、広告用Cookieを使用することがあります。",
    adsBody2:
      "EEA・英国・スイスでは、広告用Cookieは初期状態で無効です。Cookieバナーで同意されない限り、広告は非パーソナライズで配信されます。Googleアカウントの広告設定（下記リンク）から、広告のパーソナライズをいつでも管理できます。",
    consentTitle: "閲覧者の選択肢",
    consentBody:
      "Cookieに関する選択は、お使いのブラウザ内（localStorage、キー名「moundmodel-consent」）に保存され、次回以降の訪問にも適用されます。選択は次のボタンからいつでも変更できます。",
    cookieSettings: "Cookie設定を開く",
    linksTitle: "詳細・オプトアウト",
    links: [
      {
        label: "Googleのサービスを使用するサイトから収集した情報のGoogleによる使用",
        href: "https://policies.google.com/technologies/partner-sites",
      },
      {
        label: "Googleプライバシーポリシー",
        href: "https://policies.google.com/privacy",
      },
      {
        label: "Google広告設定 — パーソナライズの管理",
        href: "https://adssettings.google.com",
      },
      {
        label: "Google アナリティクス オプトアウト アドオン",
        href: "https://tools.google.com/dlpage/gaoptout",
      },
      {
        label: "インタレストベース広告について（YourAdChoices）",
        href: "https://optout.aboutads.info",
      },
    ],
    changesBody:
      "データの取り扱いに変更があった場合は、このページを更新し、上記の日付を改訂します。",
  },

  strip: {
    chipTitle: (away: string, home: string, pick: string, pct: string) =>
      `${away} @ ${home}｜予測は${pick}（${pct}）`,
    chipAria: (date: string, away: string, home: string, ok: boolean) =>
      `${date} ${away} @ ${home}、${ok ? "的中" : "外れ"} — タップすると予測と最終スコアが表示されます`,
    gotIt: "✓ 的中",
    missed: "✗ 外れ",
    pickedBefore: "予測は ",
    pickedAfter: (pct: string) => ` の勝利（${pct}）`,
    scoreCallLabel: "スコア予測",
    finalLabel: "最終スコア",
  },
};

export const translations: Record<Lang, Dict> = { en, ja };
