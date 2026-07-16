export const metadata = {
  title: "About — MLB Model",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="space-y-3 text-zinc-600 dark:text-zinc-400">{children}</div>
    </section>
  );
}

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold">About</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          A side project built by Kai Y. that predicts MLB game winners, final
          scores, and run totals — plus how each hitter will do against the
          night's starting pitcher — and keeps score on itself, in public.
        </p>
      </div>

      <Section title="What this is">
        <p>
          Every morning, a machine-learning model predicts each MLB game: who
          wins, by roughly what score, and how many runs get scored. A second
          model works one plate appearance at a time and turns into hitter
          outlooks — the chance each starter gets a hit or homers tonight.
          Every prediction is logged before first pitch and graded against the
          box score after. The record is published whole: hits, misses, and
          everything.
        </p>
      </Section>

      <Section title="The data">
        <p>
          The models train on eight seasons of play-by-play from the official
          MLB feed and nearly six million individual pitches of Statcast
          tracking data — exit velocity, pitch types, quality of contact.
          Team form is distilled into rolling features: recent scoring,
          starting-pitcher quality over the last ten starts, bullpen workload,
          and the actual posted lineup — who is in tonight, who is missing,
          and how much that lineup usually produces. Park effects and
          game-time weather forecasts feed the run-total side.
        </p>
      </Section>

      <Section title="The models">
        <p>
          The game model is a gradient-boosted system that predicts each
          team's runs directly — the winner, the score call, and the game
          total all fall out of the same prediction, so they can never
          disagree with each other. The hitter model classifies every plate
          appearance into eight outcomes (strikeout, walk, single, homer, and
          so on) from the batter's shrunken skill profile crossed with the
          opposing pitcher's arsenal, then aggregates the night's expected
          line analytically.
        </p>
        <p>
          A deliberately simple rating system runs alongside as the in-house
          benchmark. Every change to the models must beat what came before on
          thousands of paired games — with significance tests, not vibes —
          before it ships. Most candidate ideas fail that bar, and the
          failures are logged too.
        </p>
      </Section>

      <Section title="The daily cycle">
        <p>
          A scheduled job runs each morning: it ingests yesterday's games,
          re-grades every outstanding prediction, refreshes team and player
          form, retrains on a weekly cadence, and posts the day's picks. A
          second run in the late afternoon picks up the actual starting
          lineups once teams post them, sharpening the hitter outlooks and the
          missing-regulars signal before first pitch.
        </p>
      </Section>

      <Section title="Keeping myself honest">
        <p>
          Accuracy alone can flatter, so the record page shows more: how far
          the score calls miss, whether a &quot;60% chance&quot; wins 60% of
          the time, and the model&apos;s picks graded next to the betting
          market&apos;s closing expectations — the strongest public benchmark
          there is. The historical record is a strict walk-forward backtest:
          for every past game the model was trained only on games that came
          before it, under the same rules it plays by every night now. An
          automated test guarantees no prediction ever peeks at the future.
        </p>
      </Section>

      <Section title="What this is not">
        <p>
          Betting advice. The models and their outputs are published for
          curiosity, learning, and record-keeping only.
        </p>
      </Section>

      <Section title="Under the hood">
        <p>
          Python and LightGBM for the models; PostgreSQL on AWS for eight
          seasons of games, plate appearances, and pitches; the pipeline runs
          as scheduled batch jobs on AWS Fargate; this site is a static
          Next.js frontend reading a small FastAPI service. The whole system —
          ingestion to models to this page — is a successor to{" "}
          <a href="https://hoopmodel.com" className="underline">
            hoopmodel.com
          </a>
          , rebuilt cloud-native for baseball.
        </p>
      </Section>
    </div>
  );
}
